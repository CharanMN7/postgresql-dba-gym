"""Pydantic models for the PostgreSQL DBA Gym OpenEnv environment.

These are the Action / Observation / State types required by
``openenv-core`` 0.2.x. They live at the root of the package so both
``server.app`` (the FastAPI entrypoint) and ``client.py`` (the typed
``EnvClient`` subclass) can import them without pulling in server-only
dependencies like psycopg2 or sqlparse.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from openenv.core.env_server.types import Action, Observation, State
from pydantic import ConfigDict, Field


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
        default=None,
        description=(
            "Active task id (easy / medium / hard / backup_recovery / "
            "security_audit)"
        ),
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


__all__ = ["DBAAction", "DBAObservation", "DBAState"]
