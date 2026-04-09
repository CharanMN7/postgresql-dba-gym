"""Task 5: Security Audit & Access Control.

Four misconfigurations the agent must fix:

  1. ``analytics_user`` is SUPERUSER — it should be NOSUPERUSER.
  2. ``PUBLIC`` has ``CREATE`` on the ``public`` schema — it should not.
  3. ``readonly_user`` can ``SELECT`` the sensitive ``task_schema.salaries``
     table — access must be revoked.
  4. ``intern_user`` is a LOGIN role with no password — a password must be set.

Grading
-------
Four equally-weighted sub-rubrics, each worth 0.25.

Because the roles are cluster-global (not scoped to ``task_schema``), the
task's ``teardown`` drops them when the next episode starts. The seed SQL
*also* contains an idempotent pre-clean at the top to handle the case where
``teardown`` never ran (server crash, first reset, etc.).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from server.tasks.base import BaseTask, GradingResult

logger = logging.getLogger(__name__)


class SecurityAuditTask(BaseTask):
    NAME = "Security Audit"
    DIFFICULTY = "security_audit"
    SHORT_DESCRIPTION = (
        "Fix four role / permission misconfigurations: a rogue SUPERUSER, "
        "an over-permissive public schema, a sensitive-data leak, and a "
        "passwordless login role."
    )
    MAX_STEPS = 25
    SUCCESS_THRESHOLD = 0.85
    SEED_PATH = Path("/app/sql/seed_security_audit.sql")

    # Roles the seed creates and the teardown must clean up.
    _ROLES_TO_CLEAN = ("analytics_user", "readonly_user", "intern_user")

    # ------------------------------------------------------------------

    def get_description(self) -> str:
        return (
            "TASK 5 — Security Audit & Access Control (security_audit)\n"
            "Database: dba_gym  |  Schema: task_schema\n\n"
            "A compliance audit has flagged four access-control issues:\n\n"
            "  1. analytics_user has SUPERUSER (critical — BI team role should be\n"
            "     NOSUPERUSER).\n"
            "  2. PUBLIC can CREATE objects in the public schema (any role can\n"
            "     make tables there — lock it down).\n"
            "  3. readonly_user can SELECT from task_schema.salaries (sensitive\n"
            "     compensation data — revoke it).\n"
            "  4. intern_user is a LOGIN role with NO password (set one).\n\n"
            "USEFUL INSPECTION QUERIES:\n"
            "  SELECT rolname, rolsuper, rolcanlogin FROM pg_roles\n"
            "      WHERE rolname IN ('analytics_user','readonly_user','intern_user');\n"
            "  SELECT grantee, privilege_type FROM information_schema.role_table_grants\n"
            "      WHERE table_schema='task_schema' AND table_name='salaries';\n"
            "  SELECT rolname, rolpassword IS NOT NULL AS has_password FROM pg_authid\n"
            "      WHERE rolname='intern_user';\n"
            "  SELECT nspname, nspacl FROM pg_namespace WHERE nspname='public';\n\n"
            "OBJECTIVES:\n"
            "  1. ALTER ROLE analytics_user NOSUPERUSER;\n"
            "  2. REVOKE CREATE ON SCHEMA public FROM PUBLIC;\n"
            "  3. REVOKE SELECT ON task_schema.salaries FROM readonly_user;\n"
            "  4. ALTER ROLE intern_user WITH PASSWORD '<your choice>';\n\n"
            "Grading: 4 sub-rubrics × 0.25 each — you can solve them in any order.\n"
            f"Max steps: {self.MAX_STEPS}. Set done=true in your action when finished."
        )

    # ------------------------------------------------------------------

    def setup(self, env) -> None:
        seed_sql = self.load_seed_sql()
        with env.borrow() as conn:
            with conn.cursor() as cur:
                cur.execute(seed_sql)
        logger.info("Task 5 setup: 3 roles seeded with 4 misconfigurations")

    # ------------------------------------------------------------------

    def teardown(self, env) -> None:
        """Drop the seed roles and revert the public-schema grant.

        Mirrors the idempotent DO-block at the top of the seed SQL so a
        ``teardown`` followed by a fresh ``setup`` never collides on
        ``CREATE ROLE``. Errors are swallowed so a half-torn-down state
        can still reset successfully.
        """
        try:
            with env.borrow() as conn:
                with conn.cursor() as cur:
                    cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    for role in self._ROLES_TO_CLEAN:
                        # Role names are hard-coded class constants, not user
                        # input, so plain interpolation is safe here. Wrap
                        # each role's cleanup in its own try so a failure on
                        # one doesn't strand the others.
                        stmt = (
                            f"DO $$ BEGIN "
                            f"IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
                            f"  EXECUTE 'REASSIGN OWNED BY {role} TO dba'; "
                            f"  EXECUTE 'DROP OWNED BY {role}'; "
                            f"  EXECUTE 'DROP ROLE {role}'; "
                            f"END IF; END $$"
                        )
                        try:
                            cur.execute(stmt)
                        except Exception:
                            logger.exception(
                                "security_audit teardown: cleanup of %s failed",
                                role,
                            )
        except Exception:
            logger.exception("security_audit teardown failed; continuing")

    # ------------------------------------------------------------------

    def grade(self, env) -> GradingResult:
        breakdown: Dict[str, float] = {}
        notes: List[str] = []
        score = 0.0

        with env.borrow() as conn:
            with conn.cursor() as cur:
                # ----- 1. analytics_user must NOT be superuser ---------------
                cur.execute(
                    "SELECT rolsuper FROM pg_roles WHERE rolname = 'analytics_user'"
                )
                row = cur.fetchone()
                if row is not None and row[0] is False:
                    breakdown["analytics_not_superuser"] = 0.25
                    score += 0.25
                else:
                    breakdown["analytics_not_superuser"] = 0.0
                    if row is None:
                        notes.append(
                            "security: analytics_user role is missing "
                            "(did the seed run? did the agent drop it?)"
                        )
                    else:
                        notes.append(
                            "security: analytics_user is still SUPERUSER — "
                            "ALTER ROLE analytics_user NOSUPERUSER"
                        )

                # ----- 2. PUBLIC has no CREATE on schema public --------------
                # NOTE: do NOT use ``has_schema_privilege('public', 'public',
                # 'CREATE')`` here — PUBLIC is a pseudo-role, not in pg_roles,
                # and the call raises "role 'public' does not exist". Use
                # aclexplode on pg_namespace.nspacl and look for grantee=0
                # (the OID for PUBLIC). nspacl is NULL when no explicit grants
                # exist, in which case PG defaults mean PUBLIC has no CREATE
                # on public (PG15+).
                cur.execute(
                    "SELECT COALESCE(bool_or(grantee = 0 AND privilege_type = 'CREATE'), false) "
                    "FROM pg_namespace LEFT JOIN LATERAL aclexplode(nspacl) ON true "
                    "WHERE nspname = 'public'"
                )
                row = cur.fetchone()
                public_has_create = bool(row and row[0])
                if not public_has_create:
                    breakdown["public_schema_locked"] = 0.25
                    score += 0.25
                else:
                    breakdown["public_schema_locked"] = 0.0
                    notes.append(
                        "security: PUBLIC still has CREATE on schema public — "
                        "REVOKE CREATE ON SCHEMA public FROM PUBLIC"
                    )

                # ----- 3. readonly_user cannot SELECT salaries ---------------
                # has_table_privilege returns false if the role doesn't exist
                # at all, which is fine: the agent self-penalized by dropping
                # the role.
                try:
                    cur.execute(
                        "SELECT has_table_privilege('readonly_user', "
                        "'task_schema.salaries', 'SELECT')"
                    )
                    row = cur.fetchone()
                    readonly_can_read = bool(row and row[0])
                except Exception as exc:
                    notes.append(f"security: readonly_user check failed: {exc}")
                    readonly_can_read = True  # conservative
                if not readonly_can_read:
                    breakdown["salaries_locked"] = 0.25
                    score += 0.25
                else:
                    breakdown["salaries_locked"] = 0.0
                    notes.append(
                        "security: readonly_user can still SELECT salaries — "
                        "REVOKE SELECT ON task_schema.salaries FROM readonly_user"
                    )

                # ----- 4. intern_user has a password -------------------------
                # ``dba`` is SUPERUSER (scripts/start.sh) so it can read
                # rolpassword from pg_authid.
                cur.execute(
                    "SELECT rolpassword IS NOT NULL FROM pg_authid "
                    "WHERE rolname = 'intern_user'"
                )
                row = cur.fetchone()
                if row is not None and row[0] is True:
                    breakdown["intern_has_password"] = 0.25
                    score += 0.25
                else:
                    breakdown["intern_has_password"] = 0.0
                    if row is None:
                        notes.append(
                            "security: intern_user role is missing "
                            "(did the seed run? did the agent drop it?)"
                        )
                    else:
                        notes.append(
                            "security: intern_user has no password — "
                            "ALTER ROLE intern_user WITH PASSWORD '<choose one>'"
                        )

        return GradingResult(
            score=round(min(1.0, score), 4),
            breakdown=breakdown,
            notes=notes,
        )
