"""FastAPI server entrypoint for the PostgreSQL DBA Gym.

The standard ``openenv-core`` ``create_app`` helper expects an
*environment factory* — a zero-arg callable that returns a fresh
``Environment`` instance for each incoming request. We hold cluster-wide
PostgreSQL state (a connection pool, the active task, an idle blocker
thread for Task 3), so a fresh-per-request env is not viable. Instead,
we instantiate a single :class:`PostgresDBAEnvironment` at module load
and pass a ``lambda`` factory that returns the same singleton every
time. The env's ``close()`` is a no-op so the per-request cleanup that
``HTTPEnvServer`` performs is harmless; real shutdown happens via the
FastAPI ``shutdown`` event handler defined below.

Beyond the standard ``/reset``, ``/step``, ``/state``, ``/health``,
``/schema``, and ``/docs`` routes that ``create_app`` registers, we add
two convenience routes for the hackathon harness:

* ``GET /tasks`` — descriptors for all registered tasks.
* ``GET /grade/{task_id}`` — re-run the active task's grader on demand.
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException

from openenv.core.env_server.http_server import create_app

try:
    from ..models import DBAAction, DBAObservation
    from .postgres_dba_gym_environment import PostgresDBAEnvironment
except ImportError:  # pragma: no cover
    from models import DBAAction, DBAObservation
    from server.postgres_dba_gym_environment import PostgresDBAEnvironment

logging.basicConfig(
    level=os.getenv("DBA_GYM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Singleton environment + factory passed to create_app
# ---------------------------------------------------------------------------

# Construct the env once. Both /reset and /step in the openenv HTTP server
# will receive *this* instance from the factory below.
_ENV = PostgresDBAEnvironment()


def _env_factory() -> PostgresDBAEnvironment:
    """Return the singleton env. ``create_app`` calls this per request."""
    return _ENV


app = create_app(
    _env_factory,
    DBAAction,
    DBAObservation,
    env_name="postgres_dba_gym",
    max_concurrent_envs=1,
)


# ---------------------------------------------------------------------------
# Extra routes used by the hackathon harness and human debugging
# ---------------------------------------------------------------------------


@app.get("/tasks", tags=["Environment Info"])
def list_tasks():
    """Return descriptors for all three DBA tasks."""
    return {"tasks": _ENV.list_tasks()}


@app.get("/grade/{task_id}", tags=["Environment Info"])
def grade_task(task_id: str):
    """Re-run the active task's grader on demand.

    The ``task_id`` path argument is currently informational — the env
    holds at most one active task at a time, so we just verify it
    matches the running task and then re-grade.
    """
    current = _ENV.state.task_name
    if current is None:
        raise HTTPException(
            status_code=409,
            detail="No active task. Call POST /reset first.",
        )
    if task_id != current:
        raise HTTPException(
            status_code=409,
            detail=f"Active task is {current!r}, not {task_id!r}.",
        )
    return _ENV.grade_current()


# ---------------------------------------------------------------------------
# Lifespan: real shutdown happens here, not in env.close()
# ---------------------------------------------------------------------------


@app.on_event("shutdown")
def _shutdown_env() -> None:
    """Tear down the singleton env when uvicorn stops."""
    logger.info("FastAPI shutdown — releasing PostgresDBAEnvironment resources")
    try:
        _ENV.shutdown()
    except Exception:  # pragma: no cover - defensive
        logger.exception("env.shutdown() raised during FastAPI shutdown")


def main() -> None:
    """Convenience entrypoint when running ``python -m server.app``."""
    import uvicorn

    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
    )


if __name__ == "__main__":
    main()
