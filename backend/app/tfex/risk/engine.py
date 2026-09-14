"""Dormant, deterministic pre-trade risk engine.

This module has no broker dependency and cannot submit an order. It turns a strategy's
quantity-free :class:`TradeProposal` into either explicit rejections or the sole object a
future execution boundary may accept: :class:`ApprovedTradePlan`.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from app.tfex.config import RiskConfig, TfexConfig
from app.tfex.errors import FeeSemanticsError
from app.tfex.risk.models import (
    ApprovedTradePlan,
    CostAssumptions,
    ExistingPositionAction,
    KillSwitchDecision,
    KillSwitchTrigger,
    ProtectiveExitPlan,
    RiskCalculation,
    RiskContext,
    RiskDecision,
    RiskDecisionStatus,
    RiskRejection,
    RiskRejectionCode,
    StrategyRiskRule,
    TradeProposal,
    TradeSide,
)

__all__ = ["KillSwitchEvaluator", "RiskEngine"]


class KillSwitchEvaluator:
    """Evaluate policy and operational kill triggers in a stable order."""

    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    def evaluate(self, context: RiskContext) -> KillSwitchDecision:
        triggers: list[KillSwitchTrigger] = []
        reasons: list[str] = []
        risk = self._config

        if not risk.research_configured:
            triggers.append(KillSwitchTrigger.UNCALIBRATED_RISK_POLICY)
            missing = ", ".join(risk.missing_thresholds) or "calibration status"
            reasons.append(f"risk policy is not fully RESEARCH_ONLY configured: {missing}")

        realized_loss = max(Decimal(0), -context.daily_realized_pnl_thb)
        total_loss = max(
            Decimal(0),
            -(context.daily_realized_pnl_thb + context.daily_unrealized_pnl_thb),
        )
        if (
            risk.max_daily_realized_loss_thb is not None
            and realized_loss >= risk.max_daily_realized_loss_thb
        ):
            triggers.append(KillSwitchTrigger.DAILY_REALIZED_LOSS)
            reasons.append("maximum daily realized loss reached")
        if (
            risk.max_daily_total_loss_thb is not None
            and total_loss >= risk.max_daily_total_loss_thb
        ):
            triggers.append(KillSwitchTrigger.DAILY_TOTAL_LOSS)
            reasons.append("maximum daily realized plus unrealized loss reached")
        if (
            risk.max_consecutive_losses is not None
            and context.consecutive_losses >= risk.max_consecutive_losses
        ):
            triggers.append(KillSwitchTrigger.MAX_CONSECUTIVE_LOSSES)
            reasons.append("maximum consecutive losses reached")
        if (
            risk.max_repeated_execution_errors is not None
            and context.repeated_execution_errors >= risk.max_repeated_execution_errors
        ):
            triggers.append(KillSwitchTrigger.REPEATED_EXECUTION_ERRORS)
            reasons.append("maximum repeated execution errors reached")
        if context.market_data_stale:
            triggers.append(KillSwitchTrigger.STALE_MARKET_DATA)
            reasons.append("market data is stale")
        if not context.feed_connected:
            triggers.append(KillSwitchTrigger.FEED_DISCONNECT)
            reasons.append("market-data feed is disconnected")
        if not context.broker_api_healthy:
            triggers.append(KillSwitchTrigger.BROKER_API_ERROR)
            reasons.append("broker API is unhealthy")
        if not context.reconciliation_matches:
            triggers.append(KillSwitchTrigger.RECONCILIATION_MISMATCH)
            reasons.append("broker reconciliation does not match local state")
        if context.emergency_manual_disable:
            triggers.append(KillSwitchTrigger.EMERGENCY_MANUAL_DISABLE)
            reasons.append("manual emergency disable is active")

        if context.existing_position is None:
            action = ExistingPositionAction.NO_POSITION
        elif triggers:
            action = ExistingPositionAction.KEEP_PROTECTION_AND_FLATTEN_WHEN_EXECUTABLE
        else:
            action = ExistingPositionAction.CONTINUE_APPROVED_EXIT_PLAN
        return KillSwitchDecision(
            evaluated_at=context.evaluated_at,
            active_triggers=tuple(triggers),
            reasons=tuple(reasons),
            existing_position_action=action,
        )


class RiskEngine:
    """Fail-closed risk evaluation and deterministic position sizing."""

    def __init__(self, config: TfexConfig) -> None:
        self._config = config
        self._kill_switch = KillSwitchEvaluator(config.risk)

    def evaluate(
        self,
        proposal: TradeProposal,
        *,
        strategy_rule: StrategyRiskRule,
        costs: CostAssumptions,
        context: RiskContext,
    ) -> RiskDecision:
        decision_id = f"risk:{proposal.proposal_id}:{context.evaluated_at.isoformat()}"
        kill_switch = self._kill_switch.evaluate(context)
        rejections: list[RiskRejection] = []

        if not self._config.risk.research_configured:
            self._reject(
                rejections,
                RiskRejectionCode.UNCALIBRATED_RISK_LIMITS,
                "risk thresholds remain UNCALIBRATED or incomplete",
            )
        if kill_switch.active_triggers:
            self._reject(
                rejections,
                RiskRejectionCode.KILL_SWITCH_ACTIVE,
                "new entries are disabled while any kill-switch trigger is active",
            )
        if strategy_rule.strategy_id != proposal.strategy_id:
            self._reject(
                rejections,
                RiskRejectionCode.STRATEGY_RULE_MISMATCH,
                "strategy proposal and risk rule identifiers differ",
            )
        if context.evaluated_at < proposal.confirmed_at:
            self._reject(
                rejections,
                RiskRejectionCode.SIGNAL_NOT_CONFIRMED,
                "risk evaluation cannot precede closed-bar signal confirmation",
            )
        if not context.new_entry_session_allowed:
            detail = "; ".join(context.session_gate_reasons) or "session gate denied entry"
            self._reject(
                rejections,
                RiskRejectionCode.SESSION_ENTRY_NOT_ALLOWED,
                detail,
            )
        if proposal.initial_stop_price is None:
            self._reject(rejections, RiskRejectionCode.STOP_REQUIRED, "entry requires a stop")
        if proposal.exit_plan is None:
            self._reject(
                rejections,
                RiskRejectionCode.EXIT_PLAN_REQUIRED,
                "entry requires a deterministic exit plan",
            )

        stop = proposal.initial_stop_price
        if stop is not None:
            if stop == proposal.entry_price:
                self._reject(
                    rejections,
                    RiskRejectionCode.STOP_DISTANCE_ZERO,
                    "entry and stop prices may not be equal",
                )
            elif (proposal.side is TradeSide.LONG and stop > proposal.entry_price) or (
                proposal.side is TradeSide.SHORT and stop < proposal.entry_price
            ):
                self._reject(
                    rejections,
                    RiskRejectionCode.STOP_SIDE_INVALID,
                    "stop must be below a long entry and above a short entry",
                )

        target = proposal.exit_plan.target_price if proposal.exit_plan is not None else None
        if target is not None and (
            (proposal.side is TradeSide.LONG and target <= proposal.entry_price)
            or (proposal.side is TradeSide.SHORT and target >= proposal.entry_price)
        ):
            self._reject(
                rejections,
                RiskRejectionCode.TARGET_SIDE_INVALID,
                "target must be above a long entry and below a short entry",
            )

        existing = context.existing_position
        if existing is not None:
            if existing.symbol != proposal.symbol or existing.side is not proposal.side:
                self._reject(
                    rejections,
                    RiskRejectionCode.OPPOSING_POSITION_EXISTS,
                    "a proposal cannot merge with another symbol or opposing position",
                )
            elif not self._config.risk.pyramiding_enabled:
                self._reject(
                    rejections,
                    RiskRejectionCode.PYRAMIDING_DISABLED,
                    "adding to an open position is disabled by default",
                )
            elif self._is_averaging_down(proposal, existing.average_entry_price):
                self._reject(
                    rejections,
                    RiskRejectionCode.AVERAGING_DOWN_PROHIBITED,
                    "averaging down is prohibited even when pyramiding is enabled",
                )
            elif not existing.is_profitable:
                self._reject(
                    rejections,
                    RiskRejectionCode.ADDING_TO_LOSING_POSITION,
                    "a losing or flat position cannot be increased",
                )
            elif self._widens_existing_stop(proposal, existing.current_stop_price):
                self._reject(
                    rejections,
                    RiskRejectionCode.STOP_WIDENING_PROHIBITED,
                    "a pyramid entry may not widen the existing position stop",
                )

        try:
            fees_per_contract = costs.round_trip_fees.total_thb()
        except FeeSemanticsError as exc:
            fees_per_contract = Decimal(0)
            self._reject(rejections, RiskRejectionCode.COST_MODEL_UNUSABLE, str(exc))

        maximum_slippage = self._config.risk.maximum_allowed_slippage_points
        if maximum_slippage is not None and costs.adverse_slippage_points > maximum_slippage:
            self._reject(
                rejections,
                RiskRejectionCode.SLIPPAGE_LIMIT_EXCEEDED,
                "adverse slippage assumption exceeds the configured maximum",
            )

        if rejections or stop is None or proposal.exit_plan is None:
            return self._rejected(decision_id, proposal, context, kill_switch, rejections)

        risk = self._config.risk
        max_risk = risk.max_risk_per_trade_thb
        max_realized = risk.max_daily_realized_loss_thb
        max_total = risk.max_daily_total_loss_thb
        max_contracts = risk.max_contracts
        global_minimum_rr = risk.minimum_acceptable_reward_risk
        assert max_risk is not None
        assert max_realized is not None
        assert max_total is not None
        assert max_contracts is not None
        assert global_minimum_rr is not None

        multiplier = self._config.contract.point_value_thb
        stop_distance = abs(proposal.entry_price - stop)
        gross_price_risk = stop_distance * multiplier
        slippage_risk = costs.adverse_slippage_points * multiplier
        risk_per_contract = (
            gross_price_risk
            + fees_per_contract
            + slippage_risk
            + costs.additional_cost_buffer_thb_per_contract
        )

        realized_loss = max(Decimal(0), -context.daily_realized_pnl_thb)
        total_loss = max(
            Decimal(0),
            -(context.daily_realized_pnl_thb + context.daily_unrealized_pnl_thb),
        )
        allowed_risk = min(
            max_risk,
            max(Decimal(0), max_realized - realized_loss),
            max(Decimal(0), max_total - total_loss),
        )
        existing_risk = (
            context.existing_position.current_total_risk_thb
            if context.existing_position is not None
            else Decimal(0)
        )
        available_risk = allowed_risk - existing_risk
        existing_contracts = (
            context.existing_position.contracts if context.existing_position is not None else 0
        )
        available_contracts = max_contracts - existing_contracts

        if allowed_risk <= 0:
            self._reject(
                rejections,
                RiskRejectionCode.DAILY_RISK_CAPACITY_EXHAUSTED,
                "daily loss capacity is exhausted",
            )
        elif available_contracts <= 0:
            self._reject(
                rejections,
                RiskRejectionCode.MAX_CONTRACTS_REACHED,
                "maximum total contracts already reached",
            )
        elif available_risk < risk_per_contract:
            self._reject(
                rejections,
                RiskRejectionCode.RISK_BUDGET_EXCEEDED,
                "one contract plus explicit costs exceeds available risk",
            )
        contracts_by_risk = (
            int((available_risk / risk_per_contract).to_integral_value(rounding=ROUND_FLOOR))
            if available_risk > 0
            else 0
        )
        contracts = max(0, min(contracts_by_risk, available_contracts))
        total_position_risk = existing_risk + risk_per_contract * contracts

        reward_points: Decimal | None = None
        gross_reward: Decimal | None = None
        net_reward_per_contract: Decimal | None = None
        net_reward_total: Decimal | None = None
        reward_risk: Decimal | None = None
        if target is not None:
            reward_points = abs(target - proposal.entry_price)
            gross_reward = reward_points * multiplier
            net_reward_per_contract = (
                gross_reward
                - fees_per_contract
                - slippage_risk
                - costs.additional_cost_buffer_thb_per_contract
            )
            net_reward_total = net_reward_per_contract * contracts
            reward_risk = net_reward_per_contract / risk_per_contract
            minimum_rr = max(
                global_minimum_rr,
                strategy_rule.minimum_reward_risk or Decimal(0),
            )
            if reward_risk < minimum_rr:
                self._reject(
                    rejections,
                    RiskRejectionCode.REWARD_RISK_INSUFFICIENT,
                    f"net initial reward/risk {reward_risk} is below required {minimum_rr}",
                )
        minimum_expectancy = strategy_rule.minimum_expectancy_r
        expectancy = proposal.estimated_expectancy_r
        if target is None and minimum_expectancy is None:
            self._reject(
                rejections,
                RiskRejectionCode.EXPECTANCY_INSUFFICIENT,
                "non-target exit requires a strategy-specific expectancy rule",
            )
        elif minimum_expectancy is not None and (
            expectancy is None or expectancy < minimum_expectancy
        ):
            self._reject(
                rejections,
                RiskRejectionCode.EXPECTANCY_INSUFFICIENT,
                "proposal does not meet the strategy-specific expectancy requirement",
            )

        calculation = RiskCalculation(
            entry_price=proposal.entry_price,
            stop_price=stop,
            stop_distance_points=stop_distance,
            contract_multiplier_thb_per_point=multiplier,
            gross_price_risk_per_contract_thb=gross_price_risk,
            round_trip_fees_per_contract_thb=fees_per_contract,
            slippage_allowance_per_contract_thb=slippage_risk,
            additional_cost_buffer_per_contract_thb=(costs.additional_cost_buffer_thb_per_contract),
            estimated_risk_per_contract_thb=risk_per_contract,
            allowed_risk_thb=allowed_risk,
            contracts=contracts,
            existing_position_risk_thb=existing_risk,
            total_position_risk_thb=total_position_risk,
            planned_reward_points=reward_points,
            gross_planned_reward_per_contract_thb=gross_reward,
            estimated_net_reward_per_contract_thb=net_reward_per_contract,
            estimated_net_reward_thb=net_reward_total,
            initial_reward_risk=reward_risk,
            estimated_expectancy_r=proposal.estimated_expectancy_r,
        )
        if rejections:
            return self._rejected(
                decision_id,
                proposal,
                context,
                kill_switch,
                rejections,
                calculation=calculation,
            )

        plan = ApprovedTradePlan(
            plan_id=f"plan:{decision_id}",
            risk_decision_id=decision_id,
            proposal=proposal,
            calculation=calculation,
            protective_exit=ProtectiveExitPlan(
                symbol=proposal.symbol,
                side=proposal.side,
                quantity=existing_contracts + contracts,
                initial_stop_price=stop,
                target_price=target,
                deterministic_rules=proposal.exit_plan.deterministic_rules,
            ),
            resulting_total_contracts=existing_contracts + contracts,
            cost_assumptions_id=costs.assumptions_id,
            strategy_rule_id=strategy_rule.research_rule_id,
        )
        return RiskDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            evaluated_at=context.evaluated_at,
            status=RiskDecisionStatus.APPROVED,
            kill_switch=kill_switch,
            context=context,
            calculation=calculation,
            approved_plan=plan,
        )

    @staticmethod
    def _is_averaging_down(proposal: TradeProposal, average_entry: Decimal) -> bool:
        if proposal.side is TradeSide.LONG:
            return proposal.entry_price < average_entry
        return proposal.entry_price > average_entry

    @staticmethod
    def _widens_existing_stop(proposal: TradeProposal, current_stop: Decimal) -> bool:
        proposed_stop = proposal.initial_stop_price
        assert proposed_stop is not None
        if proposal.side is TradeSide.LONG:
            return proposed_stop < current_stop
        return proposed_stop > current_stop

    @staticmethod
    def _reject(rejections: list[RiskRejection], code: RiskRejectionCode, message: str) -> None:
        rejections.append(RiskRejection(code=code, message=message))

    @staticmethod
    def _rejected(
        decision_id: str,
        proposal: TradeProposal,
        context: RiskContext,
        kill_switch: KillSwitchDecision,
        rejections: list[RiskRejection],
        *,
        calculation: RiskCalculation | None = None,
    ) -> RiskDecision:
        if not rejections:
            rejections.append(
                RiskRejection(
                    code=RiskRejectionCode.RISK_BUDGET_EXCEEDED,
                    message="risk evaluation failed closed without an approvable plan",
                )
            )
        return RiskDecision(
            decision_id=decision_id,
            proposal_id=proposal.proposal_id,
            evaluated_at=context.evaluated_at,
            status=RiskDecisionStatus.REJECTED,
            rejections=tuple(rejections),
            kill_switch=kill_switch,
            context=context,
            calculation=calculation,
        )
