"""Task 2 (medium): Schema Migration.

The agent receives a denormalized ``user_orders`` table and must
normalize it into ``customers`` + ``orders`` with proper constraints
plus a backward-compatible ``user_orders_view``.

Grading
-------
Four equally-weighted sub-rubrics, each worth 0.25:

A) **Schema structure** — ``customers(id, name, email, address)`` and
   ``orders(id, customer_id, order_date, amount, status)`` exist with
   sane types.
B) **Data integrity** — total order count matches the original (2000),
   distinct customer count matches (200), and 10 cached spot-check
   tuples can still be found via the customers/orders join. Partial
   credit prorated.
C) **Constraints** — FK from orders.customer_id to customers.id,
   UNIQUE on customers.email, NOT NULL on customers.name and
   customers.email. 0.0625 per check.
D) **Backward compatibility** — ``user_orders_view`` exists, returns
   the same row count, and exposes the same column names as the
   original table.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.tasks.base import BaseTask, GradingResult

logger = logging.getLogger(__name__)


# Column names that the backward-compat view must surface (same set as the
# original user_orders table, minus the surrogate row_id which the agent
# is allowed to drop or rename).
_REQUIRED_VIEW_COLUMNS = {
    "customer_name",
    "customer_email",
    "customer_address",
    "order_date",
    "amount",
    "status",
}


class SchemaMigrationTask(BaseTask):
    NAME = "Schema Migration"
    DIFFICULTY = "medium"
    SHORT_DESCRIPTION = (
        "Normalize a denormalized user_orders table into customers/orders "
        "with constraints and a backward-compatible view."
    )
    MAX_STEPS = 30
    SUCCESS_THRESHOLD = 0.85
    SEED_PATH = Path("/app/sql/seed_schema_migration.sql")

    # ------------------------------------------------------------------

    def get_description(self) -> str:
        return (
            "TASK 2 — Schema Migration (medium)\n"
            "Database: dba_gym  |  Schema: task_schema\n\n"
            "You have a denormalized table user_orders (2000 rows, 200 unique "
            "customers) where customer name, email, and address are repeated "
            "across rows.\n\n"
            "Required:\n"
            "  1. Create table 'customers' with columns: id, name, email, address.\n"
            "     - email UNIQUE\n"
            "     - name and email NOT NULL\n"
            "  2. Create table 'orders' with columns: id, customer_id, order_date, amount, status.\n"
            "     - customer_id has a FOREIGN KEY referencing customers.id\n"
            "  3. Migrate ALL data from user_orders into the new tables, deduplicating customers.\n"
            "  4. Create a view 'user_orders_view' joining customers and orders that returns \n"
            "     the same column names and row count as the original user_orders.\n\n"
            "The original user_orders table can stay or be dropped — your view must still report\n"
            "the same row count.\n\n"
            "Grading: 4 sub-rubrics × 0.25 each (schema, data, constraints, view).\n"
            f"Max steps: {self.MAX_STEPS}. Set done=true in your action when finished."
        )

    # ------------------------------------------------------------------

    def setup(self, env) -> None:
        seed_sql = self.load_seed_sql()
        with env.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(seed_sql)
                cur.execute(
                    "SELECT customer_name, customer_email, order_date, amount, status "
                    "FROM task_schema.user_orders ORDER BY row_id LIMIT 10"
                )
                samples = cur.fetchall()
                cur.execute("SELECT count(*) FROM task_schema.user_orders")
                original_count = cur.fetchone()[0]
                cur.execute(
                    "SELECT count(DISTINCT customer_email) FROM task_schema.user_orders"
                )
                distinct_customers = cur.fetchone()[0]

        env.state.task_data["original_row_count"] = int(original_count)
        env.state.task_data["distinct_customer_count"] = int(distinct_customers)
        # Tuples come back as datetimes/Decimals — keep them as-is so we can
        # bind them straight back into the spot-check query.
        env.state.task_data["sample_rows"] = samples
        logger.info(
            "Task 2 setup: %d rows, %d distinct customers, %d samples cached",
            original_count,
            distinct_customers,
            len(samples),
        )

    # ------------------------------------------------------------------

    def grade(self, env) -> GradingResult:
        breakdown: Dict[str, float] = {}
        notes: List[str] = []

        with env.borrow() as conn:
            schema_score, schema_notes = self._grade_schema(conn)
            data_score, data_notes = self._grade_data(env, conn)
            constraint_score, c_notes = self._grade_constraints(conn)
            view_score, v_notes = self._grade_view(env, conn)

        breakdown["schema"] = round(schema_score, 4)
        breakdown["data"] = round(data_score, 4)
        breakdown["constraints"] = round(constraint_score, 4)
        breakdown["backward_compat_view"] = round(view_score, 4)
        notes.extend(schema_notes)
        notes.extend(data_notes)
        notes.extend(c_notes)
        notes.extend(v_notes)

        score = round(
            min(1.0, schema_score + data_score + constraint_score + view_score),
            4,
        )
        return GradingResult(score=score, breakdown=breakdown, notes=notes)

    # ------------------------------------------------------------------
    # Sub-graders
    # ------------------------------------------------------------------

    @staticmethod
    def _grade_schema(conn) -> Tuple[float, List[str]]:
        """0.25 max — split between customers (0.125) and orders (0.125)."""
        notes: List[str] = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='task_schema' AND table_name='customers'"
            )
            customers_cols = {row[0] for row in cur.fetchall()}
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='task_schema' AND table_name='orders'"
            )
            orders_cols = {row[0] for row in cur.fetchall()}

        required_customer_cols = {"id", "name", "email", "address"}
        required_orders_cols = {"id", "customer_id", "order_date", "amount", "status"}

        if not customers_cols:
            notes.append("schema: customers table missing")
            customers_score = 0.0
        else:
            matched = len(required_customer_cols & customers_cols)
            customers_score = 0.125 * (matched / len(required_customer_cols))
            if matched < len(required_customer_cols):
                notes.append(
                    "schema: customers missing columns "
                    f"{sorted(required_customer_cols - customers_cols)}"
                )

        if not orders_cols:
            notes.append("schema: orders table missing")
            orders_score = 0.0
        else:
            matched = len(required_orders_cols & orders_cols)
            orders_score = 0.125 * (matched / len(required_orders_cols))
            if matched < len(required_orders_cols):
                notes.append(
                    "schema: orders missing columns "
                    f"{sorted(required_orders_cols - orders_cols)}"
                )

        return customers_score + orders_score, notes

    @staticmethod
    def _grade_data(env, conn) -> Tuple[float, List[str]]:
        """0.25 max — count + distinct customers + 10 spot-check joins."""
        original = env.state.task_data.get("original_row_count", 2000)
        distinct = env.state.task_data.get("distinct_customer_count", 200)
        samples = env.state.task_data.get("sample_rows", [])
        notes: List[str] = []

        score = 0.0
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM task_schema.orders")
                count_result = cur.fetchone()
                actual_count = int(count_result[0]) if count_result else 0
                cur.execute(
                    "SELECT count(DISTINCT customer_id) FROM task_schema.orders"
                )
                actual_distinct_result = cur.fetchone()
                actual_distinct = (
                    int(actual_distinct_result[0]) if actual_distinct_result else 0
                )
        except Exception as exc:
            notes.append(f"data: orders table not queryable: {exc}")
            return 0.0, notes

        if actual_count == original:
            score += 0.05
        else:
            notes.append(
                f"data: orders count={actual_count}, expected {original}"
            )

        if actual_distinct == distinct:
            score += 0.05
        else:
            notes.append(
                f"data: distinct customer_id={actual_distinct}, expected {distinct}"
            )

        # Spot-check: each cached sample must be findable via the join.
        # Worth 0.015 per matched sample (10 × 0.015 = 0.15) → with the two
        # 0.05 chunks above we hit a total of 0.25 for a perfect migration.
        per_sample = 0.015
        matched_samples = 0
        for name, email, order_date, amount, status in samples:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM task_schema.orders o "
                        "JOIN task_schema.customers c ON c.id = o.customer_id "
                        "WHERE c.name = %s AND c.email = %s "
                        "AND o.order_date = %s AND o.amount = %s AND o.status = %s "
                        "LIMIT 1",
                        (name, email, order_date, amount, status),
                    )
                    if cur.fetchone():
                        matched_samples += 1
            except Exception:
                # Missing tables / wrong columns — already counted above.
                break
        score += per_sample * matched_samples
        if matched_samples < len(samples):
            notes.append(
                f"data: matched {matched_samples}/{len(samples)} spot-check rows"
            )
        return min(0.25, round(score, 4)), notes

    @staticmethod
    def _grade_constraints(conn) -> Tuple[float, List[str]]:
        """0.25 max, split into 4 × 0.0625 checks."""
        notes: List[str] = []
        score = 0.0

        with conn.cursor() as cur:
            # FK on orders.customer_id
            cur.execute(
                "SELECT 1 FROM information_schema.table_constraints tc "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON tc.constraint_name = ccu.constraint_name "
                "WHERE tc.table_schema='task_schema' AND tc.table_name='orders' "
                "AND tc.constraint_type='FOREIGN KEY' "
                "AND ccu.table_name='customers' AND ccu.column_name='id' "
                "LIMIT 1"
            )
            if cur.fetchone():
                score += 0.0625
            else:
                notes.append("constraints: missing FK orders.customer_id -> customers.id")

            # UNIQUE on customers.email
            cur.execute(
                "SELECT 1 FROM information_schema.table_constraints tc "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON tc.constraint_name = ccu.constraint_name "
                "WHERE tc.table_schema='task_schema' AND tc.table_name='customers' "
                "AND tc.constraint_type='UNIQUE' AND ccu.column_name='email' "
                "LIMIT 1"
            )
            unique_via_constraint = cur.fetchone() is not None
            if not unique_via_constraint:
                # Allow a UNIQUE *index* as an equivalent way to satisfy this.
                cur.execute(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE schemaname='task_schema' AND tablename='customers' "
                    "AND indexdef ILIKE '%UNIQUE%' AND indexdef ILIKE '%email%' "
                    "LIMIT 1"
                )
                unique_via_index = cur.fetchone() is not None
            else:
                unique_via_index = False
            if unique_via_constraint or unique_via_index:
                score += 0.0625
            else:
                notes.append("constraints: missing UNIQUE on customers.email")

            # NOT NULL on customers.name
            cur.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema='task_schema' AND table_name='customers' "
                "AND column_name='name'"
            )
            r = cur.fetchone()
            if r and r[0] == "NO":
                score += 0.0625
            else:
                notes.append("constraints: customers.name must be NOT NULL")

            # NOT NULL on customers.email
            cur.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema='task_schema' AND table_name='customers' "
                "AND column_name='email'"
            )
            r = cur.fetchone()
            if r and r[0] == "NO":
                score += 0.0625
            else:
                notes.append("constraints: customers.email must be NOT NULL")

        return round(score, 4), notes

    @staticmethod
    def _grade_view(env, conn) -> Tuple[float, List[str]]:
        """0.25 max — exists, correct row count, correct columns."""
        notes: List[str] = []
        score = 0.0

        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.views "
                "WHERE table_schema='task_schema' AND table_name='user_orders_view'"
            )
            if cur.fetchone():
                score += 0.08
            else:
                notes.append("view: user_orders_view does not exist")
                return score, notes

            try:
                cur.execute("SELECT count(*) FROM task_schema.user_orders_view")
                view_count_result = cur.fetchone()
                view_count = int(view_count_result[0]) if view_count_result else 0
            except Exception as exc:
                notes.append(f"view: not queryable: {exc}")
                return score, notes

            original = env.state.task_data.get("original_row_count", 2000)
            if view_count == original:
                score += 0.09
            else:
                notes.append(f"view: row count={view_count}, expected {original}")

            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='task_schema' AND table_name='user_orders_view'"
            )
            view_cols = {row[0] for row in cur.fetchall()}
            if _REQUIRED_VIEW_COLUMNS.issubset(view_cols):
                score += 0.08
            else:
                notes.append(
                    "view: missing columns "
                    f"{sorted(_REQUIRED_VIEW_COLUMNS - view_cols)}"
                )

        return round(min(0.25, score), 4), notes
