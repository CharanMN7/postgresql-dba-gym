"""PostgreSQL connection management and psql meta-command translation.

The DBA gym uses a single ``ThreadedConnectionPool`` shared across all
``/step`` requests. Tasks borrow a connection through a context manager,
execute their work, and return it to the pool. Long-lived state (like the
Task 3 idle blocker) deliberately uses *non-pool* connections so that
closing the pool never affects them.

We also expose ``translate_meta_command`` which rewrites the most common
``psql`` backslash commands (``\\dt``, ``\\d <table>``, ``\\di``, ``\\dn``,
``\\df``, ``\\l``) into equivalent ``pg_catalog`` / ``information_schema``
queries. This avoids spawning ``psql`` subprocesses while still letting the
agent use familiar diagnostic shortcuts.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extensions import connection as PGConnection

logger = logging.getLogger(__name__)


def get_dsn() -> str:
    """Read the PostgreSQL DSN from the environment.

    The container start script (``scripts/start.sh``) sets ``DBA_GYM_DSN``
    after bootstrapping the database. Outside the container we fall back
    to a sensible local default so unit tests can run against any reachable
    Postgres instance.
    """
    return os.getenv(
        "DBA_GYM_DSN",
        "postgresql://dba:dba@127.0.0.1:5432/dba_gym",
    )


def create_pool(
    dsn: Optional[str] = None,
    minconn: int = 2,
    maxconn: int = 8,
) -> pg_pool.ThreadedConnectionPool:
    """Create the shared psycopg2 connection pool.

    Args:
        dsn: PostgreSQL DSN. Falls back to :func:`get_dsn` if ``None``.
        minconn: Minimum pooled connections kept warm at all times.
        maxconn: Hard upper bound on concurrent borrowed connections.

    Returns:
        A ready-to-use ``ThreadedConnectionPool``.
    """
    return pg_pool.ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        dsn=dsn or get_dsn(),
        application_name="dba_gym_pool",
    )


def _drain_stale_transaction(conn: PGConnection) -> None:
    """Force-clear any stale server-side transaction on *conn*.

    An agent can issue an explicit ``BEGIN`` which starts a server-side
    transaction even when the connection is in autocommit mode.  If an
    error occurs before ``COMMIT``, the connection is stuck in
    ``TRANSACTION_STATUS_INERROR``.  ``conn.rollback()`` is a no-op in
    autocommit mode, and changing ``conn.autocommit`` raises when the
    server is in error state.  The only reliable escape is to send
    ``ROLLBACK`` as raw SQL through a cursor — autocommit mode uses
    ``PQexec`` which forwards any command straight to PostgreSQL, and
    PostgreSQL always accepts ``ROLLBACK`` in an aborted transaction.
    """
    if conn.closed:
        return
    status = conn.get_transaction_status()
    if status in (
        psycopg2.extensions.TRANSACTION_STATUS_INTRANS,
        psycopg2.extensions.TRANSACTION_STATUS_INERROR,
    ):
        with conn.cursor() as cur:
            cur.execute("ROLLBACK")


@contextmanager
def borrow_connection(
    pool: pg_pool.ThreadedConnectionPool,
    statement_timeout_ms: int = 15_000,
    autocommit: bool = True,
) -> Iterator[PGConnection]:
    """Borrow a pooled connection with a per-borrow statement timeout.

    The connection is returned to the pool on exit, even on error. We
    default to ``autocommit=True`` because the agent's actions are
    arbitrary SQL strings, and Postgres' implicit transactions interact
    badly with multi-statement batches that mix DDL and SELECTs.

    Args:
        pool: The shared connection pool.
        statement_timeout_ms: Per-statement timeout enforced via
            ``SET LOCAL statement_timeout``.
        autocommit: Whether to enable autocommit on the borrowed conn.
    """
    conn = pool.getconn()
    try:
        conn.autocommit = autocommit
        _drain_stale_transaction(conn)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        yield conn
    finally:
        try:
            if not conn.closed:
                _drain_stale_transaction(conn)
                if not autocommit:
                    conn.rollback()
        except psycopg2.Error:
            pass
        pool.putconn(conn)


def open_dedicated_connection(
    dsn: Optional[str] = None,
    application_name: str = "dba_gym_dedicated",
) -> PGConnection:
    """Open a non-pooled psycopg2 connection.

    Used for resources that must outlive any single request — most notably
    the Task 3 idle blocker, which holds an open transaction until torn
    down or terminated by the agent.
    """
    conn = psycopg2.connect(
        dsn=dsn or get_dsn(),
        application_name=application_name,
    )
    return conn


# ---------------------------------------------------------------------------
# psql meta-command translation
# ---------------------------------------------------------------------------

# Map common backslash commands to equivalent SQL on pg_catalog /
# information_schema. The translations target ``task_schema`` because that
# is where every task's data lives.
_META_QUERIES: dict[str, str] = {
    r"\\l": (
        "SELECT datname AS name, pg_catalog.pg_get_userbyid(datdba) AS owner, "
        "pg_encoding_to_char(encoding) AS encoding "
        "FROM pg_database WHERE datistemplate = false ORDER BY datname"
    ),
    r"\\dt": (
        "SELECT schemaname, tablename, tableowner "
        "FROM pg_tables "
        "WHERE schemaname IN ('task_schema','public') "
        "ORDER BY schemaname, tablename"
    ),
    r"\\dt\+": (
        "SELECT schemaname, tablename, tableowner, "
        "pg_size_pretty(pg_total_relation_size(format('%I.%I', schemaname, tablename)::regclass)) AS size "
        "FROM pg_tables "
        "WHERE schemaname IN ('task_schema','public') "
        "ORDER BY schemaname, tablename"
    ),
    r"\\di": (
        "SELECT schemaname, indexname, tablename, indexdef "
        "FROM pg_indexes "
        "WHERE schemaname IN ('task_schema','public') "
        "ORDER BY schemaname, tablename, indexname"
    ),
    r"\\di\+": (
        "SELECT schemaname, indexname, tablename, "
        "pg_size_pretty(pg_relation_size(format('%I.%I', schemaname, indexname)::regclass)) AS size, "
        "indexdef "
        "FROM pg_indexes "
        "WHERE schemaname IN ('task_schema','public') "
        "ORDER BY schemaname, tablename, indexname"
    ),
    r"\\dn": (
        "SELECT nspname AS schema, pg_catalog.pg_get_userbyid(nspowner) AS owner "
        "FROM pg_namespace "
        "WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' "
        "ORDER BY nspname"
    ),
    r"\\df": (
        "SELECT n.nspname AS schema, p.proname AS function "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'task_schema' "
        "ORDER BY p.proname"
    ),
}

# `\d <table>` is a special case: it takes an argument and dispatches to a
# multi-result describe. We translate it into an information_schema query
# scoped to the named table.
_DESCRIBE_TABLE_RE = re.compile(r"^\s*\\d\+?\s+([\w\".]+)\s*;?\s*$")


def is_meta_command(text: str) -> bool:
    """Return True if the input looks like a psql backslash command."""
    return text.lstrip().startswith("\\")


def translate_meta_command(text: str) -> Optional[str]:
    """Translate a psql meta-command into an equivalent SQL query.

    Returns ``None`` for unsupported meta-commands so the caller can
    return a helpful error observation. Returns the rewritten SQL string
    for supported commands.
    """
    stripped = text.strip().rstrip(";").strip()

    # `\d <table>` — describe a specific table
    m = _DESCRIBE_TABLE_RE.match(stripped)
    if m:
        raw = m.group(1).replace('"', '').strip()
        if "." in raw:
            schema, table = raw.split(".", 1)
        else:
            schema, table = "task_schema", raw
        return (
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
            "ORDER BY ordinal_position"
        )

    for pattern, query in _META_QUERIES.items():
        if re.fullmatch(pattern, stripped):
            return query

    return None


__all__ = [
    "borrow_connection",
    "create_pool",
    "get_dsn",
    "is_meta_command",
    "open_dedicated_connection",
    "translate_meta_command",
]
