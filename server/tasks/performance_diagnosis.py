"""Task 3 (hard): Performance Diagnosis.

The agent inherits a database with **four** simultaneous problems and
must fix all of them within 30 steps:

1. ``events`` table has no indexes — slow lookups by ``user_id`` and
   ``event_type``.
2. ``bloated_logs`` table has 80% dead rows that were never vacuumed.
3. Three suboptimal global GUCs (``work_mem=64kB``,
   ``random_page_cost=8.0``, ``effective_cache_size=32MB``) are set via
   ``ALTER SYSTEM``.
4. An idle-in-transaction blocker connection (``application_name='dba_gym_blocker'``)
   holds a row-level lock on ``bloated_logs`` and must be terminated
   before any ``VACUUM FULL`` / ``CLUSTER`` will succeed.

Grading is split into four sub-rubrics worth 0.25 each. See
:meth:`PerformanceDiagnosisTask.grade` for the exact rules.

Implementation notes
--------------------
The blocker is a **non-pool** psycopg2 connection running on a daemon
thread. It holds ``BEGIN; SELECT ... FOR UPDATE;`` and then sleeps on
a ``threading.Event``. Because it lives outside the connection pool,
``pg_terminate_backend(pid)`` from the agent simply closes its socket
without disturbing anything else; the thread catches the resulting
``OperationalError`` and exits silently.

We deliberately substitute ``effective_cache_size`` for the planner's
``shared_buffers`` because ``shared_buffers`` requires a full postmaster
restart to apply, and the agent can't restart the database from inside a
single SQL action. ``effective_cache_size`` is reload-friendly and
exercises the same "tune the planner's hardware assumptions" muscle.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2

from app.db import open_dedicated_connection
from app.tasks.base import BaseTask, GradingResult

logger = logging.getLogger(__name__)


# Bad GUC values applied during setup. The grader checks that the agent
# has moved each one back into a "reasonable" range.
_BAD_GUCS: Dict[str, str] = {
    "work_mem": "64kB",
    "random_page_cost": "8.0",
    "effective_cache_size": "32MB",
}


class _IdleBlocker:
    """Helper that owns a non-pool connection holding an open transaction.

    The blocker exists so the agent has a *visible* lock to find via
    ``pg_stat_activity`` and learn to terminate. We keep it dead simple:
    open a connection, ``BEGIN``, ``SELECT ... FOR UPDATE`` on a handful
    of rows from ``bloated_logs``, then block on a ``threading.Event``
    until the task is torn down.
    """

    def __init__(self) -> None:
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.pid: Optional[int] = None

    def start(self) -> int:
        """Open the blocker connection and return its backend PID."""
        self._conn = open_dedicated_connection(application_name="dba_gym_blocker")
        self._conn.autocommit = False
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            row = cur.fetchone()
            self.pid = int(row[0]) if row else None
            cur.execute("SET search_path TO task_schema, public")
            cur.execute(
                "SELECT id FROM task_schema.bloated_logs "
                "ORDER BY id LIMIT 10 FOR UPDATE"
            )
            cur.fetchall()
        # The connection now sits idle-in-transaction. Park a daemon
        # thread on the stop event so we keep ownership of the conn
        # until ``stop()`` is called (or the agent terminates us).
        self._thread = threading.Thread(
            target=self._park, name="dba_gym_blocker", daemon=True
        )
        self._thread.start()
        return self.pid or -1

    def _park(self) -> None:
        # Wait until teardown signals us to release the lock. We poll
        # every second so we notice if the agent has already killed
        # the connection from the database side.
        while not self._stop.is_set():
            if self._conn is None or self._conn.closed:
                return
            self._stop.wait(timeout=1.0)

    def stop(self) -> None:
        """Release the lock and close the blocker connection."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._conn is not None and not self._conn.closed:
            try:
                self._conn.rollback()
            except psycopg2.Error:
                pass
            try:
                self._conn.close()
            except psycopg2.Error:
                pass
        self._conn = None


class PerformanceDiagnosisTask(BaseTask):
    NAME = "Performance Diagnosis"
    DIFFICULTY = "hard"
    SHORT_DESCRIPTION = (
        "Diagnose and fix four simultaneous problems: missing indexes, "
        "table bloat, bad GUCs, and an idle-in-transaction blocker."
    )
    MAX_STEPS = 30
    SUCCESS_THRESHOLD = 0.85
    SEED_PATH = Path("/app/sql/seed_performance_diagnosis.sql")

    def __init__(self) -> None:
        self._blocker: Optional[_IdleBlocker] = None

    # ------------------------------------------------------------------

    def get_description(self) -> str:
        return (
            "TASK 3 — Performance Diagnosis (hard)\n"
            "Database: dba_gym  |  Schema: task_schema\n\n"
            "This database has FOUR simultaneous problems. Find and fix all of them.\n\n"
            "Tables in task_schema:\n"
            "  events       (id, user_id, event_type, payload, created_at)  ~80,000 rows\n"
            "  bloated_logs (id, msg, created_at)                            ~20,000 live rows\n\n"
            "Symptoms to investigate:\n"
            "  1. Queries on events.user_id and events.event_type are slow (full sequential scans).\n"
            "  2. bloated_logs reports far more disk usage than its live row count justifies.\n"
            "  3. Three planner/runtime GUCs are mis-configured at the cluster level.\n"
            "  4. A long-running session is holding a lock on bloated_logs and never finishes.\n\n"
            "Useful inspection queries:\n"
            "  EXPLAIN ANALYZE SELECT ... FROM events WHERE user_id = 42;\n"
            "  SELECT * FROM pg_indexes WHERE schemaname='task_schema';\n"
            "  SELECT * FROM pg_stat_user_tables WHERE schemaname='task_schema';\n"
            "  SELECT name, setting, unit FROM pg_settings WHERE name IN \n"
            "    ('work_mem','random_page_cost','effective_cache_size');\n"
            "  SELECT pid, application_name, state, query \n"
            "    FROM pg_stat_activity WHERE state = 'idle in transaction';\n\n"
            "Fix hints (you can use any of these techniques):\n"
            "  - CREATE INDEX ... ON task_schema.events (...)\n"
            "  - VACUUM FULL task_schema.bloated_logs;  -- (after the lock is gone!)\n"
            "  - ALTER SYSTEM SET <name> = <value>; SELECT pg_reload_conf();\n"
            "  - SELECT pg_terminate_backend(<pid>);\n\n"
            "Target GUC ranges (reload-friendly only — shared_buffers cannot change at runtime):\n"
            "  work_mem              >= 4MB\n"
            "  random_page_cost      <= 2.0\n"
            "  effective_cache_size  >= 512MB\n\n"
            "Grading: 4 sub-rubrics × 0.25 each (indexes, bloat, GUCs, blocker).\n"
            f"Max steps: {self.MAX_STEPS}. Set done=true in your action when finished."
        )

    # ------------------------------------------------------------------

    def setup(self, env) -> None:
        seed_sql = self.load_seed_sql()
        with env.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(seed_sql)

            # Apply the bad GUCs and reload so they take effect.
            with conn.cursor() as cur:
                for name, value in _BAD_GUCS.items():
                    cur.execute(f"ALTER SYSTEM SET {name} = %s", (value,))
                cur.execute("SELECT pg_reload_conf()")

            # Cache initial bloat metrics so the grader can compare.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT n_dead_tup, n_live_tup "
                    "FROM pg_stat_user_tables "
                    "WHERE schemaname='task_schema' AND relname='bloated_logs'"
                )
                row = cur.fetchone()
                initial_dead = int(row[0]) if row and row[0] is not None else 0
                initial_live = int(row[1]) if row and row[1] is not None else 0
                cur.execute(
                    "SELECT pg_total_relation_size('task_schema.bloated_logs')"
                )
                size_row = cur.fetchone()
                initial_size = int(size_row[0]) if size_row else 0

        # Spin up the idle blocker.
        self._blocker = _IdleBlocker()
        try:
            blocker_pid = self._blocker.start()
        except psycopg2.Error:
            logger.exception("failed to start idle blocker")
            blocker_pid = -1

        env.state.task_data["initial_dead_tup"] = initial_dead
        env.state.task_data["initial_live_tup"] = initial_live
        env.state.task_data["initial_table_size"] = initial_size
        env.state.task_data["blocker_pid"] = blocker_pid
        logger.info(
            "Task 3 setup: dead=%d live=%d size=%d blocker_pid=%d",
            initial_dead,
            initial_live,
            initial_size,
            blocker_pid,
        )

    # ------------------------------------------------------------------

    def teardown(self, env) -> None:
        """Release the blocker thread and undo ALTER SYSTEM tweaks."""
        if self._blocker is not None:
            try:
                self._blocker.stop()
            except Exception:  # pragma: no cover - defensive
                logger.exception("blocker stop() failed")
            self._blocker = None

        try:
            with env.borrow() as conn:
                with conn.cursor() as cur:
                    # Defense in depth: terminate any leftover blockers
                    # we may have lost track of.
                    cur.execute(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE application_name = 'dba_gym_blocker' "
                        "AND pid <> pg_backend_pid()"
                    )
                    cur.execute("ALTER SYSTEM RESET ALL")
                    cur.execute("SELECT pg_reload_conf()")
        except psycopg2.Error:
            logger.exception("Task 3 teardown SQL failed")

    # ------------------------------------------------------------------

    def grade(self, env) -> GradingResult:
        breakdown: Dict[str, float] = {}
        notes: List[str] = []

        with env.borrow() as conn:
            idx_score, idx_notes = self._grade_indexes(conn)
            bloat_score, bloat_notes = self._grade_bloat(env, conn)
            guc_score, guc_notes = self._grade_gucs(conn)
            blocker_score, blocker_notes = self._grade_blocker(conn)

        breakdown["indexes"] = round(idx_score, 4)
        breakdown["bloat"] = round(bloat_score, 4)
        breakdown["gucs"] = round(guc_score, 4)
        breakdown["blocker"] = round(blocker_score, 4)
        notes.extend(idx_notes)
        notes.extend(bloat_notes)
        notes.extend(guc_notes)
        notes.extend(blocker_notes)

        score = round(
            min(1.0, idx_score + bloat_score + guc_score + blocker_score),
            4,
        )
        return GradingResult(score=score, breakdown=breakdown, notes=notes)

    # ------------------------------------------------------------------
    # Sub-graders
    # ------------------------------------------------------------------

    @staticmethod
    def _grade_indexes(conn) -> Tuple[float, List[str]]:
        """0.25 max — 0.125 for user_id coverage, 0.125 for event_type."""
        notes: List[str] = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='task_schema' AND tablename='events'"
            )
            rows = cur.fetchall()

        covered: set[str] = set()
        for indexname, indexdef in rows:
            if indexname == "events_pkey":
                continue
            cols = _parse_index_columns(indexdef)
            covered.update(cols)

        score = 0.0
        if "user_id" in covered:
            score += 0.125
        else:
            notes.append("indexes: no index covers events.user_id")
        if "event_type" in covered:
            score += 0.125
        else:
            notes.append("indexes: no index covers events.event_type")
        return score, notes

    @staticmethod
    def _grade_bloat(env, conn) -> Tuple[float, List[str]]:
        """0.25 max — accept either dead-tuple drop OR table-size drop."""
        notes: List[str] = []
        initial_dead = env.state.task_data.get("initial_dead_tup", 0)
        initial_size = env.state.task_data.get("initial_table_size", 0)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT n_dead_tup FROM pg_stat_user_tables "
                "WHERE schemaname='task_schema' AND relname='bloated_logs'"
            )
            row = cur.fetchone()
            current_dead = int(row[0]) if row and row[0] is not None else 0
            cur.execute(
                "SELECT pg_total_relation_size('task_schema.bloated_logs')"
            )
            size_row = cur.fetchone()
            current_size = int(size_row[0]) if size_row else 0

        # Either heuristic crossing the threshold is worth full credit.
        dead_ok = initial_dead > 0 and current_dead < 0.1 * initial_dead
        size_ok = initial_size > 0 and current_size < 0.5 * initial_size

        if dead_ok or size_ok:
            return 0.25, [
                f"bloat: dead_tup {initial_dead}->{current_dead}, "
                f"size {initial_size}->{current_size}"
            ]

        notes.append(
            f"bloat: dead_tup {initial_dead}->{current_dead} "
            f"(need <{int(0.1 * initial_dead)}), "
            f"size {initial_size}->{current_size} "
            f"(need <{int(0.5 * initial_size)})"
        )
        return 0.0, notes

    @staticmethod
    def _grade_gucs(conn) -> Tuple[float, List[str]]:
        """0.25 max — split evenly across the three target GUCs."""
        notes: List[str] = []
        per_check = 0.25 / 3.0  # ≈ 0.0833
        score = 0.0

        with conn.cursor() as cur:
            # work_mem (Postgres reports it in 8kB or kB depending on unit)
            cur.execute(
                "SELECT setting, unit FROM pg_settings WHERE name='work_mem'"
            )
            r = cur.fetchone()
            work_mem_kb = _setting_to_kb(r) if r else 0
            if work_mem_kb >= 4 * 1024:
                score += per_check
            else:
                notes.append(
                    f"gucs: work_mem={work_mem_kb}kB, want >= 4096kB (4MB)"
                )

            # random_page_cost (no unit, just a float)
            cur.execute(
                "SELECT setting FROM pg_settings WHERE name='random_page_cost'"
            )
            r = cur.fetchone()
            try:
                rpc = float(r[0]) if r else 999.0
            except (TypeError, ValueError):
                rpc = 999.0
            if rpc <= 2.0:
                score += per_check
            else:
                notes.append(
                    f"gucs: random_page_cost={rpc}, want <= 2.0"
                )

            # effective_cache_size (in 8kB pages by default)
            cur.execute(
                "SELECT setting, unit FROM pg_settings "
                "WHERE name='effective_cache_size'"
            )
            r = cur.fetchone()
            ecs_kb = _setting_to_kb(r) if r else 0
            if ecs_kb >= 512 * 1024:
                score += per_check
            else:
                notes.append(
                    f"gucs: effective_cache_size={ecs_kb}kB, want >= {512*1024}kB (512MB)"
                )

        return round(score, 4), notes

    @staticmethod
    def _grade_blocker(conn) -> Tuple[float, List[str]]:
        """0.25 max — full credit when no idle blocker remains."""
        notes: List[str] = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = 'dba_gym_blocker' "
                "AND state = 'idle in transaction'"
            )
            row = cur.fetchone()
            count = int(row[0]) if row else 0
        if count == 0:
            return 0.25, []
        notes.append(
            f"blocker: {count} idle-in-transaction session(s) still holding locks"
        )
        return 0.0, notes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_index_columns(indexdef: str) -> set[str]:
    """Pull lowercase column names out of a CREATE INDEX definition."""
    import re

    match = re.search(r"\(([^)]+)\)", indexdef)
    if not match:
        return set()
    cols: set[str] = set()
    for part in match.group(1).split(","):
        token = part.strip().split()[0].strip('"')
        if token:
            cols.add(token.lower())
    return cols


def _setting_to_kb(row) -> int:
    """Normalise a ``pg_settings`` (setting, unit) tuple to kilobytes.

    Postgres reports memory-style GUCs with a unit string like ``kB``,
    ``MB``, ``8kB``, or ``8MB``. We multiply the integer setting by the
    base size implied by the unit and return kilobytes so the grader's
    thresholds can compare apples to apples.
    """
    setting, unit = row[0], row[1]
    try:
        n = int(setting)
    except (TypeError, ValueError):
        return 0
    if unit is None:
        return n  # treat unit-less ints as already-kB (rare for memory GUCs)
    unit = unit.strip()
    multiplier_kb = {
        "B": 1 / 1024,
        "kB": 1,
        "MB": 1024,
        "GB": 1024 * 1024,
        "8kB": 8,
        "8MB": 8 * 1024,
    }.get(unit, 1)
    return int(n * multiplier_kb)
