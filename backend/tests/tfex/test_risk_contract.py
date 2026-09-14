"""Deterministic unit contracts for dormant TFEX risk architecture."""

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
from app.tfex.risk.engine import KillSwitchEvaluator, RiskEngine
from app.tfex.risk.models import (
    CostAssumptions,
    DecisionInput,
    DeterministicExitRule,
    ExistingPositionAction,
    ExitPlanProposal,
    ExitRuleType,
    KillSwitchTrigger,
    PositionRiskSnapshot,
    RiskContext,
    RiskDecisionStatus,
    RiskRejectionCode,
    StrategyRiskRule,
    TradeProposal,
    TradeSide,
)

BANGKOK = ZoneInfo("Asia/Bangkok")
EVENT_TIME = datetime(2026, 9, 14, 9, 50, tzinfo=BANGKOK)
CONFIRMED_AT = datetime(2026, 9, 14, 9, 51, tzinfo=BANGKOK)


def _research_risk(**updates: object) -> RiskConfig:
    values: dict[str, object] = {
        "calibration_status": RiskCalibrationStatus.RESEARCH_ONLY,
        "max_risk_per_trade_thb": Decimal("1000"),
        "max_daily_realized_loss_thb": Decimal("2000"),
        "max_daily_total_loss_thb": Decimal("3000"),
        "max_consecutive_losses": 3,
        "max_contracts": 5,
        "minimum_acceptable_reward_risk": Decimal("1.0"),
        "maximum_allowed_slippage_points": Decimal("0.5"),
        "max_repeated_execution_errors": 3,
        "daily_kill_switch_enabled": True,
        "pyramiding_enabled": False,
        "averaging_down_allowed": False,
        "martingale_allowed": False,
    }
    values.update(updates)
    return RiskConfig.model_validate(values)


def _config(**risk_updates: object) -> TfexConfig:
    base = default_config().model_dump()
    base["risk"] = _research_risk(**risk_updates).model_dump()
    return TfexConfig.model_validate(base)


def _costs(
    *,
    slippage: Decimal = Decimal("0.2"),
    scenario: CostScenario = CostScenario.BACKTEST,
    components: tuple[FeeComponent, ...] | None = None,
) -> CostAssumptions:
    explicit = components or (
        FeeComponent(
            kind=FeeKind.BROKER_COMMISSION,
            label="research commission",
            value_thb_per_contract_per_side=Decimal("10"),
            status=FeeProvenanceStatus.USER_ASSUMPTION,
            source="unit-test research assumption",
        ),
        FeeComponent(
            kind=FeeKind.EXCHANGE_FEE,
            label="research exchange-fee assumption",
            value_thb_per_contract_per_side=Decimal("5"),
            status=FeeProvenanceStatus.USER_ASSUMPTION,
            source="unit-test research assumption",
        ),
    )
    return CostAssumptions(
        assumptions_id="costs:test:v1",
        round_trip_fees=RoundTripCostEstimate(
            scenario=scenario,
            components=explicit,
            contracts=1,
        ),
        adverse_slippage_points=slippage,
        additional_cost_buffer_thb_per_contract=Decimal("10"),
        provenance="explicit unit-test assumptions; never production",
    )


def _proposal(
    *,
    side: TradeSide = TradeSide.LONG,
    entry: Decimal = Decimal("100"),
    stop: Decimal | None = Decimal("98"),
    target: Decimal | None = Decimal("104"),
    exit_rules: tuple[DeterministicExitRule, ...] = (),
    expectancy: Decimal | None = None,
) -> TradeProposal:
    exit_plan = (
        ExitPlanProposal(target_price=target, deterministic_rules=exit_rules)
        if target is not None or exit_rules
        else None
    )
    return TradeProposal(
        proposal_id="proposal:or-breakout:20260914T0951",
        strategy_id="opening-range-breakout",
        setup_id="orb-long-1",
        symbol="S50U26",
        side=side,
        event_time=EVENT_TIME,
        confirmed_at=CONFIRMED_AT,
        entry_price=entry,
        initial_stop_price=stop,
        exit_plan=exit_plan,
        estimated_expectancy_r=expectancy,
        rationale_inputs=(DecisionInput(name="opening_range_high", value="99.8"),),
        source_signal_ids=("signal:closed-0950",),
    )


def _rule(
    *,
    minimum_rr: Decimal | None = Decimal("1.2"),
    minimum_expectancy: Decimal | None = None,
) -> StrategyRiskRule:
    return StrategyRiskRule(
        strategy_id="opening-range-breakout",
        minimum_reward_risk=minimum_rr,
        minimum_expectancy_r=minimum_expectancy,
        research_rule_id="risk-rule:orb:v1",
    )


def _context(**updates: object) -> RiskContext:
    values: dict[str, object] = {
        "evaluated_at": CONFIRMED_AT,
        "trading_date": date(2026, 9, 14),
        "new_entry_session_allowed": True,
        "session_gate_reasons": (),
        "market_data_stale": False,
        "feed_connected": True,
        "broker_api_healthy": True,
        "reconciliation_matches": True,
    }
    values.update(updates)
    return RiskContext.model_validate(values)


def _codes(decision: object) -> set[RiskRejectionCode]:
    assert hasattr(decision, "rejections")
    return {rejection.code for rejection in decision.rejections}


def test_shipped_risk_policy_is_explicitly_uncalibrated_and_fail_closed() -> None:
    config = default_config()
    assert config.risk.calibration_status is RiskCalibrationStatus.UNCALIBRATED
    assert config.risk.missing_thresholds
    decision = RiskEngine(config).evaluate(
        _proposal(), strategy_rule=_rule(), costs=_costs(), context=_context()
    )
    assert decision.status is RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.UNCALIBRATED_RISK_LIMITS in _codes(decision)
    assert KillSwitchTrigger.UNCALIBRATED_RISK_POLICY in decision.kill_switch.active_triggers


def test_research_policy_requires_every_numerical_threshold() -> None:
    with pytest.raises(ValidationError, match="requires every threshold"):
        RiskConfig(calibration_status=RiskCalibrationStatus.RESEARCH_ONLY)
    with pytest.raises(ValidationError):
        RiskConfig(martingale_allowed=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RiskConfig(averaging_down_allowed=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("proposal", "expected"),
    [
        (_proposal(stop=None), RiskRejectionCode.STOP_REQUIRED),
        (_proposal(stop=Decimal("100")), RiskRejectionCode.STOP_DISTANCE_ZERO),
        (_proposal(stop=Decimal("101")), RiskRejectionCode.STOP_SIDE_INVALID),
        (
            _proposal(
                side=TradeSide.SHORT,
                stop=Decimal("99"),
                target=Decimal("96"),
            ),
            RiskRejectionCode.STOP_SIDE_INVALID,
        ),
        (_proposal(target=None), RiskRejectionCode.EXIT_PLAN_REQUIRED),
    ],
)
def test_entry_without_valid_stop_or_exit_plan_is_rejected(
    proposal: TradeProposal, expected: RiskRejectionCode
) -> None:
    decision = RiskEngine(_config()).evaluate(
        proposal, strategy_rule=_rule(), costs=_costs(), context=_context()
    )
    assert decision.status is RiskDecisionStatus.REJECTED
    assert expected in _codes(decision)


def test_exact_risk_math_and_size_include_multiplier_fees_slippage_and_buffer() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(), strategy_rule=_rule(), costs=_costs(), context=_context()
    )
    assert decision.status is RiskDecisionStatus.APPROVED
    calculation = decision.calculation
    assert calculation is not None
    assert calculation.stop_distance_points == Decimal("2")
    assert calculation.contract_multiplier_thb_per_point == Decimal("200")
    assert calculation.gross_price_risk_per_contract_thb == Decimal("400")
    assert calculation.round_trip_fees_per_contract_thb == Decimal("30")
    assert calculation.slippage_allowance_per_contract_thb == Decimal("40")
    assert calculation.additional_cost_buffer_per_contract_thb == Decimal("10")
    assert calculation.estimated_risk_per_contract_thb == Decimal("480")
    assert calculation.allowed_risk_thb == Decimal("1000")
    assert calculation.contracts == 2
    assert calculation.total_position_risk_thb == Decimal("960")
    assert calculation.planned_reward_points == Decimal("4")
    assert calculation.gross_planned_reward_per_contract_thb == Decimal("800")
    assert calculation.estimated_net_reward_per_contract_thb == Decimal("720")
    assert calculation.estimated_net_reward_thb == Decimal("1440")
    assert calculation.initial_reward_risk == Decimal("1.5")


def test_one_contract_is_rejected_when_stop_and_cost_risk_exceed_budget() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(stop=Decimal("95"), target=Decimal("110")),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(),
    )
    assert decision.status is RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.RISK_BUDGET_EXCEEDED in _codes(decision)
    assert decision.calculation is not None
    assert decision.calculation.estimated_risk_per_contract_thb == Decimal("1080")
    assert decision.calculation.contracts == 0


def test_strategy_specific_reward_risk_is_not_hard_coded_to_two_to_one() -> None:
    approved = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(minimum_rr=Decimal("1.4")),
        costs=_costs(),
        context=_context(),
    )
    rejected = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(minimum_rr=Decimal("1.6")),
        costs=_costs(),
        context=_context(),
    )
    assert approved.status is RiskDecisionStatus.APPROVED
    assert rejected.status is RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.REWARD_RISK_INSUFFICIENT in _codes(rejected)


def test_deterministic_non_target_exit_uses_strategy_expectancy_evidence() -> None:
    rule = DeterministicExitRule(
        rule_id="time-stop:1550",
        rule_type=ExitRuleType.TIME_STOP,
        inputs=(DecisionInput(name="exit_time", value="15:50:00+07:00"),),
    )
    rejected = RiskEngine(_config()).evaluate(
        _proposal(target=None, exit_rules=(rule,), expectancy=Decimal("0.4")),
        strategy_rule=_rule(minimum_rr=None, minimum_expectancy=Decimal("0.5")),
        costs=_costs(),
        context=_context(),
    )
    approved = RiskEngine(_config()).evaluate(
        _proposal(target=None, exit_rules=(rule,), expectancy=Decimal("0.6")),
        strategy_rule=_rule(minimum_rr=None, minimum_expectancy=Decimal("0.5")),
        costs=_costs(),
        context=_context(),
    )
    assert RiskRejectionCode.EXPECTANCY_INSUFFICIENT in _codes(rejected)
    assert approved.status is RiskDecisionStatus.APPROVED
    assert approved.calculation is not None
    assert approved.calculation.initial_reward_risk is None
    assert approved.calculation.estimated_expectancy_r == Decimal("0.6")


def test_slippage_limit_and_unusable_production_costs_are_distinct_rejections() -> None:
    slippage = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(slippage=Decimal("0.6")),
        context=_context(),
    )
    cap = FeeComponent(
        kind=FeeKind.EXCHANGE_FEE,
        label="published maximum",
        value_thb_per_contract_per_side=Decimal("7"),
        status=FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP,
        source="official contract specification; maximum only",
    )
    cap_as_actual = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(scenario=CostScenario.PRODUCTION, components=(cap,)),
        context=_context(),
    )
    assert RiskRejectionCode.SLIPPAGE_LIMIT_EXCEEDED in _codes(slippage)
    assert RiskRejectionCode.COST_MODEL_UNUSABLE in _codes(cap_as_actual)


def test_daily_loss_kill_switch_blocks_new_entry() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(daily_realized_pnl_thb=Decimal("-2000")),
    )
    assert RiskRejectionCode.KILL_SWITCH_ACTIVE in _codes(decision)
    assert KillSwitchTrigger.DAILY_REALIZED_LOSS in decision.kill_switch.active_triggers
    assert decision.kill_switch.new_entries_allowed is False


def test_daily_total_loss_includes_unrealized_loss_and_is_distinct() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(
            daily_realized_pnl_thb=Decimal("-1000"),
            daily_unrealized_pnl_thb=Decimal("-2000"),
        ),
    )
    assert KillSwitchTrigger.DAILY_TOTAL_LOSS in decision.kill_switch.active_triggers
    assert KillSwitchTrigger.DAILY_REALIZED_LOSS not in decision.kill_switch.active_triggers
    assert RiskRejectionCode.KILL_SWITCH_ACTIVE in _codes(decision)


def test_missing_or_denied_session_evidence_fails_closed() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(
            new_entry_session_allowed=False,
            session_gate_reasons=("past end-of-day entry cutoff",),
        ),
    )
    assert RiskRejectionCode.SESSION_ENTRY_NOT_ALLOWED in _codes(decision)


def test_risk_evaluation_cannot_precede_signal_confirmation() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(evaluated_at=EVENT_TIME),
    )
    assert RiskRejectionCode.SIGNAL_NOT_CONFIRMED in _codes(decision)


def test_missing_operational_health_evidence_activates_kill_switch() -> None:
    context = RiskContext(
        evaluated_at=CONFIRMED_AT,
        trading_date=date(2026, 9, 14),
        new_entry_session_allowed=True,
        session_gate_reasons=(),
    )
    decision = RiskEngine(_config()).evaluate(
        _proposal(), strategy_rule=_rule(), costs=_costs(), context=context
    )
    assert RiskRejectionCode.KILL_SWITCH_ACTIVE in _codes(decision)
    assert set(decision.kill_switch.active_triggers) >= {
        KillSwitchTrigger.STALE_MARKET_DATA,
        KillSwitchTrigger.FEED_DISCONNECT,
        KillSwitchTrigger.BROKER_API_ERROR,
        KillSwitchTrigger.RECONCILIATION_MISMATCH,
    }


def test_daily_remaining_loss_capacity_reduces_position_size_before_kill_threshold() -> None:
    decision = RiskEngine(_config()).evaluate(
        _proposal(),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(daily_realized_pnl_thb=Decimal("-1200")),
    )
    assert decision.status is RiskDecisionStatus.APPROVED
    assert decision.calculation is not None
    assert decision.calculation.allowed_risk_thb == Decimal("800")
    assert decision.calculation.contracts == 1


def test_operational_kill_triggers_separate_new_entry_from_existing_protection() -> None:
    existing = PositionRiskSnapshot(
        symbol="S50U26",
        side=TradeSide.LONG,
        contracts=1,
        average_entry_price=Decimal("100"),
        current_stop_price=Decimal("98"),
        mark_price=Decimal("101"),
        current_total_risk_thb=Decimal("480"),
    )
    decision = KillSwitchEvaluator(_research_risk()).evaluate(
        _context(
            existing_position=existing,
            repeated_execution_errors=3,
            market_data_stale=True,
            feed_connected=False,
            broker_api_healthy=False,
            reconciliation_matches=False,
            emergency_manual_disable=True,
        )
    )
    assert set(decision.active_triggers) >= {
        KillSwitchTrigger.REPEATED_EXECUTION_ERRORS,
        KillSwitchTrigger.STALE_MARKET_DATA,
        KillSwitchTrigger.FEED_DISCONNECT,
        KillSwitchTrigger.BROKER_API_ERROR,
        KillSwitchTrigger.RECONCILIATION_MISMATCH,
        KillSwitchTrigger.EMERGENCY_MANUAL_DISABLE,
    }
    assert (
        decision.existing_position_action
        is ExistingPositionAction.KEEP_PROTECTION_AND_FLATTEN_WHEN_EXECUTABLE
    )


def test_pyramiding_is_disabled_by_default_and_averaging_down_remains_prohibited() -> None:
    profitable = PositionRiskSnapshot(
        symbol="S50U26",
        side=TradeSide.LONG,
        contracts=1,
        average_entry_price=Decimal("100"),
        current_stop_price=Decimal("98"),
        mark_price=Decimal("101"),
        current_total_risk_thb=Decimal("300"),
    )
    disabled = RiskEngine(_config()).evaluate(
        _proposal(entry=Decimal("101"), stop=Decimal("99"), target=Decimal("105")),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(existing_position=profitable),
    )
    losing = profitable.model_copy(
        update={"mark_price": Decimal("99"), "current_total_risk_thb": Decimal("300")}
    )
    averaging = RiskEngine(_config(pyramiding_enabled=True)).evaluate(
        _proposal(entry=Decimal("99"), stop=Decimal("98"), target=Decimal("103")),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(existing_position=losing),
    )
    assert RiskRejectionCode.PYRAMIDING_DISABLED in _codes(disabled)
    assert RiskRejectionCode.AVERAGING_DOWN_PROHIBITED in _codes(averaging)


def test_enabled_pyramid_recalculates_total_risk_and_full_protective_quantity() -> None:
    existing = PositionRiskSnapshot(
        symbol="S50U26",
        side=TradeSide.LONG,
        contracts=1,
        average_entry_price=Decimal("100"),
        current_stop_price=Decimal("98"),
        mark_price=Decimal("101"),
        current_total_risk_thb=Decimal("300"),
    )
    decision = RiskEngine(_config(pyramiding_enabled=True)).evaluate(
        _proposal(entry=Decimal("101"), stop=Decimal("100"), target=Decimal("105")),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(existing_position=existing),
    )
    assert decision.status is RiskDecisionStatus.APPROVED
    assert decision.calculation is not None
    assert decision.calculation.contracts == 2
    assert decision.calculation.existing_position_risk_thb == Decimal("300")
    assert decision.calculation.total_position_risk_thb == Decimal("860")
    assert decision.approved_plan is not None
    assert decision.approved_plan.resulting_total_contracts == 3
    assert decision.approved_plan.protective_exit.quantity == 3


def test_max_contracts_and_stop_widening_apply_to_pyramids() -> None:
    existing = PositionRiskSnapshot(
        symbol="S50U26",
        side=TradeSide.LONG,
        contracts=5,
        average_entry_price=Decimal("100"),
        current_stop_price=Decimal("99"),
        mark_price=Decimal("101"),
        current_total_risk_thb=Decimal("300"),
    )
    maxed = RiskEngine(_config(pyramiding_enabled=True)).evaluate(
        _proposal(entry=Decimal("101"), stop=Decimal("100"), target=Decimal("105")),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(existing_position=existing),
    )
    wider = RiskEngine(_config(pyramiding_enabled=True, max_contracts=6)).evaluate(
        _proposal(entry=Decimal("101"), stop=Decimal("98"), target=Decimal("105")),
        strategy_rule=_rule(),
        costs=_costs(),
        context=_context(existing_position=existing),
    )
    assert RiskRejectionCode.MAX_CONTRACTS_REACHED in _codes(maxed)
    assert RiskRejectionCode.STOP_WIDENING_PROHIBITED in _codes(wider)
