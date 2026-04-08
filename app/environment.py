"""Core OpenEnv environment for the PostgreSQL DBA Gym.

This module defines the Pydantic action / observation / state types
required by ``openenv-core`` 0.2.x and the ``PostgresDBAEnvironment``
class that drives task setup, action execution, and grading against a
live PostgreSQL 16 instance.

Design notes
============

* The environment is a singleton (one instance per server process). All
  state lives on the instance: a shared psycopg2 connection pool, the
  current task, and per-episode scratch on ``DBAState.task_data``.
* ``openenv.core.env_server.types.ResetRequest`` has ``extra="allow"``,
  so any field in the JSON body of ``POST /reset`` flows through into
  ``Environment.reset(**kwargs)``. We accept ``task`` as the task selector
  alongside the standard ``seed`` and ``episode_id``.
* ``step()`` NEVER raises. Any psycopg2 error is captured and returned
  as a normal observation with the error text in ``output`` / ``error``,
  ``reward`` set to the last grading score, and ``done=False``. The
  agent learns to fix typos rather than crash the server.
* All grading is purely deterministic — every reward is computed from
  ``pg_catalog`` / ``information_schema`` / ``pg_stat_*`` queries. Zero
  LLM-as-judge.
* ``close()`` is intentionally a no-op. The HTTP server's request handler
  calls ``env.close()`` after every reset/step, and we cannot afford to
  drop the connection pool or active task state on every request. Real
  cleanup happens via :meth:`shutdown` wired to FastAPI's shutdown event.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import psycopg2
import sqlparse
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import Action, Observation, State
from pydantic import ConfigDict, Field

from app.db import (
    borrow_connection,
    create_pool,
    is_meta_command,
    translate_meta_command,
)

if TYPE_CHECKING:
    from app.tasks.base import BaseTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DBAAction(Action):
    """Action emitted by an agent.

    Attributes:
        sql: SQL statement(s) or supported psql meta-command. Multiple
            semicolon-separated statements are allowed in one action.
        done: Optional self-declared completion flag. The environment
            also auto-terminates when reward >= success_threshold or
            step_count >= max_steps.
    """

    sql: str = Field(default="", description="SQL statement or psql meta-command")
    done: bool = Field(
        default=False, description="Set true to declare the task complete"
    )


class DBAObservation(Observation):
    """Observation returned to the agent after every reset / step."""

    output: str = Field(default="", description="Pretty-printed SQL output or error")
    rows: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Up to 100 result rows as dicts"
    )
    rowcount: Optional[int] = Field(default=None, description="cur.rowcount")
    error: Optional[str] = Field(default=None, description="Postgres error string")
    execution_ms: Optional[float] = Field(
        default=None, description="Wall-clock execution time in ms"
    )
    task_description: Optional[str] = Field(
        default=None, description="Long-form task prompt (only on /reset)"
    )
    task_id: Optional[str] = Field(
        default=None, description="Active task id (easy / medium / hard)"
    )
    step_index: int = Field(default=0, description="1-indexed step counter")
    max_steps: int = Field(default=0, description="Step budget for this task")
    grading_breakdown: Optional[Dict[str, float]] = Field(
        default=None, description="Sub-rubric scores from the grader"
    )


class DBAState(State):
    """Per-episode environment state.

    ``task_data`` is a free-form scratch space tasks use to cache
    things like baseline timings or sample row hashes between
    ``reset()`` and later ``grade()`` calls. The base ``State`` class
    already contributes ``episode_id`` and ``step_count``.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    task_name: Optional[str] = None
    max_steps: int = 25
    last_reward: float = 0.0
    done: bool = False
    task_data: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class PostgresDBAEnvironment(Environment[DBAAction, DBAObservation, DBAState]):
    """Live-PostgreSQL DBA training environment.

    Wraps a single ``ThreadedConnectionPool`` and dispatches each step
    to the currently active :class:`BaseTask`. The environment grades
    every step (rewards are cheap, sub-100ms) so the agent always sees
    a shaped reward signal in its observation.
    """

    # We hold cluster-wide PostgreSQL state, so this env is fundamentally
    # single-tenant. The ``HTTPEnvServer`` defaults to max_concurrent_envs=1
    # which matches.
    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    def __init__(self) -> None:
        super().__init__()
        # Local import to avoid a circular dependency at module load time.
        from app.tasks import build_task_registry

        self._pool = create_pool()
        self._tasks: Dict[str, "BaseTask"] = build_task_registry()
        self._current_task: Optional["BaseTask"] = None
        self._state = DBAState(episode_id=str(uuid.uuid4()))
        logger.info(
            "PostgresDBAEnvironment initialised with tasks=%s",
            sorted(self._tasks.keys()),
        )

    # ------------------------------------------------------------------
    # OpenEnv interface (reset / step / state)
    # ------------------------------------------------------------------

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        task: str = "easy",
    ) -> DBAObservation:
        """Reset the environment and load a specific task.

        Args:
            seed: Unused — task seeds are deterministic by design so the
                grader can compare against cached fixtures.
            episode_id: Optional caller-supplied episode id. We generate
                one if not provided.
            task: One of the registered task ids (``easy``, ``medium``,
                ``hard``). Unknown values fall back to ``easy`` with a
                warning so the agent gets *something* rather than an
                HTTP error.
        """
        if task not in self._tasks:
            logger.warning(
                "Unknown task %r requested; falling back to 'easy'", task
            )
            task = "easy"

        # Tear down whatever task was running before so we don't leak
        # blocker threads, GUC overrides, or stray transactions.
        if self._current_task is not None:
            try:
                self._current_task.teardown(self)
            except Exception:  # pragma: no cover - defensive
                logger.exception("teardown of previous task failed")

        self._state = DBAState(
            task_name=task,
            episode_id=episode_id or str(uuid.uuid4()),
            max_steps=self._tasks[task].MAX_STEPS,
        )

        with borrow_connection(self._pool) as conn:
            self._drop_task_schema(conn)
            self._reset_global_gucs(conn)
            self._terminate_blockers(conn)

        self._current_task = self._tasks[task]
        self._current_task.setup(self)
        return self._current_task.get_initial_observation(self)

    def step(
        self,
        action: DBAAction,
        timeout_s: Optional[float] = None,
    ) -> DBAObservation:
        """Execute one agent action and return a graded observation.

        This method NEVER raises. Errors during SQL execution are
        captured and returned in the observation's ``error`` field.
        """
        self._state.step_count += 1

        if self._current_task is None:
            # Auto-recover: nothing to do, just hand back a placeholder
            # so the agent learns it must call /reset first.
            return DBAObservation(
                output="No active task. Call POST /reset first.",
                error="no_active_task",
                step_index=self._state.step_count,
                max_steps=self._state.max_steps,
                done=True,
                reward=0.0,
            )

        rows, rowcount, ms, err = self._execute_sql(action.sql)
        output = self._format_output(action.sql, rows, rowcount, err)

        try:
            grading = self._current_task.grade(self)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("grader crashed; returning last_reward")
            grading_score = self._state.last_reward
            grading_breakdown: Dict[str, float] = {"grader_error": 0.0}
            grading_notes = [f"grader crashed: {exc}"]
        else:
            grading_score = grading.score
            grading_breakdown = grading.breakdown
            grading_notes = grading.notes

        threshold = self._current_task.SUCCESS_THRESHOLD
        max_steps_reached = self._state.step_count >= self._state.max_steps
        done = (
            bool(action.done)
            or grading_score >= threshold
            or max_steps_reached
        )

        if grading_notes:
            output = f"{output}\n--\n" + "\n".join(grading_notes)

        observation = DBAObservation(
            output=output,
            rows=rows,
            rowcount=rowcount,
            error=err,
            execution_ms=ms,
            task_id=self._state.task_name,
            step_index=self._state.step_count,
            max_steps=self._state.max_steps,
            grading_breakdown=grading_breakdown,
            done=done,
            reward=grading_score,
        )

        self._state.last_reward = grading_score
        self._state.done = done
        return observation

    @property
    def state(self) -> DBAState:
        return self._state

    def close(self) -> None:
        """No-op — see :meth:`shutdown` for real cleanup.

        The HTTP server's request handlers call ``env.close()`` at the
        end of every reset/step (because they treat the env as a
        per-request factory). We hold cluster-wide state and a
        connection pool that must survive across requests, so this
        method is intentionally a no-op. Real teardown happens once,
        on FastAPI shutdown, via :meth:`shutdown`.
        """

    def shutdown(self) -> None:
        """Tear down the active task and close the connection pool.

        Called from the FastAPI ``shutdown`` event handler in
        ``app.server``. Safe to call multiple times.
        """
        if self._current_task is not None:
            try:
                self._current_task.teardown(self)
            except Exception:  # pragma: no cover - defensive
                logger.exception("teardown during shutdown failed")
            self._current_task = None
        try:
            self._pool.closeall()
        except Exception:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------
    # Internal helpers used by tasks
    # ------------------------------------------------------------------

    def borrow(self, statement_timeout_ms: int = 15_000):
        """Public access to the pool's borrow context manager.

        Tasks call ``with env.borrow() as conn:`` rather than touching
        ``self._pool`` directly so the env keeps full control over
        timeouts and cleanup.
        """
        return borrow_connection(self._pool, statement_timeout_ms=statement_timeout_ms)

    def list_tasks(self) -> List[Dict[str, Any]]:
        """Return descriptors for all registered tasks (used by /tasks)."""
        return [
            {
                "id": tid,
                "name": task.NAME,
                "difficulty": task.DIFFICULTY,
                "description": task.SHORT_DESCRIPTION,
                "max_steps": task.MAX_STEPS,
                "success_threshold": task.SUCCESS_THRESHOLD,
            }
            for tid, task in self._tasks.items()
        ]

    def grade_current(self) -> Dict[str, Any]:
        """Run the active task's grader on demand (used by /grade)."""
        if self._current_task is None:
            return {"error": "no_active_task"}
        result = self._current_task.grade(self)
        return {
            "task": self._state.task_name,
            "score": result.score,
            "breakdown": result.breakdown,
            "notes": result.notes,
        }

    # ------------------------------------------------------------------
    # SQL execution
    # ------------------------------------------------------------------

    def _execute_sql(
        self, sql: str
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[int], Optional[float], Optional[str]]:
        """Execute one agent action against PostgreSQL.

        Returns a tuple of ``(rows, rowcount, execution_ms, error_text)``.
        Either ``rows``/``rowcount``/``execution_ms`` are populated, or
        ``error_text`` is — never both. ``rows`` is capped at 100 to keep
        observations small.

        Multi-statement actions (e.g. ``ALTER SYSTEM SET ...; SELECT
        pg_reload_conf();``) are split via :mod:`sqlparse` and executed
        one statement at a time. PostgreSQL otherwise wraps multi-
        statement Simple-Query messages in an implicit transaction
        even with autocommit on, which forbids commands like
        ``ALTER SYSTEM`` and ``VACUUM FULL``. Splitting first lets
        each statement run on its own. ``rows`` reflects the *last*
        statement that produced a result set, so a sequence like
        ``CREATE INDEX ...; SELECT * FROM pg_indexes ...;`` still
        returns the SELECT's rows to the agent.
        """
        if not sql or not sql.strip():
            return None, None, None, "empty_sql"

        # Translate psql meta-commands first.
        if is_meta_command(sql):
            translated = translate_meta_command(sql)
            if translated is None:
                return (
                    None,
                    None,
                    None,
                    f"unsupported meta-command: {sql.strip()!r}. "
                    "Use SQL on pg_catalog or information_schema instead.",
                )
            sql = translated

        statements = [
            s.strip().rstrip(";").strip()
            for s in sqlparse.split(sql)
            if s and s.strip().rstrip(";").strip()
        ]
        if not statements:
            return None, None, None, "empty_sql"

        try:
            with self.borrow() as conn:
                # Make sure DDL/DCL run against task_schema by default so
                # the agent doesn't have to qualify everything.
                with conn.cursor() as cur:
                    cur.execute("SET search_path TO task_schema, public")

                last_rows: Optional[List[Dict[str, Any]]] = None
                last_rowcount: Optional[int] = None
                start = time.perf_counter()
                for stmt in statements:
                    with conn.cursor() as cur:
                        cur.execute(stmt)
                        last_rowcount = cur.rowcount
                        if cur.description is not None:
                            cols = [d.name for d in cur.description]
                            fetched = cur.fetchmany(100)
                            last_rows = [dict(zip(cols, r)) for r in fetched]
                        else:
                            last_rows = None
                elapsed = (time.perf_counter() - start) * 1000.0
                return last_rows, last_rowcount, round(elapsed, 3), None
        except psycopg2.Error as exc:
            return None, None, None, str(exc).strip()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unexpected error in _execute_sql")
            return None, None, None, f"internal_error: {exc}"

    def _format_output(
        self,
        sql: str,
        rows: Optional[List[Dict[str, Any]]],
        rowcount: Optional[int],
        err: Optional[str],
    ) -> str:
        """Render a compact text view of a query result."""
        if err is not None:
            return f"ERROR: {err}"
        if rows is not None:
            if not rows:
                return f"OK ({rowcount} rows)\n[empty result set]"
            cols = list(rows[0].keys())
            header = " | ".join(cols)
            separator = "-+-".join("-" * len(c) for c in cols)
            body_lines = []
            for r in rows[:20]:
                body_lines.append(
                    " | ".join(self._stringify_cell(r[c]) for c in cols)
                )
            tail = ""
            if len(rows) > 20:
                tail = f"\n... ({len(rows) - 20} more rows truncated)"
            return f"{header}\n{separator}\n" + "\n".join(body_lines) + tail
        # Non-result statement (DDL, INSERT, etc.)
        verb = sql.strip().split(None, 1)[0].upper() if sql.strip() else "OK"
        return f"OK ({verb}{f', rowcount={rowcount}' if rowcount is not None else ''})"

    @staticmethod
    def _stringify_cell(value: Any) -> str:
        if value is None:
            return "NULL"
        s = str(value)
        if len(s) > 60:
            s = s[:57] + "..."
        return s

    # ------------------------------------------------------------------
    # Reset helpers
    # ------------------------------------------------------------------

    def _drop_task_schema(self, conn) -> None:
        """Drop and recreate the per-task schema."""
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS task_schema CASCADE")
            cur.execute("CREATE SCHEMA task_schema")
            cur.execute("SET search_path TO task_schema, public")

    def _reset_global_gucs(self, conn) -> None:
        """Undo any ALTER SYSTEM tweaks left over from previous episodes."""
        with conn.cursor() as cur:
            try:
                cur.execute("ALTER SYSTEM RESET ALL")
                cur.execute("SELECT pg_reload_conf()")
            except psycopg2.Error:
                # In rare cases (e.g. read-only mode), the reset may fail.
                # We swallow it: the next ALTER SYSTEM in setup will overwrite.
                pass

    def _terminate_blockers(self, conn) -> None:
        """Kill any leftover Task 3 blocker connections."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE application_name IN ('dba_gym_blocker', 'dba_gym_dedicated') "
                "AND pid <> pg_backend_pid()"
            )


__all__ = [
    "DBAAction",
    "DBAObservation",
    "DBAState",
    "PostgresDBAEnvironment",
]
