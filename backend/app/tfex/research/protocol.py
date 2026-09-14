"""Pure validation operations for the dormant research protocol."""

from __future__ import annotations

from app.tfex.errors import ResearchProtocolError, RiskBypassError
from app.tfex.research.models import (
    AcceptanceDecision,
    AcceptanceState,
    ConfirmedHistoryLedger,
    EvaluationMode,
    EvidenceArtifact,
    EvidenceDataClass,
    ExecutionCandidate,
    ExecutionEligibility,
    HoldoutAccess,
    HoldoutAccessPurpose,
    HoldoutLedger,
    HoldoutState,
    InformationArtifact,
    ResearchCostModel,
    ResearchExecutionPolicy,
    ResearchOrderIntent,
    RobustnessVerdict,
    ThresholdStatus,
    TrialDefinition,
    TrialRegistry,
    TrialResult,
)
from app.tfex.risk.boundary import ExecutionAdmission

__all__ = [
    "append_confirmed_artifact",
    "evaluate_acceptance",
    "evaluate_execution_eligibility",
    "record_holdout_access",
    "record_trial_result",
    "register_trial",
]


def record_holdout_access(
    ledger: HoldoutLedger,
    *,
    access: HoldoutAccess,
) -> HoldoutLedger:
    """Record the single permitted access; tuning permanently burns the holdout."""
    if ledger.state is not HoldoutState.UNTOUCHED or ledger.accesses:
        raise ResearchProtocolError("holdout has already been inspected and cannot be reused")
    state = (
        HoldoutState.CONSUMED_FINAL_EVALUATION
        if access.purpose is HoldoutAccessPurpose.FINAL_EVALUATION
        else HoldoutState.BURNED_FOR_TUNING
    )
    return HoldoutLedger(partition_id=ledger.partition_id, state=state, accesses=(access,))


def append_confirmed_artifact(
    ledger: ConfirmedHistoryLedger,
    artifact: InformationArtifact,
) -> ConfirmedHistoryLedger:
    """Append once; an existing ID can neither be replaced nor silently revised."""
    if any(existing.artifact_id == artifact.artifact_id for existing in ledger.artifacts):
        raise ResearchProtocolError("confirmed signal history is immutable")
    return ConfirmedHistoryLedger(artifacts=(*ledger.artifacts, artifact))


def register_trial(registry: TrialRegistry, trial: TrialDefinition) -> TrialRegistry:
    """Append a trial definition after its complete search space was declared."""
    if any(existing.trial_id == trial.trial_id for existing in registry.trials):
        raise ResearchProtocolError("trial ID is immutable and cannot be reused")
    try:
        return TrialRegistry(
            searches=registry.searches,
            trials=(*registry.trials, trial),
            results=registry.results,
        )
    except ValueError as exc:
        raise ResearchProtocolError(str(exc)) from None


def record_trial_result(registry: TrialRegistry, result: TrialResult) -> TrialRegistry:
    """Append a terminal result, retaining failed and rejected experiments."""
    if any(existing.trial_id == result.trial_id for existing in registry.results):
        raise ResearchProtocolError("trial result already exists and cannot be overwritten")
    try:
        return TrialRegistry(
            searches=registry.searches,
            trials=registry.trials,
            results=(*registry.results, result),
        )
    except ValueError as exc:
        raise ResearchProtocolError(str(exc)) from None


def evaluate_execution_eligibility(
    intent: ResearchOrderIntent,
    candidate: ExecutionCandidate,
    *,
    policy: ResearchExecutionPolicy,
    cost_model: ResearchCostModel,
) -> ExecutionEligibility:
    """Validate timing and evidence only; this deliberately does not simulate a fill."""
    try:
        plan = ExecutionAdmission.require_approved_plan(intent.approved_plan)
    except RiskBypassError:
        raise

    reasons: list[str] = []
    if policy.cost_model_id != cost_model.cost_model_id:
        reasons.append("execution policy and cost model differ")
    if plan.cost_assumptions_id != cost_model.cost_model_id:
        reasons.append("approved risk plan and research cost model differ")
    if candidate.symbol != plan.proposal.symbol:
        reasons.append("execution candidate symbol differs from approved raw contract")
    if not candidate.executable:
        reasons.append("candidate is not an executable market event")
    if candidate.event_time <= intent.eligible_after:
        reasons.append("execution must occur at a later valid executable event")
    if candidate.bar_id == intent.signal_bar_id:
        if policy.same_bar_policy.value == "PROHIBITED":
            reasons.append("same-bar execution is prohibited")
        elif (
            candidate.evidence_kind.value != "TRADE_TICK"
            or intent.confirmation_sequence is None
            or candidate.sequence <= intent.confirmation_sequence
        ):
            reasons.append("same-bar execution lacks proven post-confirmation tick sequence")
    return ExecutionEligibility(
        eligible=not reasons,
        event_id=candidate.event_id,
        reasons=tuple(reasons),
    )


_REQUIRED_MODES: dict[AcceptanceState, tuple[EvaluationMode, ...]] = {
    AcceptanceState.RESEARCH_ONLY: (),
    AcceptanceState.BACKTEST_EVIDENCE: (EvaluationMode.BACKTEST,),
    AcceptanceState.WALK_FORWARD_EVIDENCE: (
        EvaluationMode.BACKTEST,
        EvaluationMode.WALK_FORWARD,
    ),
    AcceptanceState.HOLDOUT_EVIDENCE: (
        EvaluationMode.BACKTEST,
        EvaluationMode.WALK_FORWARD,
        EvaluationMode.HOLDOUT,
    ),
    AcceptanceState.PAPER_FORWARD_EVIDENCE: (
        EvaluationMode.BACKTEST,
        EvaluationMode.WALK_FORWARD,
        EvaluationMode.HOLDOUT,
        EvaluationMode.FORWARD_TEST,
        EvaluationMode.PAPER_TRADING,
    ),
    AcceptanceState.LIVE_CANDIDATE: tuple(EvaluationMode),
}


def evaluate_acceptance(
    requested_state: AcceptanceState,
    evidence: tuple[EvidenceArtifact, ...],
    *,
    threshold_status: ThresholdStatus = ThresholdStatus.UNCALIBRATED,
) -> AcceptanceDecision:
    """Fail closed unless every prior evidence stage and governance proof exists.

    The shipped default is deliberately ``UNCALIBRATED``, so repository scaffolding cannot
    promote a strategy. ``LIVE_CANDIDATE`` is evidence status only and never enables orders.
    """
    reasons: list[str] = []
    evidence_ids = tuple(item.evidence_id for item in evidence)
    if len(evidence_ids) != len(set(evidence_ids)):
        reasons.append("evidence IDs must be unique and immutable")
    evidence_modes = tuple(item.mode for item in evidence)
    if len(evidence_modes) != len(set(evidence_modes)):
        reasons.append("each acceptance stage requires one unambiguous evidence artifact")
    if requested_state is not AcceptanceState.RESEARCH_ONLY and (
        threshold_status is ThresholdStatus.UNCALIBRATED
    ):
        reasons.append("performance and risk thresholds are UNCALIBRATED")

    required_modes = _REQUIRED_MODES[requested_state]
    by_mode = {item.mode: item for item in evidence}
    for mode in required_modes:
        item = by_mode.get(mode)
        if item is None:
            reasons.append(f"missing {mode.value} evidence")
            continue
        if item.data_class is not EvidenceDataClass.REAL_RAW_CONTRACT:
            reasons.append(f"{mode.value} evidence is synthetic, not real raw-contract data")
        checks = {
            "market-data validation": item.market_data_validator_passed,
            "provenance/checksum": item.provenance_checksum_passed,
            "TradeProposal -> RiskEngine -> ApprovedPlan route": item.risk_route_verified,
            "cost inclusion": item.costs_included,
            "complete trial registry": item.trial_registry_complete,
            "failed-trial retention": item.failed_trials_retained,
            "parameter-search logging": item.parameter_search_logged,
        }
        reasons.extend(
            f"{mode.value}: missing {name}" for name, passed in checks.items() if not passed
        )
        if item.robustness_verdict is not RobustnessVerdict.PLATEAU_EVIDENCE:
            reasons.append(f"{mode.value}: parameter-neighborhood plateau not demonstrated")
        if mode is EvaluationMode.HOLDOUT and (
            item.holdout_state is not HoldoutState.CONSUMED_FINAL_EVALUATION
        ):
            reasons.append("holdout was not consumed once as an untouched final evaluation")
        if mode in {EvaluationMode.FORWARD_TEST, EvaluationMode.PAPER_TRADING} and (
            not item.live_arriving_data
        ):
            reasons.append(f"{mode.value} did not use live-arriving data")

    if requested_state is AcceptanceState.LIVE_CANDIDATE:
        operational = by_mode.get(EvaluationMode.OPERATIONAL_PROVING)
        if operational is None or not operational.operational_controls_verified:
            reasons.append("operational proving controls are incomplete")
        if threshold_status is not ThresholdStatus.INDEPENDENTLY_REVIEWED:
            reasons.append("LIVE_CANDIDATE requires independently reviewed thresholds")

    granted = requested_state if not reasons else AcceptanceState.RESEARCH_ONLY
    return AcceptanceDecision(
        requested_state=requested_state,
        granted_state=granted,
        threshold_status=threshold_status,
        evidence_ids=evidence_ids,
        reasons=tuple(reasons),
    )
