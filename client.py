"""PostgreSQL DBA Gym Environment Client.

Typed ``EnvClient`` subclass for the DBA gym. Agents can use this to
hold a persistent WebSocket session against a running server instead
of making one-shot HTTP calls, but it is optional — ``inference.py``
talks plain HTTP via ``GenericEnvClient``.
"""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

try:
    from .models import DBAAction, DBAObservation
except ImportError:  # pragma: no cover
    from models import DBAAction, DBAObservation


class PostgresDBAGymEnv(EnvClient[DBAAction, DBAObservation, State]):
    """Client for the PostgreSQL DBA Gym environment.

    Example:
        >>> with PostgresDBAGymEnv(base_url="http://localhost:8000") as client:
        ...     result = client.reset()
        ...     result = client.step(DBAAction(sql="SELECT 1;"))
        ...     print(result.observation.output)
    """

    def _step_payload(self, action: DBAAction) -> Dict:
        return {"sql": action.sql, "done": action.done}

    def _parse_result(self, payload: Dict) -> StepResult[DBAObservation]:
        obs_data = payload.get("observation", {}) or {}
        observation = DBAObservation(
            output=obs_data.get("output", ""),
            rows=obs_data.get("rows"),
            rowcount=obs_data.get("rowcount"),
            error=obs_data.get("error"),
            execution_ms=obs_data.get("execution_ms"),
            task_description=obs_data.get("task_description"),
            task_id=obs_data.get("task_id"),
            step_index=obs_data.get("step_index", 0),
            max_steps=obs_data.get("max_steps", 0),
            grading_breakdown=obs_data.get("grading_breakdown"),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
