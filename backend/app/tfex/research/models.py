"""Immutable contracts for future TFEX strategy research and acceptance.

This package is specification and deterministic test scaffolding only. It does not load
bars, calculate indicators, optimize parameters, replay a strategy, or submit an order.
Its purpose is to make invalid evidence unrepresentable before those runtimes exist.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.costs.models import CostScenario, FeeKind, RoundTripCostEstimate
from app.tfex.risk.models import ApprovedTradePlan


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PartitionRole(StrEnum):
    DEVELOPMENT_CALIBRATION = "A_DEVELOPMENT_CALIBRATION"
    VALIDATION = "B_VALIDATION"
    FINAL_HOLDOUT = "C_UNTOUCHED_FINAL_HOLDOUT"
    FORWARD_PAPER = "D_FORWARD_PAPER"


class PartitionMethod(StrEnum):
    CHRONOLOGICAL = "CHRONOLOGICAL"


class DataPartition(_Frozen):
    partition_id: str = Field(min_length=1)
    role: PartitionRole
    start: datetime
    end: datetime
    dataset_id: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    interval: Literal["1m"] = "1m"
    source_timezone: str = Field(min_length=1)
    normalized_timezone: str = Field(min_length=1)
    synthetic: bool
    continuous_contract: Literal[False] = False

    @model_validator(mode="after")
    def _ordered_raw_contract_partition(self) -> Self:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("partition boundaries must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("partition end must be after start")
        if self.symbol != self.symbol.strip().upper():
            raise ValueError("partition symbol must be normalized uppercase")
        if re.fullmatch(r"S50[FGHJKMNQUVXZ]\d{2}", self.symbol) is None:
            raise ValueError("acceptance partitions require one raw S50 contract symbol")
        return self


class PartitionPlan(_Frozen):
    plan_id: str = Field(min_length=1)
    method: Literal[PartitionMethod.CHRONOLOGICAL] = PartitionMethod.CHRONOLOGICAL
    created_at: datetime
    partitions: tuple[DataPartition, ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def _strict_chronology_and_provenance(self) -> Self:
        if self.created_at.tzinfo is None:
            raise ValueError("partition-plan created_at must be timezone-aware")
        expected = tuple(PartitionRole)
        actual = tuple(part.role for part in self.partitions)
        if actual != expected:
            raise ValueError(
                "partitions must be ordered A development, B validation, C holdout, D forward"
            )
        ids = tuple(part.partition_id for part in self.partitions)
        if len(ids) != len(set(ids)):
            raise ValueError("partition IDs must be unique")
        first_symbol = self.partitions[0].symbol
        for earlier, later in zip(self.partitions, self.partitions[1:], strict=False):
            if earlier.end > later.start:
                raise ValueError("research partitions may not overlap")
            if later.symbol != first_symbol:
                raise ValueError("one partition plan may not splice raw contract symbols")
        return self


class HoldoutState(StrEnum):
    UNTOUCHED = "UNTOUCHED"
    CONSUMED_FINAL_EVALUATION = "CONSUMED_FINAL_EVALUATION"
    BURNED_FOR_TUNING = "BURNED_FOR_TUNING"


class HoldoutAccessPurpose(StrEnum):
    FINAL_EVALUATION = "FINAL_EVALUATION"
    TUNING = "TUNING"
    DIAGNOSTIC_INSPECTION = "DIAGNOSTIC_INSPECTION"


class HoldoutAccess(_Frozen):
    trial_id: str = Field(min_length=1)
    purpose: HoldoutAccessPurpose
    accessed_at: datetime

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.accessed_at.tzinfo is None:
            raise ValueError("holdout access time must be timezone-aware")
        return self


class HoldoutLedger(_Frozen):
    partition_id: str = Field(min_length=1)
    state: HoldoutState = HoldoutState.UNTOUCHED
    accesses: tuple[HoldoutAccess, ...] = ()

    @model_validator(mode="after")
    def _state_matches_history(self) -> Self:
        if not self.accesses and self.state is not HoldoutState.UNTOUCHED:
            raise ValueError("a changed holdout state requires an access record")
        if self.accesses and self.state is HoldoutState.UNTOUCHED:
            raise ValueError("an accessed holdout cannot remain untouched")
        if len(self.accesses) > 1:
            raise ValueError("a holdout may be inspected only once")
        if self.accesses:
            purpose = self.accesses[0].purpose
            expected = (
                HoldoutState.CONSUMED_FINAL_EVALUATION
                if purpose is HoldoutAccessPurpose.FINAL_EVALUATION
                else HoldoutState.BURNED_FOR_TUNING
            )
            if self.state is not expected:
                raise ValueError("holdout state does not match its access purpose")
        return self


class WalkForwardMethod(StrEnum):
    ANCHORED = "ANCHORED"
    ROLLING = "ROLLING"


class WalkForwardFold(_Frozen):
    fold_id: str = Field(min_length=1)
    calibration_start: datetime
    calibration_end: datetime
    validation_start: datetime
    validation_end: datetime
    parameters_selected_at: datetime
    selected_parameter_set_id: str = Field(min_length=1)
    trade_count: int = Field(ge=0)
    gross_pnl_thb: Decimal
    total_costs_thb: Decimal = Field(ge=0)
    net_pnl_thb: Decimal
    expectancy_r: Decimal | None
    max_drawdown_thb: Decimal = Field(ge=0)
    rejection_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def _causal_fold(self) -> Self:
        values = (
            self.calibration_start,
            self.calibration_end,
            self.validation_start,
            self.validation_end,
            self.parameters_selected_at,
        )
        if any(value.tzinfo is None for value in values):
            raise ValueError("walk-forward timestamps must be timezone-aware")
        if not self.calibration_start < self.calibration_end <= self.validation_start:
            raise ValueError("calibration must finish before validation starts")
        if self.validation_end <= self.validation_start:
            raise ValueError("validation end must be after validation start")
        if not self.calibration_start <= self.parameters_selected_at <= self.calibration_end:
            raise ValueError("parameters must be selected from the calibration window")
        if self.net_pnl_thb != self.gross_pnl_thb - self.total_costs_thb:
            raise ValueError("fold net P&L must equal gross P&L minus costs")
        return self


class WalkForwardPlan(_Frozen):
    plan_id: str = Field(min_length=1)
    method: WalkForwardMethod
    folds: tuple[WalkForwardFold, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _deterministic_fold_sequence(self) -> Self:
        ids = tuple(fold.fold_id for fold in self.folds)
        if len(ids) != len(set(ids)):
            raise ValueError("walk-forward fold IDs must be unique")
        for previous, current in zip(self.folds, self.folds[1:], strict=False):
            if previous.validation_end > current.validation_start:
                raise ValueError("walk-forward validation windows may not overlap")
            if self.method is WalkForwardMethod.ANCHORED:
                if previous.calibration_start != current.calibration_start:
                    raise ValueError("anchored folds must retain the original calibration start")
            elif current.calibration_start <= previous.calibration_start:
                raise ValueError("rolling folds must advance the calibration start")
        return self


class NormalizationScope(StrEnum):
    EXPANDING_PAST_ONLY = "EXPANDING_PAST_ONLY"
    CALIBRATION_WINDOW_ONLY = "CALIBRATION_WINDOW_ONLY"


class FeatureDefinition(_Frozen):
    feature_id: str = Field(min_length=1)
    lookback_bars: int = Field(gt=0)
    shift_periods: int = Field(ge=0)
    centered_rolling: Literal[False] = False
    normalization_scope: NormalizationScope
    uses_future_session_extrema: Literal[False] = False
    confirmed_history_immutable: Literal[True] = True


class InformationArtifact(_Frozen):
    artifact_id: str = Field(min_length=1)
    event_time: datetime
    confirmed_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _confirmation_order(self) -> Self:
        if self.event_time.tzinfo is None or self.confirmed_at.tzinfo is None:
            raise ValueError("information times must be timezone-aware")
        if self.confirmed_at < self.event_time:
            raise ValueError("confirmation cannot precede the event")
        return self


class DecisionSnapshot(_Frozen):
    decision_time: datetime
    available_information: tuple[InformationArtifact, ...]

    @model_validator(mode="after")
    def _only_confirmed_information(self) -> Self:
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        ids = tuple(item.artifact_id for item in self.available_information)
        if len(ids) != len(set(ids)):
            raise ValueError("a decision snapshot cannot contain revised duplicate artifacts")
        if any(item.confirmed_at > self.decision_time for item in self.available_information):
            raise ValueError("decision snapshot contains information confirmed in the future")
        return self


class ConfirmedHistoryLedger(_Frozen):
    artifacts: tuple[InformationArtifact, ...] = ()

    @model_validator(mode="after")
    def _unique_immutable_history(self) -> Self:
        ids = tuple(item.artifact_id for item in self.artifacts)
        if len(ids) != len(set(ids)):
            raise ValueError("confirmed artifacts are append-only and may not be revised")
        if tuple(sorted(self.artifacts, key=lambda item: item.confirmed_at)) != self.artifacts:
            raise ValueError("confirmed history must be ordered by confirmed_at")
        return self


class ResearchAssumptionStatus(StrEnum):
    RESEARCH_ASSUMPTION = "RESEARCH_ASSUMPTION"


class ResearchCostModel(_Frozen):
    cost_model_id: str = Field(min_length=1)
    status: Literal[ResearchAssumptionStatus.RESEARCH_ASSUMPTION] = (
        ResearchAssumptionStatus.RESEARCH_ASSUMPTION
    )
    round_trip_fees: RoundTripCostEstimate
    slippage_points_per_side: Decimal = Field(ge=0)
    contract_multiplier_thb_per_point: Decimal = Field(gt=0)
    tick_size_points: Decimal = Field(gt=0)
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def _complete_research_costs(self) -> Self:
        if self.round_trip_fees.scenario is CostScenario.PRODUCTION:
            raise ValueError("research costs cannot be labelled as production accounting")
        kinds = {component.kind for component in self.round_trip_fees.components}
        required = {FeeKind.EXCHANGE_FEE, FeeKind.BROKER_COMMISSION}
        if not required.issubset(kinds):
            raise ValueError("research costs require explicit exchange and broker components")
        if self.round_trip_fees.unknown_components:
            raise ValueError("every research cost component requires a labelled numeric assumption")
        return self


class CostSensitivityPlan(_Frozen):
    plan_id: str = Field(min_length=1)
    baseline_cost_model_id: str = Field(min_length=1)
    sensitivity_cost_model_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct_scenarios(self) -> Self:
        ids = (self.baseline_cost_model_id, *self.sensitivity_cost_model_ids)
        if len(ids) != len(set(ids)):
            raise ValueError("cost sensitivity scenarios must be distinct")
        return self


class DailyPnl(_Frozen):
    trading_date: date
    gross_pnl_thb: Decimal
    costs_thb: Decimal = Field(ge=0)
    net_pnl_thb: Decimal

    @model_validator(mode="after")
    def _net_matches(self) -> Self:
        if self.net_pnl_thb != self.gross_pnl_thb - self.costs_thb:
            raise ValueError("daily net P&L must equal gross P&L minus costs")
        return self


class ConfidenceEstimate(_Frozen):
    method: str = Field(min_length=1)
    confidence_level: Decimal = Field(gt=0, lt=1)
    lower: Decimal
    upper: Decimal

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.upper < self.lower:
            raise ValueError("confidence upper bound precedes lower bound")
        return self


class PerformanceMetrics(_Frozen):
    total_trades: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    breakeven_trades: int = Field(ge=0)
    win_rate: Decimal = Field(ge=0, le=1)
    average_win_thb: Decimal = Field(ge=0)
    average_loss_thb: Decimal = Field(le=0)
    expectancy_per_trade_thb: Decimal
    expectancy_r: Decimal
    profit_factor: Decimal | None = Field(default=None, ge=0)
    gross_pnl_thb: Decimal
    total_costs_thb: Decimal = Field(ge=0)
    net_pnl_thb: Decimal
    average_r: Decimal
    median_r: Decimal
    max_drawdown_thb: Decimal = Field(ge=0)
    max_drawdown_duration_seconds: int = Field(ge=0)
    average_mae_r: Decimal = Field(ge=0)
    average_mfe_r: Decimal = Field(ge=0)
    max_consecutive_losses: int = Field(ge=0)
    daily_pnl_distribution: tuple[DailyPnl, ...]
    trades_per_day: Decimal = Field(ge=0)
    exposure_fraction: Decimal = Field(ge=0, le=1)
    rejected_setups: int = Field(ge=0)
    slippage_sensitivity_net_pnl: tuple[Decimal, ...] = Field(min_length=2)
    confidence_estimate: ConfidenceEstimate | None = None

    @model_validator(mode="after")
    def _internally_consistent(self) -> Self:
        if self.winning_trades + self.losing_trades + self.breakeven_trades != self.total_trades:
            raise ValueError("win/loss/breakeven counts must sum to total trades")
        expected_win_rate = (
            Decimal(0)
            if self.total_trades == 0
            else Decimal(self.winning_trades) / Decimal(self.total_trades)
        )
        if self.win_rate != expected_win_rate:
            raise ValueError("win_rate must match the recorded trade counts")
        if self.net_pnl_thb != self.gross_pnl_thb - self.total_costs_thb:
            raise ValueError("net P&L must equal gross P&L minus costs")
        dates = tuple(item.trading_date for item in self.daily_pnl_distribution)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("daily P&L distribution must be unique and chronological")
        return self


class StrategyFamily(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class ExitPolicyKind(StrEnum):
    FIXED_R = "FIXED_R"
    STRUCTURE_TARGET = "STRUCTURE_TARGET"
    VWAP_TARGET = "VWAP_TARGET"
    PARTIAL_PLUS_RUNNER = "PARTIAL_PLUS_RUNNER"
    STRUCTURE_TRAIL = "STRUCTURE_TRAIL"
    ATR_TRAIL = "ATR_TRAIL"
    TIME_BASED = "TIME_BASED"


class ParameterValue(_Frozen):
    name: str = Field(min_length=1)
    value: str


class ParameterSet(_Frozen):
    parameter_set_id: str = Field(min_length=1)
    values: tuple[ParameterValue, ...]

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        names = tuple(item.name for item in self.values)
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        return self


class RobustnessVerdict(StrEnum):
    UNASSESSED = "UNASSESSED"
    PLATEAU_EVIDENCE = "PLATEAU_EVIDENCE"
    FRAGILE_NARROW_OPTIMUM = "FRAGILE_NARROW_OPTIMUM"


class ParameterNeighborhood(_Frozen):
    neighborhood_id: str = Field(min_length=1)
    parameter_name: str = Field(min_length=1)
    lower_parameter_set_id: str = Field(min_length=1)
    center_parameter_set_id: str = Field(min_length=1)
    upper_parameter_set_id: str = Field(min_length=1)
    verdict: RobustnessVerdict = RobustnessVerdict.UNASSESSED
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _three_distinct_points(self) -> Self:
        ids = (
            self.lower_parameter_set_id,
            self.center_parameter_set_id,
            self.upper_parameter_set_id,
        )
        if len(set(ids)) != 3:
            raise ValueError("parameter robustness requires distinct lower, center, and upper sets")
        if self.verdict is RobustnessVerdict.FRAGILE_NARROW_OPTIMUM and not self.reasons:
            raise ValueError("a fragile optimum requires rejection reasons")
        return self


class TrialStatus(StrEnum):
    PLANNED = "PLANNED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class EvaluationMode(StrEnum):
    BACKTEST = "BACKTEST"
    WALK_FORWARD = "WALK_FORWARD"
    HOLDOUT = "HOLDOUT"
    FORWARD_TEST = "FORWARD_TEST"
    PAPER_TRADING = "PAPER_TRADING"
    OPERATIONAL_PROVING = "OPERATIONAL_PROVING"


class ParameterSearchDeclaration(_Frozen):
    search_id: str = Field(min_length=1)
    declared_at: datetime
    strategy: StrategyFamily
    parameter_set_ids: tuple[str, ...] = Field(min_length=1)
    filter_variant_ids: tuple[str, ...] = Field(min_length=1)
    exit_variants: tuple[ExitPolicyKind, ...] = Field(min_length=1)
    stop_variant_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_declaration(self) -> Self:
        if self.declared_at.tzinfo is None:
            raise ValueError("search declaration time must be timezone-aware")
        for values in (
            self.parameter_set_ids,
            self.filter_variant_ids,
            self.exit_variants,
            self.stop_variant_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("search variants must be unique")
        return self


class TrialDefinition(_Frozen):
    trial_id: str = Field(min_length=1)
    registered_at: datetime
    strategy: StrategyFamily
    evaluation_mode: EvaluationMode
    partition_plan_id: str = Field(min_length=1)
    parameter_search_id: str = Field(min_length=1)
    parameter_set_id: str = Field(min_length=1)
    filter_variant_id: str = Field(min_length=1)
    exit_variant: ExitPolicyKind
    stop_variant_id: str = Field(min_length=1)
    cost_model_id: str = Field(min_length=1)
    execution_policy_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.registered_at.tzinfo is None:
            raise ValueError("trial registration time must be timezone-aware")
        return self


class TrialResult(_Frozen):
    trial_id: str = Field(min_length=1)
    status: TrialStatus
    completed_at: datetime
    metrics: PerformanceMetrics | None = None
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _result_shape(self) -> Self:
        if self.completed_at.tzinfo is None:
            raise ValueError("trial completion time must be timezone-aware")
        if self.status in {TrialStatus.FAILED, TrialStatus.REJECTED} and not self.reasons:
            raise ValueError("failed and rejected trials require retained reasons")
        if self.status is TrialStatus.SUCCEEDED and self.metrics is None:
            raise ValueError("successful trials require complete metrics")
        if self.status is TrialStatus.PLANNED:
            raise ValueError("PLANNED is not a terminal trial result")
        return self


class TrialRegistry(_Frozen):
    searches: tuple[ParameterSearchDeclaration, ...] = ()
    trials: tuple[TrialDefinition, ...] = ()
    results: tuple[TrialResult, ...] = ()

    @model_validator(mode="after")
    def _append_only_registry(self) -> Self:
        search_ids = tuple(item.search_id for item in self.searches)
        trial_ids = tuple(item.trial_id for item in self.trials)
        result_ids = tuple(item.trial_id for item in self.results)
        if len(search_ids) != len(set(search_ids)):
            raise ValueError("parameter-search IDs are immutable and cannot be reused")
        if len(trial_ids) != len(set(trial_ids)):
            raise ValueError("trial IDs are immutable and cannot be reused")
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("a trial result cannot be overwritten")
        definitions = {trial.trial_id: trial for trial in self.trials}
        searches = {search.search_id: search for search in self.searches}
        for trial in self.trials:
            search = searches.get(trial.parameter_search_id)
            if search is None:
                raise ValueError("every trial must cite a predeclared parameter search")
            if trial.registered_at < search.declared_at:
                raise ValueError("a trial cannot predate its search declaration")
            if trial.strategy is not search.strategy:
                raise ValueError("trial strategy differs from its declared search")
            if trial.parameter_set_id not in search.parameter_set_ids:
                raise ValueError("trial parameter set was not declared")
            if trial.filter_variant_id not in search.filter_variant_ids:
                raise ValueError("trial filter was not declared")
            if trial.exit_variant not in search.exit_variants:
                raise ValueError("trial exit was not declared")
            if trial.stop_variant_id not in search.stop_variant_ids:
                raise ValueError("trial stop was not declared")
        if any(result.trial_id not in definitions for result in self.results):
            raise ValueError("trial result has no registered definition")
        if any(
            result.completed_at < definitions[result.trial_id].registered_at
            for result in self.results
        ):
            raise ValueError("trial result cannot predate its registered definition")
        return self


class StratumDimension(StrEnum):
    SESSION = "SESSION"
    MARKET_REGIME = "MARKET_REGIME"
    VOLATILITY = "VOLATILITY"
    RELATIVE_VOLUME = "RELATIVE_VOLUME"


class StratifiedPerformance(_Frozen):
    dimension: StratumDimension
    label: str = Field(min_length=1)
    deterministic_label_rule_id: str = Field(min_length=1)
    metrics: PerformanceMetrics


class StrategyEvaluationReport(_Frozen):
    report_id: str = Field(min_length=1)
    strategy: StrategyFamily
    trial_id: str = Field(min_length=1)
    setup_count: int = Field(ge=0)
    accepted_setup_count: int = Field(ge=0)
    rejected_setup_count: int = Field(ge=0)
    setup_frequency_per_day: Decimal = Field(ge=0)
    aggregate_metrics: PerformanceMetrics
    strata: tuple[StratifiedPerformance, ...]

    @model_validator(mode="after")
    def _required_independent_strata(self) -> Self:
        if self.accepted_setup_count + self.rejected_setup_count != self.setup_count:
            raise ValueError("accepted and rejected setup counts must equal all setups")
        required = {
            (StratumDimension.SESSION, "MORNING"),
            (StratumDimension.SESSION, "AFTERNOON"),
            (StratumDimension.MARKET_REGIME, "TREND"),
            (StratumDimension.MARKET_REGIME, "RANGE"),
            (StratumDimension.VOLATILITY, "HIGH"),
            (StratumDimension.VOLATILITY, "LOW"),
            (StratumDimension.RELATIVE_VOLUME, "HIGH"),
            (StratumDimension.RELATIVE_VOLUME, "LOW"),
        }
        actual = {(item.dimension, item.label) for item in self.strata}
        missing = required - actual
        if missing:
            raise ValueError(f"strategy report is missing deterministic strata: {sorted(missing)}")
        return self


class SelectionMode(StrEnum):
    ALL_QUALIFIED = "ALL_QUALIFIED"
    BEST_SETUP_ONLY = "BEST_SETUP_ONLY"


class DailySelectionProtocol(_Frozen):
    protocol_id: str = Field(min_length=1)
    mode: SelectionMode
    declared_at: datetime
    ranking_rule_id: str | None = None
    ranking_input_names: tuple[str, ...] = ()
    outcomes_used_in_ranking: Literal[False] = False

    @model_validator(mode="after")
    def _predeclared_ranking(self) -> Self:
        if self.declared_at.tzinfo is None:
            raise ValueError("selection declaration time must be timezone-aware")
        if self.mode is SelectionMode.BEST_SETUP_ONLY and (
            not self.ranking_rule_id or not self.ranking_input_names
        ):
            raise ValueError(
                "best-setup-only research requires a predeclared ranking rule and inputs"
            )
        return self


class BestSetupComparison(_Frozen):
    comparison_id: str = Field(min_length=1)
    all_qualified_trial_id: str = Field(min_length=1)
    best_only_trial_id: str = Field(min_length=1)
    partition_plan_id: str = Field(min_length=1)
    parameter_set_id: str = Field(min_length=1)
    cost_model_id: str = Field(min_length=1)
    declared_at: datetime
    evaluation_starts_at: datetime
    outcome_based_selection: Literal[False] = False

    @model_validator(mode="after")
    def _declared_before_evaluation(self) -> Self:
        if self.declared_at.tzinfo is None or self.evaluation_starts_at.tzinfo is None:
            raise ValueError("comparison times must be timezone-aware")
        if self.declared_at > self.evaluation_starts_at:
            raise ValueError("best-setup comparison must be declared before evaluation")
        if self.all_qualified_trial_id == self.best_only_trial_id:
            raise ValueError("all-qualified and best-only runs require distinct trial IDs")
        return self


class OrderKind(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class SameBarPolicy(StrEnum):
    PROHIBITED = "PROHIBITED"
    PROVEN_TICK_SEQUENCE_ONLY = "PROVEN_TICK_SEQUENCE_ONLY"


class ExecutionEvidenceKind(StrEnum):
    BAR_OHLC = "BAR_OHLC"
    QUOTE = "QUOTE"
    TRADE_TICK = "TRADE_TICK"


class ResearchExecutionPolicy(_Frozen):
    policy_id: str = Field(min_length=1)
    timing: Literal["NEXT_VALID_EXECUTABLE_EVENT"] = "NEXT_VALID_EXECUTABLE_EVENT"
    same_bar_policy: SameBarPolicy = SameBarPolicy.PROHIBITED
    market_fill_rule_id: str = Field(min_length=1)
    limit_fill_rule_id: str = Field(min_length=1)
    stop_fill_rule_id: str = Field(min_length=1)
    partial_fill_rule_id: str = Field(min_length=1)
    cost_model_id: str = Field(min_length=1)


class ResearchOrderIntent(_Frozen):
    intent_id: str = Field(min_length=1)
    approved_plan: ApprovedTradePlan
    kind: OrderKind
    eligible_after: datetime
    signal_bar_id: str = Field(min_length=1)
    confirmation_sequence: int | None = Field(default=None, ge=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _order_shape_and_timing(self) -> Self:
        if self.eligible_after.tzinfo is None:
            raise ValueError("order eligibility time must be timezone-aware")
        if self.eligible_after < self.approved_plan.proposal.confirmed_at:
            raise ValueError("an order cannot become eligible before signal confirmation")
        if self.kind is OrderKind.LIMIT and self.limit_price is None:
            raise ValueError("limit intent requires limit_price")
        if self.kind is OrderKind.STOP and self.stop_price is None:
            raise ValueError("stop intent requires stop_price")
        if self.kind is OrderKind.MARKET and (
            self.limit_price is not None or self.stop_price is not None
        ):
            raise ValueError("market intent cannot carry a limit or stop trigger price")
        return self


class ExecutionCandidate(_Frozen):
    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    event_time: datetime
    bar_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    executable: bool
    evidence_kind: ExecutionEvidenceKind

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.event_time.tzinfo is None:
            raise ValueError("execution event time must be timezone-aware")
        return self


class ExecutionEligibility(_Frozen):
    eligible: bool
    event_id: str
    reasons: tuple[str, ...]


class DataArrivalMode(StrEnum):
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    LIVE_ARRIVING = "LIVE_ARRIVING"


class EvaluationRun(_Frozen):
    run_id: str = Field(min_length=1)
    mode: EvaluationMode
    data_arrival: DataArrivalMode
    started_at: datetime
    ended_at: datetime | None = None
    hindsight_recomputed: Literal[False] = False

    @model_validator(mode="after")
    def _arrival_matches_mode(self) -> Self:
        if self.started_at.tzinfo is None or (
            self.ended_at is not None and self.ended_at.tzinfo is None
        ):
            raise ValueError("evaluation-run times must be timezone-aware")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("evaluation run end precedes start")
        live_modes = {
            EvaluationMode.FORWARD_TEST,
            EvaluationMode.PAPER_TRADING,
            EvaluationMode.OPERATIONAL_PROVING,
        }
        if self.mode in live_modes and self.data_arrival is not DataArrivalMode.LIVE_ARRIVING:
            raise ValueError("forward and paper evidence must use live-arriving data")
        if (
            self.mode not in live_modes
            and self.data_arrival is not DataArrivalMode.HISTORICAL_REPLAY
        ):
            raise ValueError("historical evidence must use historical replay data")
        return self


class PaperDecisionRecord(_Frozen):
    record_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    risk_decision_id: str = Field(min_length=1)
    approved_plan_id: str | None
    signal_event_time: datetime
    confirmed_at: datetime
    order_created_at: datetime | None
    fill_at: datetime | None
    slippage_points: Decimal | None = Field(default=None, ge=0)
    post_decision_mae_r: Decimal = Field(ge=0)
    post_decision_mfe_r: Decimal = Field(ge=0)
    management_action_ids: tuple[str, ...]
    rejection_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def _causal_timeline(self) -> Self:
        times = (self.signal_event_time, self.confirmed_at, self.order_created_at, self.fill_at)
        if any(value is not None and value.tzinfo is None for value in times):
            raise ValueError("paper-decision times must be timezone-aware")
        if self.confirmed_at < self.signal_event_time:
            raise ValueError("paper confirmation cannot precede signal event")
        if self.order_created_at is not None and self.order_created_at < self.confirmed_at:
            raise ValueError("paper order cannot precede confirmation")
        if self.fill_at is not None and (
            self.order_created_at is None or self.fill_at < self.order_created_at
        ):
            raise ValueError("paper fill requires and cannot precede an order")
        if self.fill_at is not None and self.slippage_points is None:
            raise ValueError("paper fill requires recorded slippage")
        if self.fill_at is not None and self.approved_plan_id is None:
            raise ValueError("paper fill requires an approved plan")
        if self.approved_plan_id is None and not self.rejection_reasons:
            raise ValueError("a rejected paper setup must retain rejection reasons")
        return self


class AcceptanceState(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BACKTEST_EVIDENCE = "BACKTEST_EVIDENCE"
    WALK_FORWARD_EVIDENCE = "WALK_FORWARD_EVIDENCE"
    HOLDOUT_EVIDENCE = "HOLDOUT_EVIDENCE"
    PAPER_FORWARD_EVIDENCE = "PAPER_FORWARD_EVIDENCE"
    LIVE_CANDIDATE = "LIVE_CANDIDATE"


class ThresholdStatus(StrEnum):
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATED_FROM_RESEARCH = "CALIBRATED_FROM_RESEARCH"
    INDEPENDENTLY_REVIEWED = "INDEPENDENTLY_REVIEWED"


class EvidenceDataClass(StrEnum):
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    REAL_RAW_CONTRACT = "REAL_RAW_CONTRACT"


class EvidenceArtifact(_Frozen):
    evidence_id: str = Field(min_length=1)
    mode: EvaluationMode
    trial_id: str = Field(min_length=1)
    strategy: StrategyFamily
    data_class: EvidenceDataClass
    market_data_validator_passed: bool
    provenance_checksum_passed: bool
    risk_route_verified: bool
    costs_included: bool
    trial_registry_complete: bool
    failed_trials_retained: bool
    parameter_search_logged: bool
    robustness_verdict: RobustnessVerdict
    holdout_state: HoldoutState | None = None
    live_arriving_data: bool = False
    operational_controls_verified: bool = False


class AcceptanceDecision(_Frozen):
    requested_state: AcceptanceState
    granted_state: AcceptanceState = AcceptanceState.RESEARCH_ONLY
    threshold_status: ThresholdStatus = ThresholdStatus.UNCALIBRATED
    evidence_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    live_orders_enabled: Literal[False] = False

    @model_validator(mode="after")
    def _fail_closed_shape(self) -> Self:
        if self.granted_state is not AcceptanceState.RESEARCH_ONLY and self.reasons:
            raise ValueError("a granted evidence state cannot carry unmet prerequisites")
        if (
            self.granted_state is not AcceptanceState.RESEARCH_ONLY
            and self.threshold_status is ThresholdStatus.UNCALIBRATED
        ):
            raise ValueError("uncalibrated thresholds cannot grant an evidence state")
        if (
            self.granted_state is AcceptanceState.LIVE_CANDIDATE
            and self.threshold_status is not ThresholdStatus.INDEPENDENTLY_REVIEWED
        ):
            raise ValueError("LIVE_CANDIDATE requires independently reviewed thresholds")
        if self.granted_state not in {AcceptanceState.RESEARCH_ONLY, self.requested_state}:
            raise ValueError(
                "an acceptance decision may only grant the requested state or fail closed"
            )
        return self
