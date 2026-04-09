"""Task 4: Backup & Recovery.

A simulated data-loss incident has removed rows from ``customers``/``orders``,
corrupted a fraction of customer balance values, and dropped the ``audit_log``
table entirely. Backup copies live inside the same ``task_schema`` as
``backup_customers`` / ``backup_orders`` / ``backup_audit_log``. The agent must
restore the live tables from those backups.

Grading
-------
Four equally-weighted sub-rubrics, each worth 0.25:

A) **customers count** — live row count vs backup row count. Partial credit
   scales linearly from the post-corruption baseline up to the expected total.
B) **orders count** — same partial-credit scheme against the backup.
C) **audit_log** — the dropped table must exist again with the same row count
   as ``backup_audit_log``. Partial credit if the table exists but is under-
   populated.
D) **balances** — row-by-row comparison of ``customers.balance`` against
   ``backup_customers.balance``. Scored as 0.25 × (matching / total).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

from server.tasks.base import BaseTask, GradingResult

logger = logging.getLogger(__name__)


class BackupRecoveryTask(BaseTask):
    NAME = "Backup & Recovery"
    DIFFICULTY = "expert"
    SHORT_DESCRIPTION = (
        "Restore corrupted/deleted data from in-schema backup copies after a "
        "simulated data-loss incident."
    )
    MAX_STEPS = 25
    # Data loss is binary — we require all four sub-rubrics to land for
    # "success". 0.85 would let 3-of-4 slip through, which isn't a real
    # recovery.
    SUCCESS_THRESHOLD = 0.98
    SEED_PATH = Path("/app/sql/seed_backup_recovery.sql")

    # ------------------------------------------------------------------

    def get_description(self) -> str:
        return (
            "TASK 4 — Backup & Recovery (expert)\n"
            "Database: dba_gym  |  Schema: task_schema\n\n"
            "DISASTER: data loss has been detected in the production database.\n"
            "  * customers is missing ~100 rows (deleted)\n"
            "  * orders is missing a large chunk of rows (cascaded + partial delete)\n"
            "  * audit_log has been DROPPED entirely\n"
            "  * Some customers.balance values were corrupted to 0.00\n\n"
            "AVAILABLE BACKUPS (in the same task_schema):\n"
            "  * task_schema.backup_customers\n"
            "  * task_schema.backup_orders\n"
            "  * task_schema.backup_audit_log  (includes JSONB columns)\n\n"
            "OBJECTIVES:\n"
            "  1. Restore all missing customers from backup_customers.\n"
            "  2. Restore all missing orders from backup_orders.\n"
            "  3. Recreate the audit_log table and repopulate it from backup_audit_log.\n"
            "  4. Repair corrupted customers.balance values using backup_customers.\n\n"
            "You can use any SQL — INSERT ... SELECT, CREATE TABLE AS, UPDATE ... FROM,\n"
            "etc. Each /step runs in a fresh pooled connection, so either schema-qualify\n"
            "your tables (``task_schema.customers``) or rely on the env's default\n"
            "search_path, which is already set to ``task_schema, public``.\n\n"
            "Grading: 4 sub-rubrics × 0.25 each (customers, orders, audit_log, balances).\n"
            f"Max steps: {self.MAX_STEPS}. Set done=true in your action when finished."
        )

    # ------------------------------------------------------------------

    def setup(self, env) -> None:
        seed_sql = self.load_seed_sql()
        with env.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(seed_sql)
                cur.execute("SELECT count(*) FROM task_schema.backup_customers")
                expected_customers = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM task_schema.backup_orders")
                expected_orders = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM task_schema.backup_audit_log")
                expected_audit = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM task_schema.customers")
                corrupted_customers = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM task_schema.orders")
                corrupted_orders = int(cur.fetchone()[0])

        env.state.task_data["expected_customers"] = expected_customers
        env.state.task_data["expected_orders"] = expected_orders
        env.state.task_data["expected_audit"] = expected_audit
        env.state.task_data["corrupted_customers"] = corrupted_customers
        env.state.task_data["corrupted_orders"] = corrupted_orders
        logger.info(
            "Task 4 setup: customers %d/%d, orders %d/%d, audit expected %d (table dropped)",
            corrupted_customers,
            expected_customers,
            corrupted_orders,
            expected_orders,
            expected_audit,
        )

    # ------------------------------------------------------------------

    def grade(self, env) -> GradingResult:
        breakdown: Dict[str, float] = {}
        notes: List[str] = []

        with env.borrow() as conn:
            customers_score, n1 = self._grade_count(
                conn,
                "customers",
                env.state.task_data.get("expected_customers", 500),
                env.state.task_data.get("corrupted_customers", 400),
            )
            orders_score, n2 = self._grade_count(
                conn,
                "orders",
                env.state.task_data.get("expected_orders", 2000),
                env.state.task_data.get("corrupted_orders", 0),
            )
            audit_score, n3 = self._grade_audit(
                conn, env.state.task_data.get("expected_audit", 1000)
            )
            balance_score, n4 = self._grade_balances(conn)

        breakdown["customers"] = round(customers_score, 4)
        breakdown["orders"] = round(orders_score, 4)
        breakdown["audit_log"] = round(audit_score, 4)
        breakdown["balances"] = round(balance_score, 4)
        notes.extend(n1)
        notes.extend(n2)
        notes.extend(n3)
        notes.extend(n4)

        score = round(
            min(1.0, customers_score + orders_score + audit_score + balance_score),
            4,
        )
        return GradingResult(score=score, breakdown=breakdown, notes=notes)

    # ------------------------------------------------------------------
    # Sub-graders
    # ------------------------------------------------------------------

    @staticmethod
    def _grade_count(
        conn,
        table: str,
        expected: int,
        corrupted_baseline: int,
    ) -> Tuple[float, List[str]]:
        """0.25 max — linear partial credit between the corruption baseline and
        the backup's row count.

        A fresh reset sits at ``corrupted_baseline`` (0.0 reward). A full
        restoration sits at ``expected`` (0.25 reward). Values in between get
        prorated. Over-shooting (more rows than the backup) caps at 0.25 but
        leaves a note so the agent can tell they inserted duplicates.
        """
        notes: List[str] = []
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM task_schema.{table}")
                actual = int(cur.fetchone()[0])
        except Exception as exc:
            notes.append(f"data: task_schema.{table} not queryable: {exc}")
            return 0.0, notes

        if expected <= corrupted_baseline:
            # Shouldn't happen with the seed as written, but guard against
            # divide-by-zero so the grader never crashes.
            score = 0.25 if actual >= expected else 0.0
        elif actual >= expected:
            score = 0.25
            if actual > expected:
                notes.append(
                    f"data: {table} has {actual} rows, expected {expected} "
                    "(duplicates? check for over-insert)"
                )
        elif actual <= corrupted_baseline:
            score = 0.0
            notes.append(
                f"data: {table} row count {actual} — restore from "
                f"task_schema.backup_{table}"
            )
        else:
            score = 0.25 * (actual - corrupted_baseline) / (expected - corrupted_baseline)
            notes.append(
                f"data: {table} partial — {actual}/{expected} rows "
                f"(baseline={corrupted_baseline})"
            )
        return round(score, 4), notes

    @staticmethod
    def _grade_audit(conn, expected: int) -> Tuple[float, List[str]]:
        """0.25 max — table must exist and have the expected row count."""
        notes: List[str] = []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT to_regclass('task_schema.audit_log') IS NOT NULL"
                )
                exists = bool(cur.fetchone()[0])
                if not exists:
                    notes.append(
                        "data: task_schema.audit_log does not exist — "
                        "recreate from backup_audit_log"
                    )
                    return 0.0, notes
                cur.execute("SELECT count(*) FROM task_schema.audit_log")
                actual = int(cur.fetchone()[0])
        except Exception as exc:
            notes.append(f"data: audit_log not queryable: {exc}")
            return 0.0, notes

        if expected <= 0:
            return 0.25 if actual >= 0 else 0.0, notes
        if actual >= expected:
            if actual > expected:
                notes.append(
                    f"data: audit_log has {actual} rows, expected {expected} "
                    "(duplicates?)"
                )
            return 0.25, notes
        score = 0.25 * (actual / expected)
        notes.append(f"data: audit_log partial — {actual}/{expected} rows")
        return round(score, 4), notes

    @staticmethod
    def _grade_balances(conn) -> Tuple[float, List[str]]:
        """0.25 max — row-by-row balance match against backup_customers.

        Only joins on ``id`` so customers the agent forgot to restore simply
        don't contribute (the matching count stays the same). Total is the
        number of backup rows, so the only way to reach 0.25 is to have every
        backup customer present in ``customers`` with the correct balance.
        """
        notes: List[str] = []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM task_schema.customers c "
                    "JOIN task_schema.backup_customers b ON c.id = b.id "
                    "WHERE c.balance = b.balance"
                )
                matching = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM task_schema.backup_customers")
                total = int(cur.fetchone()[0])
        except Exception as exc:
            notes.append(f"data: balance check failed: {exc}")
            return 0.0, notes

        if total <= 0:
            return 0.0, notes
        score = 0.25 * (matching / total)
        if matching < total:
            notes.append(
                f"data: balances match {matching}/{total} — "
                "UPDATE from backup_customers to repair the rest"
            )
        return round(score, 4), notes
