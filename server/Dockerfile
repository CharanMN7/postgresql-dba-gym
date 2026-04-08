# PostgreSQL DBA Gym — single-container OpenEnv environment.
#
# Bundles PostgreSQL 16 (apt.postgresql.org) + Python 3.11 + FastAPI/openenv-core
# in one image so the agent can talk to a real database via HTTP. Designed for
# HuggingFace Spaces (port 8000, runs as UID 1000).

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PG_MAJOR=16 \
    PGDATA=/var/lib/postgresql/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENABLE_WEB_INTERFACE=true

# ---- system deps + Postgres apt repo ---------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release locales \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] \
        https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        postgresql-${PG_MAJOR} postgresql-client-${PG_MAJOR} \
 && rm -rf /var/lib/apt/lists/* \
 && localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8

ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# ---- non-root user (HF Spaces convention) ----------------------------------
RUN useradd -m -u 1000 -s /bin/bash appuser \
 && mkdir -p ${PGDATA} /var/run/postgresql /app \
 && chown -R appuser:appuser ${PGDATA} /var/run/postgresql /app

# ---- python deps ------------------------------------------------------------
WORKDIR /app
COPY --chown=appuser:appuser requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ---- application code -------------------------------------------------------
# Build context is the repo root: `docker build -f server/Dockerfile .`
COPY --chown=appuser:appuser server /app/server
COPY --chown=appuser:appuser sql /app/sql
COPY --chown=appuser:appuser scripts /app/scripts
COPY --chown=appuser:appuser models.py __init__.py client.py /app/
COPY --chown=appuser:appuser pyproject.toml openenv.yaml README.md /app/
COPY --chown=appuser:appuser inference.py demo.py /app/
RUN chmod +x /app/scripts/start.sh
ENV PYTHONPATH=/app

USER appuser

# ---- pre-init the postgres cluster at build time ---------------------------
# Saves ~3s of cold-start latency on HF Spaces and bakes a deterministic
# starting state into the image.
RUN /usr/lib/postgresql/${PG_MAJOR}/bin/initdb \
        -D ${PGDATA} \
        --auth-local=trust \
        --auth-host=md5 \
        --username=postgres \
        --encoding=UTF8 \
        --locale=en_US.UTF-8

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["/app/scripts/start.sh"]
