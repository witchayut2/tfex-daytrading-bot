"""Research execution timing is causal, costed, and behind the risk boundary."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError

import app.tfex.research.models as research_models
import app.tfex.research.protocol as research_protocol
from app.tfex.costs.models import (
    CostScenario,
    FeeComponent,
    FeeKind,
    FeeProvenanceStatus,
    RoundTripCostEstimate,
)
from app.tfex.errors import RiskBypassError
from app.tfex.research.models import (
    ExecutionCandidate,
    ExecutionEvidenceKind,
    OrderKind,
    ResearchCostModel,
    ResearchExecutionPolicy,
    ResearchOrderIntent,
    SameBarPolicy,
)
from app.tfex.research.protocol import evaluate_execution_eligibility
from app.tfex.risk.models import (
    ApprovedTradePlan,
    DecisionInput,
    ExitPlanProposal,
    ProtectiveExitPlan,
    RiskCalculation,
    TradeProposal,
    TradeSide,
)

T0 = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


def _approved_plan() -> ApprovedTradePlan:
    proposal = TradeProposal(
        proposal_id="proposal:a:1",
        strategy_id="A",
        setup_id="setup:a:1",
        symbol="S50U26",
        side=TradeSide.LONG,
        event_time=T0 - timedelta(minutes=1),
        confirmed_at=T0,
        entry_price=Decimal("100"),
        initial_stop_price=Decimal("98"),
        exit_plan=ExitPlanProposal(target_price=Decimal("104")),
        rationale_inputs=(DecisionInput(name="closed_bar", value="bar:1"),),
        source_signal_ids=("signal:a:1",),
    )
    calculation = RiskCalculation(
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        stop_distance_points=Decimal("2"),
        contract_multiplier_thb_per_point=Decimal("200"),
        gross_price_risk_per_contract_thb=Decimal("400"),
        round_trip_fees_per_contract_thb=Decimal("34"),
        slippage_allowance_per_contract_thb=Decimal("80"),
        additional_cost_buffer_per_contract_thb=Decimal("0"),
        estimated_risk_per_contract_thb=Decimal("514"),
        allowed_risk_thb=Decimal("1100"),
        contracts=2,
        total_position_risk_thb=Decimal("1028"),
        planned_reward_points=Decimal("4"),
        gross_planned_reward_per_contract_thb=Decimal("800"),
        estimated_net_reward_per_contract_thb=Decimal("686"),
        estimated_net_reward_thb=Decimal("1372"),
        initial_reward_risk=Decimal("1.3346"),
    )
    return ApprovedTradePlan(
        plan_id="plan:a:1",
        risk_decision_id="risk:a:1",
        proposal=proposal,
        calculation=calculation,
        protective_exit=ProtectiveExitPlan(
            symbol="S50U26",
            side=TradeSide.LONG,
            quantity=2,
            initial_stop_price=Decimal("98"),
            target_price=Decimal("104"),
        ),
        resulting_total_contracts=2,
        cost_assumptions_id="costs:research:v1",
        strategy_rule_id="strategy-risk:a:v1",
    )


def _cost_model() -> ResearchCostModel:
    return ResearchCostModel(
        cost_model_id="costs:research:v1",
        round_trip_fees=RoundTripCostEstimate(
            scenario=CostScenario.BACKTEST,
            components=(
                FeeComponent(
                    kind=FeeKind.EXCHANGE_FEE,
                    label="exchange research assumption",
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
        ),
        slippage_points_per_side=Decimal("0.2"),
        contract_multiplier_thb_per_point=Decimal("200"),
        tick_size_points=Decimal("0.1"),
        provenance="test-only research assumptions",
    )


def _policy() -> ResearchExecutionPolicy:
    return ResearchExecutionPolicy(
        policy_id="execution:next-event:v1",
        market_fill_rule_id="market:next-quote-adverse-slippage",
        limit_fill_rule_id="limit:conservative-touch",
        stop_fill_rule_id="stop:conservative-cross",
        partial_fill_rule_id="partial:available-size-only",
        cost_model_id="costs:research:v1",
    )


def _intent() -> ResearchOrderIntent:
    return ResearchOrderIntent(
        intent_id="intent:a:1",
        approved_plan=_approved_plan(),
        kind=OrderKind.MARKET,
        eligible_after=T0,
        signal_bar_id="bar:signal",
    )


def _candidate(*, at: datetime, bar_id: str, executable: bool = True) -> ExecutionCandidate:
    return ExecutionCandidate(
        event_id=f"event:{at.isoformat()}:{bar_id}",
        symbol="S50U26",
        event_time=at,
        bar_id=bar_id,
        sequence=1,
        executable=executable,
        evidence_kind=ExecutionEvidenceKind.BAR_OHLC,
    )


def test_execution_is_no_earlier_than_the_next_valid_event() -> None:
    intent = _intent()
    same_instant = evaluate_execution_eligibility(
        intent,
        _candidate(at=T0, bar_id="bar:next"),
        policy=_policy(),
        cost_model=_cost_model(),
    )
    next_event = evaluate_execution_eligibility(
        intent,
        _candidate(at=T0 + timedelta(minutes=1), bar_id="bar:next"),
        policy=_policy(),
        cost_model=_cost_model(),
    )

    assert not same_instant.eligible
    assert "later valid executable event" in same_instant.reasons[0]
    assert next_event.eligible
    assert not next_event.reasons


@pytest.mark.anti_repaint
def test_same_bar_ohlc_fill_is_rejected_as_clairvoyant() -> None:
    decision = evaluate_execution_eligibility(
        _intent(),
        _candidate(at=T0 + timedelta(seconds=1), bar_id="bar:signal"),
        policy=_policy(),
        cost_model=_cost_model(),
    )

    assert not decision.eligible
    assert "same-bar execution is prohibited" in decision.reasons


@pytest.mark.anti_repaint
def test_same_bar_requires_explicit_post_confirmation_tick_ordering() -> None:
    intent = _intent().model_copy(update={"confirmation_sequence": 10})
    policy = _policy().model_copy(
        update={"same_bar_policy": SameBarPolicy.PROVEN_TICK_SEQUENCE_ONLY}
    )
    unproven = ExecutionCandidate(
        event_id="event:unproven",
        symbol="S50U26",
        event_time=T0 + timedelta(seconds=1),
        bar_id="bar:signal",
        sequence=10,
        executable=True,
        evidence_kind=ExecutionEvidenceKind.TRADE_TICK,
    )
    proven = unproven.model_copy(update={"event_id": "event:proven", "sequence": 11})

    assert not evaluate_execution_eligibility(
        intent,
        unproven,
        policy=policy,
        cost_model=_cost_model(),
    ).eligible
    assert evaluate_execution_eligibility(
        intent,
        proven,
        policy=policy,
        cost_model=_cost_model(),
    ).eligible


def test_market_limit_and_stop_intents_have_distinct_required_fields() -> None:
    plan = _approved_plan()
    with pytest.raises(ValidationError, match="limit_price"):
        ResearchOrderIntent(
            intent_id="limit:invalid",
            approved_plan=plan,
            kind=OrderKind.LIMIT,
            eligible_after=T0,
            signal_bar_id="bar:signal",
        )
    with pytest.raises(ValidationError, match="stop_price"):
        ResearchOrderIntent(
            intent_id="stop:invalid",
            approved_plan=plan,
            kind=OrderKind.STOP,
            eligible_after=T0,
            signal_bar_id="bar:signal",
        )


def test_research_execution_cannot_bypass_risk_engine_approved_plan_type() -> None:
    forged = ResearchOrderIntent.model_construct(
        intent_id="intent:forged",
        approved_plan=cast(ApprovedTradePlan, object()),
        kind=OrderKind.MARKET,
        eligible_after=T0,
        signal_bar_id="bar:signal",
        limit_price=None,
        stop_price=None,
    )
    with pytest.raises(RiskBypassError, match="ApprovedTradePlan only"):
        evaluate_execution_eligibility(
            forged,
            _candidate(at=T0 + timedelta(minutes=1), bar_id="bar:next"),
            policy=_policy(),
            cost_model=_cost_model(),
        )


def test_research_scaffold_has_no_broker_or_order_submission_surface() -> None:
    source = "\n".join(
        inspect.getsource(module) for module in (research_models, research_protocol)
    ).lower()
    assert "settrade" not in source
    assert "submit_order" not in source
    assert "place_order" not in source
    assert not hasattr(research_protocol, "submit_order")
