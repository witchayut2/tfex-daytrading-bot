"""Causal partition, walk-forward, registry, cost, and acceptance contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.tfex.costs.models import (
    CostScenario,
    FeeComponent,
    FeeKind,
    FeeProvenanceStatus,
    RoundTripCostEstimate,
)
from app.tfex.errors import ResearchProtocolError
from app.tfex.research.models import (
    AcceptanceState,
    ConfirmedHistoryLedger,
    DataArrivalMode,
    DataPartition,
    DecisionSnapshot,
    EvaluationMode,
    EvaluationRun,
    EvidenceArtifact,
    EvidenceDataClass,
    ExitPolicyKind,
    FeatureDefinition,
    HoldoutAccess,
    HoldoutAccessPurpose,
    HoldoutLedger,
    HoldoutState,
    InformationArtifact,
    NormalizationScope,
    ParameterSearchDeclaration,
    PartitionMethod,
    PartitionPlan,
    PartitionRole,
    ResearchCostModel,
    RobustnessVerdict,
    StrategyFamily,
    ThresholdStatus,
    TrialDefinition,
    TrialRegistry,
    TrialResult,
    TrialStatus,
    WalkForwardFold,
    WalkForwardMethod,
    WalkForwardPlan,
)
from app.tfex.research.protocol import (
    append_confirmed_artifact,
    evaluate_acceptance,
    record_holdout_access,
    record_trial_result,
    register_trial,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def _partition(role: PartitionRole, start_day: int, end_day: int) -> DataPartition:
    return DataPartition(
        partition_id=f"partition:{role.value}",
        role=role,
        start=T0 + timedelta(days=start_day),
        end=T0 + timedelta(days=end_day),
        dataset_id="s50u26-real-v1",
        dataset_sha256=HASH,
        source="Settrade Open API",
        symbol="S50U26",
        source_timezone="Asia/Bangkok",
        normalized_timezone="UTC",
        synthetic=False,
    )


def _partition_plan() -> PartitionPlan:
    return PartitionPlan(
        plan_id="partition-plan:v1",
        created_at=T0,
        partitions=(
            _partition(PartitionRole.DEVELOPMENT_CALIBRATION, 0, 10),
            _partition(PartitionRole.VALIDATION, 10, 15),
            _partition(PartitionRole.FINAL_HOLDOUT, 15, 20),
            _partition(PartitionRole.FORWARD_PAPER, 20, 25),
        ),
    )


def _fold(
    fold_id: str,
    calibration_start: int,
    calibration_end: int,
    validation_start: int,
    validation_end: int,
) -> WalkForwardFold:
    return WalkForwardFold(
        fold_id=fold_id,
        calibration_start=T0 + timedelta(days=calibration_start),
        calibration_end=T0 + timedelta(days=calibration_end),
        validation_start=T0 + timedelta(days=validation_start),
        validation_end=T0 + timedelta(days=validation_end),
        parameters_selected_at=T0 + timedelta(days=calibration_end),
        selected_parameter_set_id=f"parameters:{fold_id}",
        trade_count=10,
        gross_pnl_thb=Decimal("1000"),
        total_costs_thb=Decimal("100"),
        net_pnl_thb=Decimal("900"),
        expectancy_r=Decimal("0.1"),
        max_drawdown_thb=Decimal("250"),
        rejection_reasons=(),
    )


def _search() -> ParameterSearchDeclaration:
    return ParameterSearchDeclaration(
        search_id="search:a:v1",
        declared_at=T0,
        strategy=StrategyFamily.A,
        parameter_set_ids=("parameters:a:1", "parameters:a:2"),
        filter_variant_ids=("filter:none",),
        exit_variants=(ExitPolicyKind.FIXED_R,),
        stop_variant_ids=("stop:structure",),
    )


def _trial(trial_id: str = "trial:a:1") -> TrialDefinition:
    return TrialDefinition(
        trial_id=trial_id,
        registered_at=T0 + timedelta(seconds=1),
        strategy=StrategyFamily.A,
        evaluation_mode=EvaluationMode.BACKTEST,
        partition_plan_id="partition-plan:v1",
        parameter_search_id="search:a:v1",
        parameter_set_id="parameters:a:1",
        filter_variant_id="filter:none",
        exit_variant=ExitPolicyKind.FIXED_R,
        stop_variant_id="stop:structure",
        cost_model_id="costs:research:v1",
        execution_policy_id="execution:next-event:v1",
    )


def _evidence(
    mode: EvaluationMode,
    *,
    data_class: EvidenceDataClass = EvidenceDataClass.REAL_RAW_CONTRACT,
) -> EvidenceArtifact:
    return EvidenceArtifact(
        evidence_id=f"evidence:{mode.value}",
        mode=mode,
        trial_id=f"trial:{mode.value}",
        strategy=StrategyFamily.A,
        data_class=data_class,
        market_data_validator_passed=True,
        provenance_checksum_passed=True,
        risk_route_verified=True,
        costs_included=True,
        trial_registry_complete=True,
        failed_trials_retained=True,
        parameter_search_logged=True,
        robustness_verdict=RobustnessVerdict.PLATEAU_EVIDENCE,
        holdout_state=(
            HoldoutState.CONSUMED_FINAL_EVALUATION if mode is EvaluationMode.HOLDOUT else None
        ),
        live_arriving_data=mode in {EvaluationMode.FORWARD_TEST, EvaluationMode.PAPER_TRADING},
        operational_controls_verified=mode is EvaluationMode.OPERATIONAL_PROVING,
    )


def test_partition_plan_is_chronological_only_and_preserves_raw_identity() -> None:
    plan = _partition_plan()

    assert plan.method is PartitionMethod.CHRONOLOGICAL
    assert [part.role for part in plan.partitions] == list(PartitionRole)
    assert {part.symbol for part in plan.partitions} == {"S50U26"}
    assert not any(part.continuous_contract for part in plan.partitions)

    with pytest.raises(ValidationError, match="PartitionMethod"):
        PartitionPlan(
            plan_id="random",
            method="RANDOM",  # type: ignore[arg-type]
            created_at=T0,
            partitions=plan.partitions,
        )


def test_partition_overlap_and_contract_splicing_are_rejected() -> None:
    plan = _partition_plan()
    overlap = plan.partitions[1].model_copy(
        update={"start": plan.partitions[0].end - timedelta(minutes=1)}
    )
    with pytest.raises(ValidationError, match="may not overlap"):
        PartitionPlan(
            plan_id="overlap",
            created_at=T0,
            partitions=(plan.partitions[0], overlap, *plan.partitions[2:]),
        )

    changed_symbol = plan.partitions[-1].model_copy(update={"symbol": "S50Z26"})
    with pytest.raises(ValidationError, match="may not splice"):
        PartitionPlan(
            plan_id="splice",
            created_at=T0,
            partitions=(*plan.partitions[:-1], changed_symbol),
        )


def test_tuning_or_inspection_burns_holdout_and_it_cannot_be_reused() -> None:
    ledger = HoldoutLedger(partition_id="partition:holdout")
    burned = record_holdout_access(
        ledger,
        access=HoldoutAccess(
            trial_id="trial:tuning",
            purpose=HoldoutAccessPurpose.TUNING,
            accessed_at=T0,
        ),
    )

    assert burned.state is HoldoutState.BURNED_FOR_TUNING
    with pytest.raises(ResearchProtocolError, match="cannot be reused"):
        record_holdout_access(
            burned,
            access=HoldoutAccess(
                trial_id="trial:final",
                purpose=HoldoutAccessPurpose.FINAL_EVALUATION,
                accessed_at=T0 + timedelta(days=1),
            ),
        )


def test_walk_forward_windows_are_causal_for_anchored_and_rolling_research() -> None:
    anchored = WalkForwardPlan(
        plan_id="wf:anchored",
        method=WalkForwardMethod.ANCHORED,
        folds=(_fold("a1", 0, 5, 5, 7), _fold("a2", 0, 7, 7, 9)),
    )
    rolling = WalkForwardPlan(
        plan_id="wf:rolling",
        method=WalkForwardMethod.ROLLING,
        folds=(_fold("r1", 0, 5, 5, 7), _fold("r2", 2, 7, 7, 9)),
    )

    assert anchored.method is WalkForwardMethod.ANCHORED
    assert rolling.method is WalkForwardMethod.ROLLING
    with pytest.raises(ValidationError, match="calibration window"):
        _fold("future-selected", 0, 5, 5, 7).model_copy(
            update={"parameters_selected_at": T0 + timedelta(days=6)}
        ).model_validate(
            _fold("future-selected", 0, 5, 5, 7)
            .model_copy(update={"parameters_selected_at": T0 + timedelta(days=6)})
            .model_dump()
        )


@pytest.mark.anti_repaint
def test_future_information_and_early_pivot_confirmation_are_rejected() -> None:
    pivot = InformationArtifact(
        artifact_id="pivot:1",
        event_time=T0,
        confirmed_at=T0 + timedelta(minutes=3),
        content_sha256=HASH,
    )
    with pytest.raises(ValidationError, match="confirmed in the future"):
        DecisionSnapshot(
            decision_time=T0 + timedelta(minutes=2),
            available_information=(pivot,),
        )

    allowed = DecisionSnapshot(
        decision_time=pivot.confirmed_at,
        available_information=(pivot,),
    )
    assert allowed.available_information == (pivot,)


@pytest.mark.anti_repaint
def test_future_shifts_centered_windows_and_full_frame_normalization_are_unrepresentable() -> None:
    valid = FeatureDefinition(
        feature_id="feature:causal",
        lookback_bars=20,
        shift_periods=1,
        normalization_scope=NormalizationScope.EXPANDING_PAST_ONLY,
    )
    assert valid.confirmed_history_immutable

    with pytest.raises(ValidationError):
        FeatureDefinition(
            feature_id="feature:future-shift",
            lookback_bars=20,
            shift_periods=-1,
            normalization_scope=NormalizationScope.EXPANDING_PAST_ONLY,
        )
    with pytest.raises(ValidationError):
        FeatureDefinition(
            feature_id="feature:centered",
            lookback_bars=20,
            shift_periods=0,
            centered_rolling=True,  # type: ignore[arg-type]
            normalization_scope=NormalizationScope.EXPANDING_PAST_ONLY,
        )
    with pytest.raises(ValidationError):
        FeatureDefinition(
            feature_id="feature:full-frame",
            lookback_bars=20,
            shift_periods=0,
            normalization_scope="FULL_FRAME",  # type: ignore[arg-type]
        )


@pytest.mark.anti_repaint
def test_confirmed_history_cannot_be_revised() -> None:
    first = InformationArtifact(
        artifact_id="signal:1",
        event_time=T0,
        confirmed_at=T0 + timedelta(minutes=1),
        content_sha256=HASH,
    )
    ledger = append_confirmed_artifact(ConfirmedHistoryLedger(), first)
    revised = first.model_copy(update={"content_sha256": "b" * 64})

    with pytest.raises(ResearchProtocolError, match="immutable"):
        append_confirmed_artifact(ledger, revised)


def test_research_costs_require_fee_commission_slippage_multiplier_and_tick() -> None:
    fees = RoundTripCostEstimate(
        scenario=CostScenario.BACKTEST,
        components=(
            FeeComponent(
                kind=FeeKind.EXCHANGE_FEE,
                label="exchange cap stress assumption",
                value_thb_per_contract_per_side=Decimal("7"),
                status=FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP,
            ),
            FeeComponent(
                kind=FeeKind.BROKER_COMMISSION,
                label="broker research assumption",
                value_thb_per_contract_per_side=Decimal("10"),
                status=FeeProvenanceStatus.USER_ASSUMPTION,
            ),
        ),
    )
    costs = ResearchCostModel(
        cost_model_id="costs:research:v1",
        round_trip_fees=fees,
        slippage_points_per_side=Decimal("0.2"),
        contract_multiplier_thb_per_point=Decimal("200"),
        tick_size_points=Decimal("0.1"),
        provenance="research assumptions; actual broker charges remain unverified",
    )

    assert costs.status.value == "RESEARCH_ASSUMPTION"
    with pytest.raises(ValidationError, match="exchange and broker"):
        ResearchCostModel(
            cost_model_id="costs:incomplete",
            round_trip_fees=RoundTripCostEstimate(
                scenario=CostScenario.BACKTEST,
                components=(fees.components[1],),
            ),
            slippage_points_per_side=Decimal("0.2"),
            contract_multiplier_thb_per_point=Decimal("200"),
            tick_size_points=Decimal("0.1"),
            provenance="incomplete test",
        )


def test_trial_ids_are_immutable_search_is_predeclared_and_failures_are_retained() -> None:
    registry = TrialRegistry(searches=(_search(),))
    registry = register_trial(registry, _trial())
    registry = record_trial_result(
        registry,
        TrialResult(
            trial_id="trial:a:1",
            status=TrialStatus.FAILED,
            completed_at=T0 + timedelta(minutes=1),
            reasons=("no executable fill",),
        ),
    )

    assert registry.results[0].status is TrialStatus.FAILED
    assert registry.results[0].reasons == ("no executable fill",)
    with pytest.raises(ResearchProtocolError, match="immutable"):
        register_trial(registry, _trial())
    with pytest.raises(ResearchProtocolError, match="was not declared"):
        register_trial(
            registry,
            _trial("trial:a:undeclared").model_copy(update={"parameter_set_id": "mined:winner"}),
        )


def test_synthetic_or_cost_omitting_evidence_cannot_pass_acceptance() -> None:
    synthetic = _evidence(
        EvaluationMode.BACKTEST,
        data_class=EvidenceDataClass.SYNTHETIC_FIXTURE,
    )
    synthetic_decision = evaluate_acceptance(
        AcceptanceState.BACKTEST_EVIDENCE,
        (synthetic,),
        threshold_status=ThresholdStatus.CALIBRATED_FROM_RESEARCH,
    )
    assert synthetic_decision.granted_state is AcceptanceState.RESEARCH_ONLY
    assert any("synthetic" in reason for reason in synthetic_decision.reasons)

    missing_costs = _evidence(EvaluationMode.BACKTEST).model_copy(update={"costs_included": False})
    cost_decision = evaluate_acceptance(
        AcceptanceState.BACKTEST_EVIDENCE,
        (missing_costs,),
        threshold_status=ThresholdStatus.CALIBRATED_FROM_RESEARCH,
    )
    assert cost_decision.granted_state is AcceptanceState.RESEARCH_ONLY
    assert any("cost inclusion" in reason for reason in cost_decision.reasons)


def test_holdout_tuning_and_fragile_parameter_optima_block_acceptance() -> None:
    evidence = (
        _evidence(EvaluationMode.BACKTEST),
        _evidence(EvaluationMode.WALK_FORWARD).model_copy(
            update={"robustness_verdict": RobustnessVerdict.FRAGILE_NARROW_OPTIMUM}
        ),
        _evidence(EvaluationMode.HOLDOUT).model_copy(
            update={"holdout_state": HoldoutState.BURNED_FOR_TUNING}
        ),
    )
    decision = evaluate_acceptance(
        AcceptanceState.HOLDOUT_EVIDENCE,
        evidence,
        threshold_status=ThresholdStatus.CALIBRATED_FROM_RESEARCH,
    )

    assert decision.granted_state is AcceptanceState.RESEARCH_ONLY
    assert any("plateau" in reason for reason in decision.reasons)
    assert any("untouched final evaluation" in reason for reason in decision.reasons)


def test_acceptance_defaults_uncalibrated_and_live_candidate_never_enables_orders() -> None:
    decision = evaluate_acceptance(
        AcceptanceState.BACKTEST_EVIDENCE,
        (_evidence(EvaluationMode.BACKTEST),),
    )
    assert decision.threshold_status is ThresholdStatus.UNCALIBRATED
    assert decision.granted_state is AcceptanceState.RESEARCH_ONLY
    assert not decision.live_orders_enabled


def test_forward_and_paper_runs_are_live_arriving_not_historical_replays() -> None:
    with pytest.raises(ValidationError, match="live-arriving"):
        EvaluationRun(
            run_id="paper:invalid",
            mode=EvaluationMode.PAPER_TRADING,
            data_arrival=DataArrivalMode.HISTORICAL_REPLAY,
            started_at=T0,
        )

    paper = EvaluationRun(
        run_id="paper:valid",
        mode=EvaluationMode.PAPER_TRADING,
        data_arrival=DataArrivalMode.LIVE_ARRIVING,
        started_at=T0,
    )
    assert paper.mode is EvaluationMode.PAPER_TRADING
