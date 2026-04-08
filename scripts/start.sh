#!/usr/bin/env bash
# Container entrypoint: start PostgreSQL in the background, bootstrap the
# `dba_gym` database and `dba` superuser, then exec uvicorn as PID 1.
set -euo pipefail

PG_BIN=/usr/lib/postgresql/16/bin
export PGDATA=${PGDATA:-/var/lib/postgresql/data}

echo "[start.sh] starting PostgreSQL 16 on 127.0.0.1:5432"
"$PG_BIN/pg_ctl" -D "$PGDATA" -l /tmp/postgres.log \
    -o "-c listen_addresses='127.0.0.1' -c port=5432 -c unix_socket_directories='/tmp'" \
    start

echo "[start.sh] waiting for PostgreSQL to accept connections"
for i in {1..30}; do
    if "$PG_BIN/pg_isready" -h 127.0.0.1 -p 5432 -q; then
        echo "[start.sh] PostgreSQL is ready"
        break
    fi
    sleep 1
    if [[ $i -eq 30 ]]; then
        echo "[start.sh] ERROR: PostgreSQL did not become ready in 30s"
        cat /tmp/postgres.log || true
        exit 1
    fi
done

echo "[start.sh] bootstrapping dba_gym database and dba role (idempotent)"
"$PG_BIN/psql" -h 127.0.0.1 -U postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname='dba_gym'" | grep -q 1 \
    || "$PG_BIN/psql" -h 127.0.0.1 -U postgres -c "CREATE DATABASE dba_gym;"

"$PG_BIN/psql" -h 127.0.0.1 -U postgres -tc \
    "SELECT 1 FROM pg_roles WHERE rolname='dba'" | grep -q 1 \
    || "$PG_BIN/psql" -h 127.0.0.1 -U postgres -c \
       "CREATE ROLE dba LOGIN PASSWORD 'dba' SUPERUSER;"

"$PG_BIN/psql" -h 127.0.0.1 -U postgres -c \
    "GRANT ALL ON DATABASE dba_gym TO dba;"

# Stop postgres cleanly when the container is asked to exit so the data
# directory is left consistent for the next run.
trap '"$PG_BIN/pg_ctl" -D "$PGDATA" -m fast stop || true' EXIT TERM INT

export DBA_GYM_DSN="postgresql://dba:dba@127.0.0.1:5432/dba_gym"

echo "[start.sh] starting uvicorn on 0.0.0.0:8000"
exec uvicorn app.server:app --host 0.0.0.0 --port 8000 --workers 1
