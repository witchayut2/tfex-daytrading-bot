"""Dormant strategy-research protocol contracts; no replay or trading runtime."""

from app.tfex.research.models import (
    AcceptanceDecision,
    AcceptanceState,
    DataPartition,
    EvaluationMode,
    EvidenceArtifact,
    HoldoutLedger,
    PartitionPlan,
    PerformanceMetrics,
    ResearchCostModel,
    ResearchExecutionPolicy,
    TrialRegistry,
    WalkForwardPlan,
)
from app.tfex.research.protocol import (
    evaluate_acceptance,
    evaluate_execution_eligibility,
    record_holdout_access,
    record_trial_result,
    register_trial,
)

__all__ = [
    "AcceptanceDecision",
    "AcceptanceState",
    "DataPartition",
    "EvaluationMode",
    "EvidenceArtifact",
    "HoldoutLedger",
    "PartitionPlan",
    "PerformanceMetrics",
    "ResearchCostModel",
    "ResearchExecutionPolicy",
    "TrialRegistry",
    "WalkForwardPlan",
    "evaluate_acceptance",
    "evaluate_execution_eligibility",
    "record_holdout_access",
    "record_trial_result",
    "register_trial",
]
