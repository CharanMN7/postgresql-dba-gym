"""Abstract base class for DBA gym tasks.

A task encapsulates four things:

1. A SQL seed that creates the broken/initial database state.
2. A natural-language description shown to the agent on reset.
3. A deterministic grader that returns a 0..1 score derived purely
   from inspecting ``pg_catalog`` / ``information_schema`` / ``pg_stat_*``.
4. Optional teardown logic to release task-specific resources (e.g.,
   the Task 3 idle blocker thread).

Tasks never hold a connection: they borrow one from the env's pool via
``with env.borrow() as conn:`` for each operation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from app.environment import DBAObservation, PostgresDBAEnvironment


@dataclass
class GradingResult:
    """A grader's return value.

    Attributes:
        score: Final reward in [0.0, 1.0].
        breakdown: Sub-rubric scores so the agent can see what's missing.
            Keys are short labels (e.g. ``"indexes"``, ``"bloat"``).
        notes: Optional human-readable hints (shown after the SQL output
            when grading completes).
    """

    score: float
    breakdown: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


class BaseTask(ABC):
    """Abstract base for all DBA gym tasks."""

    NAME: str = "base"
    DIFFICULTY: str = "easy"
    SHORT_DESCRIPTION: str = ""
    MAX_STEPS: int = 25
    SUCCESS_THRESHOLD: float = 0.85
    SEED_PATH: Path = Path("/app/sql/placeholder.sql")

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    @abstractmethod
    def get_description(self) -> str:
        """Long-form prompt shown to the agent at the start of an episode."""

    @abstractmethod
    def setup(self, env: "PostgresDBAEnvironment") -> None:
        """Seed the database and stash any per-episode scratch on env.state."""

    @abstractmethod
    def grade(self, env: "PostgresDBAEnvironment") -> GradingResult:
        """Compute the current reward by inspecting database state."""

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    def teardown(self, env: "PostgresDBAEnvironment") -> None:
        """Release task-specific resources. Default: no-op."""

    # ------------------------------------------------------------------
    # Default observation builder
    # ------------------------------------------------------------------

    def get_initial_observation(
        self, env: "PostgresDBAEnvironment"
    ) -> "DBAObservation":
        """Return the observation handed to the agent on /reset.

        Subclasses rarely need to override this — they only customise
        :meth:`get_description`. We pass the description through both
        ``output`` and ``task_description`` so the agent's first
        ``user`` message has the full prompt.
        """
        from app.environment import DBAObservation

        description = self.get_description()
        return DBAObservation(
            output=description,
            task_description=description,
            task_id=self.DIFFICULTY,
            step_index=0,
            max_steps=self.MAX_STEPS,
            done=False,
            reward=0.0,
            grading_breakdown={},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def load_seed_sql(self) -> str:
        """Read the seed SQL file from disk.

        ``SEED_PATH`` is hard-coded to the in-container path
        (``/app/sql/seed_*.sql``). If that file does not exist (e.g.
        when running tests outside Docker), we fall back to resolving
        the same filename relative to the repo root inferred from
        ``__file__``.
        """
        import os

        if self.SEED_PATH.exists():
            return self.SEED_PATH.read_text(encoding="utf-8")

        env_dir = os.environ.get("DBA_GYM_SQL_DIR")
        if env_dir:
            candidate = Path(env_dir) / self.SEED_PATH.name
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")

        # Last resort: walk up from this file to the repo root and look
        # for ``sql/<basename>``. Works for both ``app/tasks/foo.py``
        # and any future relocation as long as the layout stays
        # ``<root>/sql/...``.
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "sql" / self.SEED_PATH.name
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Could not locate seed SQL for {self.NAME!r}: tried "
            f"{self.SEED_PATH}, $DBA_GYM_SQL_DIR, and parents of {here}"
        )


__all__ = ["BaseTask", "GradingResult"]
