"""Task registry for the PostgreSQL DBA Gym."""

from __future__ import annotations

from typing import Dict

from server.tasks.backup_recovery import BackupRecoveryTask
from server.tasks.base import BaseTask
from server.tasks.index_optimization import IndexOptimizationTask
from server.tasks.performance_diagnosis import PerformanceDiagnosisTask
from server.tasks.schema_migration import SchemaMigrationTask
from server.tasks.security_audit import SecurityAuditTask


def build_task_registry() -> Dict[str, BaseTask]:
    """Return a fresh dict of {task_id: task_instance}.

    Tasks are kept as singletons within a server process — the env
    instance owns one of each and re-uses them across episodes.
    """
    return {
        "easy": IndexOptimizationTask(),
        "medium": SchemaMigrationTask(),
        "hard": PerformanceDiagnosisTask(),
        "backup_recovery": BackupRecoveryTask(),
        "security_audit": SecurityAuditTask(),
    }


__all__ = ["BaseTask", "build_task_registry"]
