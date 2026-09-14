"""Immutable contracts shared by future strategies, risk, positions, and paper execution.

These models are deliberately dormant: they contain no broker connection and submit no
orders. They lock the information and invariants that TFEX-4/TFEX-5 must preserve when
those milestones eventually start.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.costs.models import FeeKind, RoundTripCostEstimate

__all__ = [
    "ApprovedTradePlan",
    "AuditEvent",
    "AuditEventType",
    "AuditField",
    "CostAssumptions",
    "DecisionInput",
    "DeterministicExitRule",
    "ExistingPositionAction",
    "ExitPlanProposal",
    "ExitRuleType",
    "KillSwitchDecision",
    "KillSwitchTrigger",
    "PositionRiskSnapshot",
    "ProtectiveExitPlan",
    "RiskCalculation",
    "RiskContext",
    "RiskDecision",
    "RiskDecisionStatus",
    "RiskRejection",
    "RiskRejectionCode",
    "StrategyRiskRule",
    "TradeProposal",
    "TradeSide",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TradeSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitRuleType(StrEnum):
    TAKE_PROFIT = "TAKE_PROFIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    BREAK_EVEN = "BREAK_EVEN"
    STRUCTURE_TRAIL = "STRUCTURE_TRAIL"
    ATR_TRAIL = "ATR_TRAIL"
    TIME_STOP = "TIME_STOP"
    SESSION_EXIT = "SESSION_EXIT"
    EOD_FLATTEN = "EOD_FLATTEN"


class DecisionInput(_Frozen):
    """One named, serializable input used by a deterministic decision."""

    name: str = Field(min_length=1)
    value: str


class DeterministicExitRule(_Frozen):
    rule_id: str = Field(min_length=1)
    rule_type: ExitRuleType
    inputs: tuple[DecisionInput, ...] = Field(min_length=1)


class ExitPlanProposal(_Frozen):
    """Exit intent supplied by a strategy; protection is added by the risk engine."""

    target_price: Decimal | None = Field(default=None, gt=0)
    deterministic_rules: tuple[DeterministicExitRule, ...] = ()
    overnight_allowed: Literal[False] = False
    eod_flatten_required: Literal[True] = True

    @model_validator(mode="after")
    def _has_a_planned_exit(self) -> Self:
        if self.target_price is None and not self.deterministic_rules:
            raise ValueError("exit plan requires a target or deterministic exit rule")
        rule_ids = tuple(rule.rule_id for rule in self.deterministic_rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("deterministic exit rule IDs must be unique")
        return self


class StrategyRiskRule(_Frozen):
    """Strategy-specific RRR or expectancy requirement, configured before replay."""

    strategy_id: str = Field(min_length=1)
    minimum_reward_risk: Decimal | None = Field(default=None, gt=0)
    minimum_expectancy_r: Decimal | None = Field(default=None, gt=0)
    research_rule_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _has_an_acceptance_rule(self) -> Self:
        if self.minimum_reward_risk is None and self.minimum_expectancy_r is None:
            raise ValueError("strategy rule requires minimum RRR or minimum expectancy")
        return self


class TradeProposal(_Frozen):
    """A strategy proposal, never an order and intentionally carrying no quantity."""

    proposal_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    setup_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: TradeSide
    event_time: datetime
    confirmed_at: datetime
    entry_price: Decimal = Field(gt=0)
    initial_stop_price: Decimal | None = Field(default=None, gt=0)
    exit_plan: ExitPlanProposal | None = None
    estimated_expectancy_r: Decimal | None = None
    rationale_inputs: tuple[DecisionInput, ...] = Field(min_length=1)
    source_signal_ids: tuple[str, ...] = Field(min_length=1)
    live_order_requested: Literal[False] = False

    @model_validator(mode="after")
    def _time_and_identity_are_valid(self) -> Self:
        if self.event_time.tzinfo is None or self.confirmed_at.tzinfo is None:
            raise ValueError("event_time and confirmed_at must be timezone-aware")
        if self.confirmed_at < self.event_time:
            raise ValueError("confirmed_at cannot precede event_time")
        if self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be normalized uppercase")
        return self


class CostAssumptions(_Frozen):
    """Auditable round-trip costs and adverse stop-execution slippage per contract."""

    assumptions_id: str = Field(min_length=1)
    round_trip_fees: RoundTripCostEstimate
    adverse_slippage_points: Decimal = Field(ge=0)
    additional_cost_buffer_thb_per_contract: Decimal = Field(default=Decimal(0), ge=0)
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def _per_contract_and_no_double_counted_slippage(self) -> Self:
        if self.round_trip_fees.contracts != 1:
            raise ValueError("risk cost assumptions must be expressed per one contract")
        if not self.round_trip_fees.components:
            raise ValueError("cost assumptions require explicit fee/commission components")
        if any(component.kind is FeeKind.SLIPPAGE for component in self.round_trip_fees.components):
            raise ValueError("slippage belongs in adverse_slippage_points, not fee components")
        return self


class PositionRiskSnapshot(_Frozen):
    """Existing exposure supplied to a fresh total-position risk evaluation."""

    symbol: str = Field(min_length=1)
    side: TradeSide
    contracts: int = Field(gt=0)
    average_entry_price: Decimal = Field(gt=0)
    current_stop_price: Decimal = Field(gt=0)
    mark_price: Decimal = Field(gt=0)
    current_total_risk_thb: Decimal = Field(ge=0)

    @property
    def is_profitable(self) -> bool:
        if self.side is TradeSide.LONG:
            return self.mark_price > self.average_entry_price
        return self.mark_price < self.average_entry_price


class RiskContext(_Frozen):
    """Account/session health observed at one deterministic evaluation instant."""

    evaluated_at: datetime
    trading_date: date
    new_entry_session_allowed: bool = False
    session_gate_reasons: tuple[str, ...] = ("session eligibility was not supplied",)
    daily_realized_pnl_thb: Decimal = Decimal(0)
    daily_unrealized_pnl_thb: Decimal = Decimal(0)
    consecutive_losses: int = Field(default=0, ge=0)
    repeated_execution_errors: int = Field(default=0, ge=0)
    market_data_stale: bool = True
    feed_connected: bool = False
    broker_api_healthy: bool = False
    reconciliation_matches: bool = False
    emergency_manual_disable: bool = False
    existing_position: PositionRiskSnapshot | None = None

    @model_validator(mode="after")
    def _aware_time(self) -> Self:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("risk evaluation time must be timezone-aware")
        if self.new_entry_session_allowed and self.session_gate_reasons:
            raise ValueError("allowed session evidence cannot carry denial reasons")
        return self


class KillSwitchTrigger(StrEnum):
    DAILY_REALIZED_LOSS = "DAILY_REALIZED_LOSS"
    DAILY_TOTAL_LOSS = "DAILY_TOTAL_LOSS"
    MAX_CONSECUTIVE_LOSSES = "MAX_CONSECUTIVE_LOSSES"
    REPEATED_EXECUTION_ERRORS = "REPEATED_EXECUTION_ERRORS"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    FEED_DISCONNECT = "FEED_DISCONNECT"
    BROKER_API_ERROR = "BROKER_API_ERROR"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    EMERGENCY_MANUAL_DISABLE = "EMERGENCY_MANUAL_DISABLE"
    UNCALIBRATED_RISK_POLICY = "UNCALIBRATED_RISK_POLICY"


class ExistingPositionAction(StrEnum):
    NO_POSITION = "NO_POSITION"
    CONTINUE_APPROVED_EXIT_PLAN = "CONTINUE_APPROVED_EXIT_PLAN"
    KEEP_PROTECTION_AND_FLATTEN_WHEN_EXECUTABLE = "KEEP_PROTECTION_AND_FLATTEN_WHEN_EXECUTABLE"


class KillSwitchDecision(_Frozen):
    evaluated_at: datetime
    active_triggers: tuple[KillSwitchTrigger, ...] = ()
    reasons: tuple[str, ...] = ()
    existing_position_action: ExistingPositionAction

    @model_validator(mode="after")
    def _auditable_trigger_shape(self) -> Self:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("kill-switch evaluation time must be timezone-aware")
        if len(self.active_triggers) != len(set(self.active_triggers)):
            raise ValueError("kill-switch triggers must be unique")
        if len(self.active_triggers) != len(self.reasons):
            raise ValueError("each kill-switch trigger requires one reason")
        return self

    @property
    def new_entries_allowed(self) -> bool:
        return not self.active_triggers


class RiskRejectionCode(StrEnum):
    UNCALIBRATED_RISK_LIMITS = "UNCALIBRATED_RISK_LIMITS"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    STOP_REQUIRED = "STOP_REQUIRED"
    STOP_SIDE_INVALID = "STOP_SIDE_INVALID"
    STOP_DISTANCE_ZERO = "STOP_DISTANCE_ZERO"
    EXIT_PLAN_REQUIRED = "EXIT_PLAN_REQUIRED"
    TARGET_SIDE_INVALID = "TARGET_SIDE_INVALID"
    COST_MODEL_UNUSABLE = "COST_MODEL_UNUSABLE"
    SLIPPAGE_LIMIT_EXCEEDED = "SLIPPAGE_LIMIT_EXCEEDED"
    RISK_BUDGET_EXCEEDED = "RISK_BUDGET_EXCEEDED"
    DAILY_RISK_CAPACITY_EXHAUSTED = "DAILY_RISK_CAPACITY_EXHAUSTED"
    REWARD_RISK_INSUFFICIENT = "REWARD_RISK_INSUFFICIENT"
    EXPECTANCY_INSUFFICIENT = "EXPECTANCY_INSUFFICIENT"
    STRATEGY_RULE_MISMATCH = "STRATEGY_RULE_MISMATCH"
    PYRAMIDING_DISABLED = "PYRAMIDING_DISABLED"
    AVERAGING_DOWN_PROHIBITED = "AVERAGING_DOWN_PROHIBITED"
    ADDING_TO_LOSING_POSITION = "ADDING_TO_LOSING_POSITION"
    OPPOSING_POSITION_EXISTS = "OPPOSING_POSITION_EXISTS"
    MAX_CONTRACTS_REACHED = "MAX_CONTRACTS_REACHED"
    STOP_WIDENING_PROHIBITED = "STOP_WIDENING_PROHIBITED"
    SESSION_ENTRY_NOT_ALLOWED = "SESSION_ENTRY_NOT_ALLOWED"
    SIGNAL_NOT_CONFIRMED = "SIGNAL_NOT_CONFIRMED"


class RiskRejection(_Frozen):
    code: RiskRejectionCode
    message: str = Field(min_length=1)


class RiskCalculation(_Frozen):
    entry_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    stop_distance_points: Decimal = Field(gt=0)
    contract_multiplier_thb_per_point: Decimal = Field(gt=0)
    gross_price_risk_per_contract_thb: Decimal = Field(gt=0)
    round_trip_fees_per_contract_thb: Decimal = Field(ge=0)
    slippage_allowance_per_contract_thb: Decimal = Field(ge=0)
    additional_cost_buffer_per_contract_thb: Decimal = Field(ge=0)
    estimated_risk_per_contract_thb: Decimal = Field(gt=0)
    allowed_risk_thb: Decimal = Field(ge=0)
    contracts: int = Field(ge=0)
    existing_position_risk_thb: Decimal = Field(default=Decimal(0), ge=0)
    total_position_risk_thb: Decimal = Field(ge=0)
    planned_reward_points: Decimal | None = Field(default=None, gt=0)
    gross_planned_reward_per_contract_thb: Decimal | None = Field(default=None, gt=0)
    estimated_net_reward_per_contract_thb: Decimal | None = None
    estimated_net_reward_thb: Decimal | None = None
    initial_reward_risk: Decimal | None = None
    estimated_expectancy_r: Decimal | None = None

    @model_validator(mode="after")
    def _reward_fields_are_complete_when_applicable(self) -> Self:
        reward_values = (
            self.gross_planned_reward_per_contract_thb,
            self.estimated_net_reward_per_contract_thb,
            self.estimated_net_reward_thb,
            self.initial_reward_risk,
        )
        if self.planned_reward_points is None and any(value is not None for value in reward_values):
            raise ValueError("fixed reward values require planned_reward_points")
        if self.planned_reward_points is not None and any(value is None for value in reward_values):
            raise ValueError("planned target requires complete gross/net reward and RRR values")
        minimum_new_risk = self.estimated_risk_per_contract_thb * self.contracts
        if self.total_position_risk_thb < minimum_new_risk:
            raise ValueError("total position risk cannot be below calculated new-entry risk")
        return self


class ProtectiveExitPlan(_Frozen):
    symbol: str
    side: TradeSide
    quantity: int = Field(gt=0)
    initial_stop_price: Decimal = Field(gt=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    deterministic_rules: tuple[DeterministicExitRule, ...] = ()
    stop_widening_allowed: Literal[False] = False
    overnight_allowed: Literal[False] = False
    eod_flatten_required: Literal[True] = True


class ApprovedTradePlan(_Frozen):
    """The only object the future execution boundary may accept."""

    plan_id: str = Field(min_length=1)
    risk_decision_id: str = Field(min_length=1)
    proposal: TradeProposal
    calculation: RiskCalculation
    protective_exit: ProtectiveExitPlan
    resulting_total_contracts: int = Field(gt=0)
    cost_assumptions_id: str = Field(min_length=1)
    strategy_rule_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _all_plan_parts_agree(self) -> Self:
        stop = self.proposal.initial_stop_price
        exit_plan = self.proposal.exit_plan
        if stop is None or exit_plan is None:
            raise ValueError("approved plan requires proposal stop and exit plan")
        if self.calculation.contracts < 1:
            raise ValueError("approved plan requires at least one calculated contract")
        if stop == self.proposal.entry_price:
            raise ValueError("approved plan cannot have zero stop distance")
        if (self.proposal.side is TradeSide.LONG and stop > self.proposal.entry_price) or (
            self.proposal.side is TradeSide.SHORT and stop < self.proposal.entry_price
        ):
            raise ValueError("approved stop is on the invalid side of entry")
        target = exit_plan.target_price
        if target is not None and (
            (self.proposal.side is TradeSide.LONG and target <= self.proposal.entry_price)
            or (self.proposal.side is TradeSide.SHORT and target >= self.proposal.entry_price)
        ):
            raise ValueError("approved target is on the invalid side of entry")
        if self.calculation.entry_price != self.proposal.entry_price:
            raise ValueError("calculation entry differs from proposal")
        if self.calculation.stop_price != stop:
            raise ValueError("calculation stop differs from proposal")
        if self.protective_exit.symbol != self.proposal.symbol:
            raise ValueError("protective symbol differs from proposal")
        if self.protective_exit.side is not self.proposal.side:
            raise ValueError("protective side differs from proposal")
        if self.protective_exit.initial_stop_price != stop:
            raise ValueError("protective stop differs from proposal")
        if self.protective_exit.target_price != exit_plan.target_price:
            raise ValueError("protective target differs from proposal")
        if self.protective_exit.deterministic_rules != exit_plan.deterministic_rules:
            raise ValueError("protective deterministic rules differ from proposal")
        if self.resulting_total_contracts < self.calculation.contracts:
            raise ValueError("resulting quantity cannot be below newly approved quantity")
        if self.protective_exit.quantity != self.resulting_total_contracts:
            raise ValueError("protective plan must cover the entire resulting position")
        return self


class RiskDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskDecision(_Frozen):
    decision_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    evaluated_at: datetime
    status: RiskDecisionStatus
    rejections: tuple[RiskRejection, ...] = ()
    kill_switch: KillSwitchDecision
    context: RiskContext
    calculation: RiskCalculation | None = None
    approved_plan: ApprovedTradePlan | None = None

    @model_validator(mode="after")
    def _decision_shape_matches_status(self) -> Self:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("risk decision time must be timezone-aware")
        if self.context.evaluated_at != self.evaluated_at:
            raise ValueError("risk decision and context evaluation times differ")
        if self.status is RiskDecisionStatus.APPROVED:
            if self.rejections or self.calculation is None or self.approved_plan is None:
                raise ValueError("approved decision requires calculation and approved plan")
            if self.proposal_id != self.approved_plan.proposal.proposal_id:
                raise ValueError("risk decision proposal differs from approved plan")
            if self.decision_id != self.approved_plan.risk_decision_id:
                raise ValueError("approved plan references another risk decision")
            if self.calculation != self.approved_plan.calculation:
                raise ValueError("risk decision calculation differs from approved plan")
            if not self.context.new_entry_session_allowed:
                raise ValueError("approved decision requires affirmative session evidence")
            if not self.kill_switch.new_entries_allowed:
                raise ValueError("approved decision cannot carry an active kill switch")
        elif self.approved_plan is not None or not self.rejections:
            raise ValueError("rejected decision requires reasons and no approved plan")
        return self


class AuditEventType(StrEnum):
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    ORDER_STATE_CHANGED = "ORDER_STATE_CHANGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    STOP_MODIFIED = "STOP_MODIFIED"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    EXIT = "EXIT"
    KILL_SWITCH_CHANGED = "KILL_SWITCH_CHANGED"
    RECONCILIATION = "RECONCILIATION"


class AuditField(_Frozen):
    name: str = Field(min_length=1)
    value: str


class AuditEvent(_Frozen):
    audit_id: str = Field(min_length=1)
    trade_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    event_type: AuditEventType
    event_time: datetime
    recorded_at: datetime
    fields: tuple[AuditField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _auditable_times(self) -> Self:
        if self.event_time.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("audit timestamps must be timezone-aware")
        if self.recorded_at < self.event_time:
            raise ValueError("audit recorded_at cannot precede event_time")
        names = tuple(field.name for field in self.fields)
        if len(names) != len(set(names)):
            raise ValueError("audit field names must be unique")
        return self
