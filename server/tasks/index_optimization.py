"""Task 1 (easy): Index Optimization.

Setup
-----
Create a 120K-row ``orders`` table with deterministic content. The agent
sees a slow target query that does a sequential scan and is asked to add
indexes that speed it up.

Grading
-------
Reward is shaped:

* ``speedup_score = min(1.0, (baseline_ms / new_ms) / 10.0)`` — a 10x
  speedup is worth 1.0; lesser improvements get partial credit.
* ``optimal_bonus = 0.10`` if any index covers all of
  {customer_id, status, order_date}.
* ``partial_bonus = 0.05`` if any index covers {customer_id, status}
  (only awarded if no optimal index already triggered the larger bonus).
* Final reward is ``min(1.0, speedup + optimal + partial)``.

The baseline timing is captured in :meth:`setup` (median of 2 warm runs)
and stored on ``env.state.task_data`` so grading can compute the ratio
without re-warming on every step.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from pathlib import Path
from typing import List, Set

from server.tasks.base import BaseTask, GradingResult

logger = logging.getLogger(__name__)


TARGET_QUERY = (
    "SELECT * FROM task_schema.orders "
    "WHERE customer_id = 12345 AND status = 'pending' "
    "ORDER BY order_date DESC"
)


class IndexOptimizationTask(BaseTask):
    NAME = "Index Optimization"
    DIFFICULTY = "easy"
    SHORT_DESCRIPTION = (
        "Speed up a slow query on a 120K-row orders table by adding indexes."
    )
    MAX_STEPS = 25
    SUCCESS_THRESHOLD = 0.85
    SEED_PATH = Path("/app/sql/seed_index_optimization.sql")

    # ------------------------------------------------------------------

    def get_description(self) -> str:
        return (
            "TASK 1 — Index Optimization (easy)\n"
            "Database: dba_gym  |  Schema: task_schema\n"
            "Table: orders (~120K rows, columns: id, customer_id, order_date, "
            "status, amount, region)\n\n"
            "A query is running slowly:\n"
            "    " + TARGET_QUERY + "\n\n"
            "Your job: speed it up by creating the right index(es).\n"
            "You can run any SQL: EXPLAIN ANALYZE, CREATE INDEX, SELECT * FROM "
            "pg_indexes WHERE schemaname='task_schema', etc.\n\n"
            "Reward formula (shaped):\n"
            "  speedup = min(1.0, (baseline_ms / new_ms) / 10.0)\n"
            "  +0.10 if any index covers {customer_id, status, order_date}\n"
            "  +0.05 if any index covers {customer_id, status} (only if no optimal index)\n"
            "  reward = min(1.0, speedup + bonuses)\n\n"
            f"Max steps: {self.MAX_STEPS}. Set done=true in your action when finished."
        )

    # ------------------------------------------------------------------

    def setup(self, env) -> None:
        seed_sql = self.load_seed_sql()
        with env.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(seed_sql)

        baseline_ms = self._measure_query_ms(env, runs=3, drop_first=True)
        env.state.task_data["target_query"] = TARGET_QUERY
        env.state.task_data["baseline_ms"] = baseline_ms
        logger.info("Task 1 baseline_ms = %.3f", baseline_ms)

    # ------------------------------------------------------------------

    def grade(self, env) -> GradingResult:
        baseline_ms: float = env.state.task_data.get("baseline_ms", 50.0)

        new_ms = self._measure_query_ms(env, runs=2, drop_first=False)
        speedup_score = max(
            0.0,
            min(1.0, (baseline_ms / max(new_ms, 0.01)) / 10.0),
        )

        index_columns = self._index_columns(env)
        has_optimal = any(
            {"customer_id", "status", "order_date"}.issubset(cols)
            for cols in index_columns
        )
        has_partial = any(
            {"customer_id", "status"}.issubset(cols) for cols in index_columns
        )

        optimal_bonus = 0.10 if has_optimal else 0.0
        partial_bonus = 0.05 if (has_partial and not has_optimal) else 0.0

        score = min(1.0, speedup_score + optimal_bonus + partial_bonus)

        breakdown = {
            "speedup": round(speedup_score, 4),
            "optimal_index_bonus": round(optimal_bonus, 4),
            "partial_index_bonus": round(partial_bonus, 4),
        }
        notes = [
            f"baseline={baseline_ms:.2f}ms  current={new_ms:.2f}ms  "
            f"ratio={baseline_ms / max(new_ms, 0.01):.2f}x",
            f"indexes_present={[sorted(c) for c in index_columns] or 'none'}",
        ]
        return GradingResult(score=score, breakdown=breakdown, notes=notes)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _measure_query_ms(env, runs: int, drop_first: bool) -> float:
        """Run the target query under EXPLAIN ANALYZE and return median ms.

        We use FORMAT JSON so we can pull the ``Execution Time`` directly
        from the planner output rather than scraping the textual form.
        """
        samples: List[float] = []
        with env.borrow() as conn:
            with conn.cursor() as cur:
                for _ in range(runs):
                    cur.execute(
                        "EXPLAIN (ANALYZE, FORMAT JSON, BUFFERS) " + TARGET_QUERY
                    )
                    plan = cur.fetchone()[0]
                    if isinstance(plan, str):
                        plan = json.loads(plan)
                    samples.append(float(plan[0]["Execution Time"]))
        if drop_first and len(samples) > 1:
            samples = samples[1:]
        return statistics.median(samples)

    @staticmethod
    def _index_columns(env) -> List[Set[str]]:
        """Return the set of columns covered by each user index on orders.

        Excludes the implicit primary key (orders_pkey).
        """
        out: List[Set[str]] = []
        with env.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT indexname, indexdef "
                    "FROM pg_indexes "
                    "WHERE schemaname = 'task_schema' AND tablename = 'orders'"
                )
                rows = cur.fetchall()
        for indexname, indexdef in rows:
            if indexname == "orders_pkey":
                continue
            cols = _parse_index_columns(indexdef)
            if cols:
                out.append(cols)
        return out


_INDEX_COL_RE = re.compile(r"\(([^)]+)\)")


def _parse_index_columns(indexdef: str) -> Set[str]:
    """Pull the column names out of a CREATE INDEX definition.

    Handles ``CREATE INDEX foo ON task_schema.orders USING btree (a, b DESC)``
    and similar variants. We strip operator classes / sort modifiers
    (``DESC``, ``ASC``, ``NULLS FIRST``...) and quoted identifiers.
    """
    match = _INDEX_COL_RE.search(indexdef)
    if not match:
        return set()
    raw = match.group(1)
    cols: Set[str] = set()
    for part in raw.split(","):
        token = part.strip().split()[0]  # drop ASC/DESC/NULLS modifiers
        token = token.strip('"')
        if token:
            cols.add(token.lower())
    return cols
