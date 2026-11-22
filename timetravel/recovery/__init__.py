"""Durable transaction history and deterministic recovery primitives for Time-Travel DB."""
from .dependencies import (
    DependencyEdge,
    ForeignKey,
    UnsupportedRelationshipError,
    inspect_foreign_keys,
    relationship_summary,
)
from .integrity import RecoveryConflictError, analyze_conflicts, validate_step_schema
from .change_tracker import (
    ChangeEvent,
    TransactionRecord,
    capture_scope,
    ensure_history,
    fetch_events,
    fetch_events_after_timestamp,
    fetch_transactions,
    history_installed,
    latest_event_id,
)
from .recovery_engine import (
    create_plan,
    dry_run_plan,
    execute_plan,
    restore_snapshot,
    snapshot,
)
from .recovery_planner import (
    RecoveryPlan,
    RecoveryStep,
    build_plan_after_event,
    build_plan_after_timestamp,
    explain_plan,
)
from .transaction_logger import ensure_schema, install
from .verification import (
    VerificationBaseline,
    build_baseline,
    capture_reference,
    checksum_database,
    compare_baselines,
    row_checksum,
    verify_state_against,
)

__all__ = [
    "ChangeEvent",
    "TransactionRecord",
    "VerificationBaseline",
    "RecoveryPlan",
    "RecoveryStep",
    "RecoveryConflictError",
    "DependencyEdge",
    "ForeignKey",
    "UnsupportedRelationshipError",
    "analyze_conflicts",
    "inspect_foreign_keys",
    "validate_step_schema",
    "build_baseline",
    "build_plan_after_event",
    "build_plan_after_timestamp",
    "capture_reference",
    "checksum_database",
    "compare_baselines",
    "capture_scope",
    "create_plan",
    "dry_run_plan",
    "ensure_history",
    "ensure_schema",
    "execute_plan",
    "explain_plan",
    "fetch_events",
    "fetch_events_after_timestamp",
    "fetch_transactions",
    "history_installed",
    "install",
    "latest_event_id",
    "relationship_summary",
    "restore_snapshot",
    "row_checksum",
    "snapshot",
    "verify_state_against",
]
