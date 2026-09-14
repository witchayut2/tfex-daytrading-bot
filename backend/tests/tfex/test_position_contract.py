"""Order/position state contracts; pure reducers with no broker or market-data calls."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.tfex.config import RiskCalibrationStatus, RiskConfig, TfexConfig, default_config
from app.tfex.costs.models import (
    CostScenario,
    FeeComponent,
    FeeKind,
    FeeProvenanceStatus,
    RoundTripCostEstimate,
)
from app.tfex.errors import InvalidOrderTransitionError, PositionProtectionError, RiskBypassError
from app.tfex.risk.audit import TradeAuditRecord
from app.tfex.risk.boundary import ExecutionAdmission
from app.tfex.risk.engine import RiskEngine
from app.tfex.risk.models import (
    ApprovedTradePlan,
    AuditEvent,
    AuditEventType,
    AuditField,
    CostAssumptions,
    DecisionInput,
    ExistingPositionAction,
    ExitPlanProposal,
    KillSwitchDecision,
    RiskContext,
    RiskDecision,
    RiskDecisionStatus,
    StrategyRiskRule,
    TradeProposal,
    TradeSide,
)
from app.tfex.risk.position import (
    ExitReason,
    FillRecord,
    FillRole,
    LifecycleState,
    ManagedPosition,
    PositionManager,
    ProtectionStatus,
    RecoveryReason,
    StopChangeDecision,
    StopUpdateKind,
    StopUpdateRequest,
    validate_lifecycle_transition,
)

BANGKOK = ZoneInfo("Asia/Bangkok")
T0 = datetime(2026, 9, 14, 10, 0, tzinfo=BANGKOK)


def _cost_assumptions() -> CostAssumptions:
    return CostAssumptions(
        assumptions_id="costs:test:v1",
        round_trip_fees=RoundTripCostEstimate(
            scenario=CostScenario.BACKTEST,
            components=(
                FeeComponent(
                    kind=FeeKind.BROKER_COMMISSION,
                    label="research cost",
                    value_thb_per_contract_per_side=Decimal("10"),
                    status=FeeProvenanceStatus.USER_ASSUMPTION,
                    source="test only",
                ),
            ),
        ),
        adverse_slippage_points=Decimal("0.2"),
        additional_cost_buffer_thb_per_contract=Decimal("20"),
        provenance="test only",
    )


def _approved_plan() -> ApprovedTradePlan:
    base = default_config().model_dump()
    base["risk"] = RiskConfig(
        calibration_status=RiskCalibrationStatus.RESEARCH_ONLY,
        max_risk_per_trade_thb=Decimal("1000"),
        max_daily_realized_loss_thb=Decimal("2000"),
        max_daily_total_loss_thb=Decimal("3000"),
        max_consecutive_losses=3,
        max_contracts=5,
        minimum_acceptable_reward_risk=Decimal("1"),
        maximum_allowed_slippage_points=Decimal("0.5"),
        max_repeated_execution_errors=3,
    ).model_dump()
    config = TfexConfig.model_validate(base)
    proposal = TradeProposal(
        proposal_id="proposal:test:1",
        strategy_id="test-strategy",
        setup_id="setup:1",
        symbol="S50U26",
        side=TradeSide.LONG,
        event_time=T0,
        confirmed_at=T0,
        entry_price=Decimal("100"),
        initial_stop_price=Decimal("98"),
        exit_plan=ExitPlanProposal(target_price=Decimal("104")),
        rationale_inputs=(DecisionInput(name="closed_bar", value="2026-09-14T10:00+07:00"),),
        source_signal_ids=("signal:test:closed-bar",),
    )
    decision = RiskEngine(config).evaluate(
        proposal,
        strategy_rule=StrategyRiskRule(
            strategy_id="test-strategy",
            minimum_reward_risk=Decimal("1.2"),
            research_rule_id="rule:test:v1",
        ),
        costs=_cost_assumptions(),
        context=RiskContext(
            evaluated_at=T0,
            trading_date=date(2026, 9, 14),
            new_entry_session_allowed=True,
            session_gate_reasons=(),
            market_data_stale=False,
            feed_connected=True,
            broker_api_healthy=True,
            reconciliation_matches=True,
        ),
    )
    assert decision.approved_plan is not None
    assert decision.approved_plan.calculation.contracts == 2
    return decision.approved_plan


def _fill(
    fill_id: str,
    *,
    role: FillRole,
    quantity: int,
    price: str,
    reason: ExitReason | None = None,
) -> FillRecord:
    return FillRecord(
        fill_id=fill_id,
        role=role,
        quantity=quantity,
        price=Decimal(price),
        event_time=T0,
        recorded_at=T0,
        broker_order_id="paper-order-1",
        broker_fill_id=fill_id,
        exit_reason=reason,
    )


def _fully_protected_position() -> ManagedPosition:
    pending = PositionManager.from_approved_plan(_approved_plan())
    filled = PositionManager.apply_entry_fill(
        pending,
        _fill("entry-full", role=FillRole.ENTRY, quantity=2, price="100"),
    )
    return PositionManager.acknowledge_protection(filled)


def test_locked_lifecycle_graph_rejects_risk_and_protection_bypasses() -> None:
    validate_lifecycle_transition(LifecycleState.SIGNAL_CANDIDATE, LifecycleState.RISK_EVALUATION)
    validate_lifecycle_transition(LifecycleState.RISK_EVALUATION, LifecycleState.APPROVED)
    validate_lifecycle_transition(LifecycleState.APPROVED, LifecycleState.ENTRY_PENDING)
    with pytest.raises(InvalidOrderTransitionError, match="invalid lifecycle transition"):
        validate_lifecycle_transition(LifecycleState.SIGNAL_CANDIDATE, LifecycleState.FILLED)
    with pytest.raises(InvalidOrderTransitionError, match="invalid lifecycle transition"):
        validate_lifecycle_transition(LifecycleState.FILLED, LifecycleState.MANAGED)


def test_execution_boundary_revalidates_a_forged_pydantic_copy() -> None:
    plan = _approved_plan()
    forged_exit = plan.protective_exit.model_copy(update={"initial_stop_price": Decimal("97")})
    forged_plan = plan.model_copy(update={"protective_exit": forged_exit})
    with pytest.raises(RiskBypassError, match="failed invariant validation"):
        ExecutionAdmission.require_approved_plan(forged_plan)


def test_partial_entry_fill_immediately_reserves_protection_for_all_exposure() -> None:
    pending = PositionManager.from_approved_plan(_approved_plan())
    partial = PositionManager.apply_entry_fill(
        pending,
        _fill("entry-1", role=FillRole.ENTRY, quantity=1, price="100"),
    )
    assert partial.state is LifecycleState.PARTIALLY_FILLED
    assert partial.open_quantity == 1
    assert partial.remaining_entry_quantity == 1
    assert partial.entry_order_open is True
    assert partial.protective_quantity == partial.open_quantity
    assert partial.current_stop_price == Decimal("98")
    assert partial.protection_status is ProtectionStatus.PENDING_ACK

    protected = PositionManager.acknowledge_protection(partial)
    final_fill = PositionManager.apply_entry_fill(
        protected,
        _fill("entry-2", role=FillRole.ENTRY, quantity=1, price="100.2"),
    )
    assert final_fill.state is LifecycleState.FILLED
    assert final_fill.open_quantity == 2
    assert final_fill.entry_order_open is False
    assert final_fill.protective_quantity == 2
    assert final_fill.protection_status is ProtectionStatus.PENDING_ACK
    assert final_fill.average_entry_price == Decimal("100.1")


def test_partial_entry_remainder_can_be_cancelled_without_losing_approved_history() -> None:
    pending = PositionManager.from_approved_plan(_approved_plan())
    partial = PositionManager.apply_entry_fill(
        pending,
        _fill("entry-partial-cancel", role=FillRole.ENTRY, quantity=1, price="100"),
    )
    protected = PositionManager.acknowledge_protection(partial)
    cancelled = PositionManager.cancel_remaining_entry(protected)
    assert cancelled.entry_order_open is False
    assert cancelled.remaining_entry_quantity == 1
    assert cancelled.planned_entry_quantity == cancelled.plan.calculation.contracts
    with pytest.raises(InvalidOrderTransitionError, match="entry fill is invalid"):
        PositionManager.apply_entry_fill(
            cancelled,
            _fill("late-entry", role=FillRole.ENTRY, quantity=1, price="100.1"),
        )


def test_model_refuses_filled_exposure_without_matching_protective_quantity() -> None:
    protected = _fully_protected_position()
    values = protected.model_dump()
    values["protective_quantity"] = 1
    with pytest.raises(ValidationError, match="protective quantity must equal"):
        ManagedPosition.model_validate(values)


def test_partial_take_profit_atomically_reduces_stop_quantity_then_closes() -> None:
    protected = _fully_protected_position()
    exit_pending = PositionManager.request_exit(protected, ExitReason.PARTIAL_TAKE_PROFIT)
    partial = PositionManager.apply_exit_fill(
        exit_pending,
        _fill(
            "exit-1",
            role=FillRole.EXIT,
            quantity=1,
            price="103",
            reason=ExitReason.PARTIAL_TAKE_PROFIT,
        ),
    )
    assert partial.state is LifecycleState.MANAGED
    assert partial.open_quantity == 1
    assert partial.protective_quantity == 1
    assert partial.protection_status is ProtectionStatus.REPLACE_PENDING

    protected_remainder = PositionManager.acknowledge_protection(partial)
    final_exit = PositionManager.request_exit(protected_remainder, ExitReason.TAKE_PROFIT)
    closed = PositionManager.apply_exit_fill(
        final_exit,
        _fill(
            "exit-2",
            role=FillRole.EXIT,
            quantity=1,
            price="104",
            reason=ExitReason.TAKE_PROFIT,
        ),
    )
    assert closed.state is LifecycleState.CLOSED
    assert closed.open_quantity == 0
    assert closed.protective_quantity == 0
    assert closed.protection_status is ProtectionStatus.EXECUTED


@pytest.mark.parametrize(
    ("kind", "new_stop"),
    [
        (StopUpdateKind.TIGHTEN, "99"),
        (StopUpdateKind.BREAK_EVEN, "100"),
        (StopUpdateKind.LOCK_PROFIT, "100.5"),
        (StopUpdateKind.STRUCTURE_TRAIL, "101"),
        (StopUpdateKind.ATR_TRAIL, "101.5"),
    ],
)
def test_only_deterministic_non_widening_stop_changes_are_accepted(
    kind: StopUpdateKind, new_stop: str
) -> None:
    protected = _fully_protected_position()
    inputs = (
        DecisionInput(name="closed_bar_high", value="102"),
        DecisionInput(name="trail_value", value=new_stop),
    )
    request = StopUpdateRequest(
        update_id=f"stop:{kind}",
        kind=kind,
        new_stop_price=Decimal(new_stop),
        rule_id=f"rule:{kind}",
        decided_at=T0,
        inputs=inputs,
    )
    decision = PositionManager.evaluate_stop_change(protected, request)
    assert decision.accepted is True
    updated = PositionManager.apply_stop_change(protected, decision)
    assert updated.current_stop_price == Decimal(new_stop)
    assert updated.protective_quantity == updated.open_quantity
    assert updated.protection_status is ProtectionStatus.REPLACE_PENDING


def test_stop_widening_is_rejected_by_default() -> None:
    protected = _fully_protected_position()
    widening = StopUpdateRequest(
        update_id="stop:widen",
        kind=StopUpdateKind.TIGHTEN,
        new_stop_price=Decimal("97.9"),
        rule_id="rule:invalid-widen",
        decided_at=T0,
    )
    decision = PositionManager.evaluate_stop_change(protected, widening)
    assert decision.accepted is False
    assert "widening" in decision.reason
    with pytest.raises(PositionProtectionError, match="widening"):
        PositionManager.apply_stop_change(protected, decision)


def test_forged_accepted_decision_still_cannot_widen_stop() -> None:
    protected = _fully_protected_position()
    forged = StopChangeDecision(
        accepted=True,
        previous_stop_price=Decimal("98"),
        requested_stop_price=Decimal("97"),
        kind=StopUpdateKind.TIGHTEN,
        reason="incorrect external acceptance",
        decided_at=T0,
        rule_id="forged:widen",
    )
    with pytest.raises(PositionProtectionError, match="widening"):
        PositionManager.apply_stop_change(protected, forged)


def test_duplicate_partial_fill_is_rejected_before_quantity_changes() -> None:
    pending = PositionManager.from_approved_plan(_approved_plan())
    fill = _fill("entry-duplicate", role=FillRole.ENTRY, quantity=1, price="100")
    partial = PositionManager.apply_entry_fill(pending, fill)
    with pytest.raises(InvalidOrderTransitionError, match="duplicate fill ID"):
        PositionManager.apply_entry_fill(partial, fill)


def test_break_even_and_profit_labels_must_match_filled_average() -> None:
    protected = _fully_protected_position()
    mislabeled = StopUpdateRequest(
        update_id="stop:false-be",
        kind=StopUpdateKind.BREAK_EVEN,
        new_stop_price=Decimal("99"),
        rule_id="rule:false-be",
        decided_at=T0,
    )
    decision = PositionManager.evaluate_stop_change(protected, mislabeled)
    assert decision.accepted is False
    assert "average entry" in decision.reason


def test_protection_failure_keeps_full_risk_state_and_requires_emergency_exit() -> None:
    protected = _fully_protected_position()
    emergency = PositionManager.protection_failed(protected)
    assert emergency.state is LifecycleState.EMERGENCY_EXIT_PENDING
    assert emergency.pending_exit_reason is ExitReason.EMERGENCY_FLATTEN
    assert emergency.protective_quantity == emergency.open_quantity
    assert emergency.protection_status is ProtectionStatus.EMERGENCY_FLATTEN_REQUIRED


def test_normal_exit_failure_keeps_stop_and_moves_to_emergency_flatten() -> None:
    protected = _fully_protected_position()
    exit_pending = PositionManager.request_exit(protected, ExitReason.TIME_STOP)
    emergency = PositionManager.exit_failed(exit_pending)
    assert emergency.state is LifecycleState.EMERGENCY_EXIT_PENDING
    assert emergency.current_stop_price == protected.current_stop_price
    assert emergency.protective_quantity == protected.open_quantity
    assert emergency.pending_exit_reason is ExitReason.EMERGENCY_FLATTEN


def test_eod_flatten_is_deterministic_and_cannot_trigger_early() -> None:
    protected = _fully_protected_position()
    assert protected.plan.proposal.exit_plan is not None
    assert protected.plan.proposal.exit_plan.overnight_allowed is False
    assert protected.plan.protective_exit.overnight_allowed is False
    assert protected.plan.protective_exit.eod_flatten_required is True
    with pytest.raises(InvalidOrderTransitionError, match="before session policy"):
        PositionManager.request_eod_flatten(protected, session_requires_flatten=False)
    exit_pending = PositionManager.request_eod_flatten(protected, session_requires_flatten=True)
    assert exit_pending.state is LifecycleState.EXIT_PENDING
    assert exit_pending.pending_exit_reason is ExitReason.EOD_FLATTEN


def test_unexpected_open_exposure_never_becomes_a_normal_managed_position() -> None:
    recovered = PositionManager.recover_unexpected_exposure(
        recovery_id="recovery:restart:1",
        reason=RecoveryReason.UNEXPECTED_BROKER_POSITION,
        symbol="S50U26",
        side=TradeSide.LONG,
        observed_quantity=2,
        observed_average_entry_price=Decimal("100"),
        emergency_stop_price=Decimal("98"),
        observed_at=T0,
    )
    assert recovered.state is LifecycleState.EMERGENCY_EXIT_PENDING
    assert recovered.protective_quantity == recovered.observed_quantity
    assert recovered.flatten_when_executable is True


def test_audit_event_preserves_nonrepaint_times_and_named_decision_inputs() -> None:
    event = AuditEvent(
        audit_id="audit:1",
        trade_id="position:1",
        sequence=1,
        event_type=AuditEventType.RISK_APPROVED,
        event_time=T0,
        recorded_at=T0,
        fields=(
            AuditField(name="proposal_id", value="proposal:test:1"),
            AuditField(name="risk_decision_id", value="risk:test:1"),
            AuditField(name="entry_price", value="100"),
            AuditField(name="stop_price", value="98"),
            AuditField(name="contracts", value="2"),
        ),
    )
    assert event.event_time.tzinfo is not None
    assert event.recorded_at.tzinfo is not None
    assert {field.name for field in event.fields} == {
        "proposal_id",
        "risk_decision_id",
        "entry_price",
        "stop_price",
        "contracts",
    }
    invalid = event.model_dump()
    invalid["fields"] = (
        AuditField(name="proposal_id", value="one"),
        AuditField(name="proposal_id", value="two"),
    )
    with pytest.raises(ValidationError, match="field names must be unique"):
        AuditEvent.model_validate(invalid)


def test_trade_audit_record_reconstructs_proposal_risk_costs_and_position() -> None:
    plan = _approved_plan()
    kill = KillSwitchDecision(
        evaluated_at=T0,
        existing_position_action=ExistingPositionAction.NO_POSITION,
    )
    decision = RiskDecision(
        decision_id=plan.risk_decision_id,
        proposal_id=plan.proposal.proposal_id,
        evaluated_at=T0,
        status=RiskDecisionStatus.APPROVED,
        kill_switch=kill,
        context=RiskContext(
            evaluated_at=T0,
            trading_date=date(2026, 9, 14),
            new_entry_session_allowed=True,
            session_gate_reasons=(),
            market_data_stale=False,
            feed_connected=True,
            broker_api_healthy=True,
            reconciliation_matches=True,
        ),
        calculation=plan.calculation,
        approved_plan=plan,
    )
    position = PositionManager.from_approved_plan(plan)
    common_fields = (
        AuditField(name="strategy_id", value=plan.proposal.strategy_id),
        AuditField(name="setup_id", value=plan.proposal.setup_id),
        AuditField(name="proposal_id", value=plan.proposal.proposal_id),
    )
    record = TradeAuditRecord(
        trade_id=position.position_id,
        proposal=plan.proposal,
        risk_decision=decision,
        cost_assumptions=_cost_assumptions(),
        kill_switch_history=(kill,),
        lifecycle_events=(
            AuditEvent(
                audit_id="audit:proposal",
                trade_id=position.position_id,
                sequence=0,
                event_type=AuditEventType.PROPOSAL_CREATED,
                event_time=plan.proposal.event_time,
                recorded_at=plan.proposal.confirmed_at,
                fields=common_fields,
            ),
            AuditEvent(
                audit_id="audit:risk",
                trade_id=position.position_id,
                sequence=1,
                event_type=AuditEventType.RISK_APPROVED,
                event_time=T0,
                recorded_at=T0,
                fields=(
                    AuditField(name="entry_price", value=str(plan.calculation.entry_price)),
                    AuditField(name="stop_price", value=str(plan.calculation.stop_price)),
                    AuditField(
                        name="risk_thb", value=str(plan.calculation.total_position_risk_thb)
                    ),
                    AuditField(name="contracts", value=str(plan.calculation.contracts)),
                    AuditField(name="cost_assumptions_id", value=plan.cost_assumptions_id),
                ),
            ),
        ),
        position=position,
    )
    dumped = record.model_dump(mode="json")
    assert dumped["proposal"]["event_time"] == "2026-09-14T10:00:00+07:00"
    assert dumped["risk_decision"]["calculation"]["contracts"] == 2
    assert dumped["cost_assumptions"]["assumptions_id"] == "costs:test:v1"
