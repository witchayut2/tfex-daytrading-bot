"""TFEX platform configuration.

`CLAUDE_TFEX.md` section 3 is explicit: contract facts "must be represented as
configuration and metadata, not scattered constants". Everything in this module is loaded
from YAML, validated on load, and frozen afterwards.

Two classes of value live here and must not be confused:

* **Exchange facts** (point value, tick size, session boundaries). Static, but still
  configuration so that an exchange change is a data edit rather than a code edit.
* **Research defaults** (roll thresholds, entry cutoffs, safety buffers). These are *our*
  choices, not exchange rules, and section 7 says so explicitly. Fields carrying research
  defaults are marked in their docstrings.

Dynamic values (margin rates, commissions, holidays, last trading dates) are deliberately
absent: they are fetched or imported with provenance, never configured as constants.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from app.tfex.costs.models import CostScenario, FeeProvenanceStatus
from app.tfex.errors import ConfigurationError, LiveTradingDisabledError

__all__ = [
    "CommissionConfig",
    "ContractConfig",
    "CostsConfig",
    "ExchangeFeeConfig",
    "ExpiryConfig",
    "MarginConfig",
    "MarketConfig",
    "MetadataConfig",
    "RollConfig",
    "SessionsConfig",
    "SymbolConfig",
    "TfexConfig",
    "TimeBucketStatisticsConfig",
    "TimeWindow",
    "TradingConfig",
    "default_config",
    "load_config",
]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tfex.yaml"


def _decimal_from_scalar(value: Any) -> Any:
    """Route floats through ``str`` so YAML ``0.1`` does not become ``0.1000000000000000055``.

    Tick arithmetic decides position size; binary float error has no place in it.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    return value


Money = Annotated[Decimal, BeforeValidator(_decimal_from_scalar)]


class _Frozen(BaseModel):
    """Immutable, typo-intolerant base. ``extra='forbid'`` turns a misspelt key into an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TimeWindow(_Frozen):
    """A half-open local-time interval ``[start, end)``.

    Half-open is the whole point: 12:30:00 belongs to the midday break, not to the morning
    session, and 16:55:00 is post-close. Every boundary comparison in the platform follows
    this rule so that a single instant never belongs to two sequential phases.
    """

    start: time
    end: time

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError(f"window start {self.start} must be before end {self.end}")
        return self

    def contains(self, value: time) -> bool:
        return self.start <= value < self.end


class MarketConfig(_Frozen):
    exchange: Literal["TFEX"] = "TFEX"
    timezone: str = "Asia/Bangkok"
    instrument_family: str = "SET50_INDEX_FUTURES"
    symbol_root: str = "S50"
    currency: Literal["THB"] = "THB"


class ContractConfig(_Frozen):
    """Static contract terms from the official SET50 Index Futures specification."""

    point_value_thb: Money = Decimal("200")
    tick_size_points: Money = Decimal("0.1")
    tick_value_thb: Money = Decimal("20")
    settlement_type: Literal["CASH"] = "CASH"
    price_limit_reference: Literal["LATEST_SETTLEMENT"] = "LATEST_SETTLEMENT"
    price_limit_percent: Money = Decimal("30")

    @model_validator(mode="after")
    def _tick_arithmetic_is_consistent(self) -> Self:
        """0.1 point x THB 200/point must equal the THB 20 tick value.

        A typo in any one of the three silently mis-sizes every position, so it is caught
        at load time rather than discovered in a P&L reconciliation.
        """
        derived = self.tick_size_points * self.point_value_thb
        if derived != self.tick_value_thb:
            raise ValueError(
                f"tick_size_points ({self.tick_size_points}) x point_value_thb "
                f"({self.point_value_thb}) = {derived}, which contradicts tick_value_thb "
                f"({self.tick_value_thb})"
            )
        return self


class SymbolConfig(_Frozen):
    """Rules the contract-symbol parser enforces."""

    root: str = "S50"
    year_digits: Literal[2] = 2
    century_pivot_years: int = Field(default=50, ge=1, le=99)
    """Half-width of the two-digit-year resolution window around the reference year.

    A symbol's ``25`` is resolved to the candidate year within
    ``[reference_year - pivot, reference_year + pivot]``. Never resolved against "now".
    """

    minimum_contract_year: int = Field(default=2006, ge=1900)
    """Research default. SET50 Index Futures were the first TFEX product; verify the exact
    listing history against the exchange before relying on this to reject old symbols."""

    maximum_years_ahead: int = Field(default=3, ge=1)
    """Listed months span under a year ahead; 3 leaves room without accepting nonsense."""


class SessionsConfig(_Frozen):
    """Regular-day session boundaries (section 9).

    The midday break and the afternoon pre-open overlap on purpose. Section 9 requires the
    overlap to be modelled explicitly instead of being flattened into one phase, so the
    validator below *asserts* the overlap rather than rejecting it.
    """

    timezone: str = "Asia/Bangkok"
    morning_preopen: TimeWindow
    morning: TimeWindow
    midday_break: TimeWindow
    afternoon_preopen: TimeWindow
    afternoon: TimeWindow

    entry_cutoff: time = time(16, 30)
    """Research default: no new positions after this time on a regular day."""

    end_of_day_flatten_minutes_before_close: int = Field(default=5, ge=0, le=120)
    """Research default (section 24: end-of-day flatten is enabled by default)."""

    @model_validator(mode="after")
    def _phases_chain_correctly(self) -> Self:
        if self.morning_preopen.end != self.morning.start:
            raise ValueError("morning pre-open must end exactly when the morning session opens")
        if self.morning.end != self.midday_break.start:
            raise ValueError("the midday break must start exactly when the morning session closes")
        if self.midday_break.end != self.afternoon.start:
            raise ValueError("the afternoon session must open exactly when the midday break ends")
        if self.afternoon_preopen.end != self.afternoon.start:
            raise ValueError("afternoon pre-open must end exactly when the afternoon session opens")
        if not self.midday_break.start <= self.afternoon_preopen.start < self.midday_break.end:
            raise ValueError(
                "afternoon pre-open must begin inside the midday break; section 9 relies on "
                "this overlap being real"
            )
        if not self.morning.contains(self.entry_cutoff) and not self.afternoon.contains(
            self.entry_cutoff
        ):
            raise ValueError("entry_cutoff must fall inside a continuous trading session")
        return self


class ExpiryConfig(_Frozen):
    """Last-trading-day behaviour (sections 3 and 24)."""

    last_trading_day_cessation_time: time = time(16, 30)
    """Exchange fact: trading ceases at 16:30 on the last trading day."""

    closing_window_minutes: int = Field(default=15, ge=0, le=240)
    """Research default. Width of ``LAST_TRADING_DAY_CLOSING_WINDOW`` before cessation."""

    require_published_last_trading_day: bool = False
    """When true, a contract whose last trading day was derived from the calendar rule
    rather than published by the exchange is not eligible for orders."""


class RollConfig(_Frozen):
    """Section 7 roll policy. Every value here is a research default, not an exchange rule."""

    enabled: bool = True
    minimum_days_before_expiry: int = Field(default=2, ge=0)
    """Counted in **trading** days, not calendar days. Section 5/7 leave the unit unstated;
    trading days are holiday-aware and strictly more conservative."""

    volume_ratio_threshold: Money = Decimal("1.20")
    confirmation_sessions: int = Field(default=1, ge=1)
    prevent_new_positions_on_last_trading_day_after: time = time(15, 45)
    force_flatten_before_last_trade_stop_minutes: int = Field(default=15, ge=0, le=240)


class ExchangeFeeConfig(_Frozen):
    """The exchange fee, kept strictly separate from what a broker actually charges.

    The contract specification publishes THB 7 per contract per side as a **maximum**. That
    number lives in ``cap_*`` and is never a production charge. ``actual_*`` stays unset —
    and therefore ``UNKNOWN`` — until someone verifies the rate for a specific account.
    """

    cap_thb_per_contract_per_side: Money = Decimal("7")
    cap_source: str = "SET50 Index Futures contract specification (maximum)"
    actual_thb_per_contract_per_side: Money | None = None
    actual_status: FeeProvenanceStatus = FeeProvenanceStatus.UNKNOWN
    actual_source: str | None = None

    @model_validator(mode="after")
    def _actual_is_supported(self) -> Self:
        if self.actual_status is FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP:
            raise ValueError(
                "actual_status may not be VERIFIED_EXCHANGE_CAP: a cap is not an actual "
                "charged fee. Leave actual_* unset until the broker's rate is verified."
            )
        if self.actual_status is not FeeProvenanceStatus.UNKNOWN and (
            self.actual_thb_per_contract_per_side is None
        ):
            raise ValueError(
                f"actual_status {self.actual_status} claims knowledge but no "
                f"actual_thb_per_contract_per_side was configured"
            )
        return self


class CommissionConfig(_Frozen):
    """Broker commission. Negotiable per account, therefore unknown until configured."""

    thb_per_contract_per_side: Money | None = None
    status: FeeProvenanceStatus = FeeProvenanceStatus.UNKNOWN
    minimum_thb_per_order: Money | None = None
    vat_percent: Money = Decimal("7")
    source: str | None = None

    @model_validator(mode="after")
    def _value_supports_status(self) -> Self:
        if self.status is FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP:
            raise ValueError("a broker commission cannot have exchange-cap provenance")
        if self.status is not FeeProvenanceStatus.UNKNOWN and (
            self.thb_per_contract_per_side is None
        ):
            raise ValueError(
                f"commission status {self.status} claims knowledge but no rate was configured"
            )
        return self


class CostsConfig(_Frozen):
    """Section 23 cost model inputs, each carrying its own provenance."""

    exchange_fee: ExchangeFeeConfig = ExchangeFeeConfig()
    commission: CommissionConfig = CommissionConfig()
    research_scenario: CostScenario = CostScenario.CONSERVATIVE_STRESS_TEST
    """Which labelled scenario research runs use by default. The conservative stress test is
    the only place the exchange cap may legitimately be applied."""


class MarginConfig(_Frozen):
    """Section 22. The rates themselves are dynamic and live in the margin provider (TFEX-4)."""

    free_equity_buffer_multiplier: Money = Decimal("2.0")
    reject_when_stale: bool = True


class MetadataConfig(_Frozen):
    """Freshness policy for imported exchange metadata (section 2)."""

    version: str = "1"
    holiday_data_stale_after_days: int = Field(default=180, ge=1)
    require_verified_sources: bool = False
    """Research default false so that replay work can proceed on unverified imports.
    Order-capable modes set this true; section 28 forbids trading on stale metadata."""


class TimeBucketStatisticsConfig(_Frozen):
    """Section 20 minimum sample sizes before a time-bucket statistic may be reported."""

    minimum_trades: int = Field(default=50, ge=1)
    minimum_sessions: int = Field(default=30, ge=1)


class TradingConfig(_Frozen):
    """Trading mode. There is no live order route in this build."""

    mode: str = "PAPER"
    live_orders_enabled: bool = False

    @model_validator(mode="after")
    def _no_live_route(self) -> Self:
        # Deliberately typed as plain bool/str rather than Literal: a YAML file that sets
        # `live_orders_enabled: true` must fail loudly with this error, not with a schema
        # type message that reads like a typo.
        if self.live_orders_enabled or self.mode != "PAPER":
            raise LiveTradingDisabledError(
                "live order submission is not implemented and may not be enabled; see "
                "CLAUDE_TFEX.md section 32"
            )
        return self


class TfexConfig(_Frozen):
    """Root configuration object."""

    market: MarketConfig = MarketConfig()
    contract: ContractConfig = ContractConfig()
    symbol: SymbolConfig = SymbolConfig()
    sessions: SessionsConfig
    expiry: ExpiryConfig = ExpiryConfig()
    roll: RollConfig = RollConfig()
    costs: CostsConfig = CostsConfig()
    margin: MarginConfig = MarginConfig()
    metadata: MetadataConfig = MetadataConfig()
    time_bucket_statistics: TimeBucketStatisticsConfig = TimeBucketStatisticsConfig()
    trading: TradingConfig = TradingConfig()

    @model_validator(mode="after")
    def _timezones_agree(self) -> Self:
        if self.market.timezone != self.sessions.timezone:
            raise ValueError(
                f"market.timezone ({self.market.timezone}) and sessions.timezone "
                f"({self.sessions.timezone}) must be the same zone"
            )
        return self

    @model_validator(mode="after")
    def _symbol_root_matches_market(self) -> Self:
        if self.symbol.root != self.market.symbol_root:
            raise ValueError("symbol.root and market.symbol_root must be the same ticker root")
        return self

    @model_validator(mode="after")
    def _last_trading_day_cutoffs_are_ordered(self) -> Self:
        cutoff = self.roll.prevent_new_positions_on_last_trading_day_after
        cessation = self.expiry.last_trading_day_cessation_time
        if cutoff >= cessation:
            raise ValueError(
                f"new-position cutoff on the last trading day ({cutoff}) must be before "
                f"cessation ({cessation})"
            )
        return self


def default_config() -> TfexConfig:
    """Configuration with regular TFEX session boundaries and documented research defaults."""
    return TfexConfig(
        sessions=SessionsConfig(
            morning_preopen=TimeWindow(start=time(9, 15), end=time(9, 45)),
            morning=TimeWindow(start=time(9, 45), end=time(12, 30)),
            midday_break=TimeWindow(start=time(12, 30), end=time(13, 45)),
            afternoon_preopen=TimeWindow(start=time(13, 15), end=time(13, 45)),
            afternoon=TimeWindow(start=time(13, 45), end=time(16, 55)),
        )
    )


def load_config(path: Path | str | None = None) -> TfexConfig:
    """Load and validate ``config/tfex.yaml``.

    Raises:
        ConfigurationError: the file is missing, is not a mapping, or fails validation.
    """
    resolved = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw_text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read TFEX configuration at {resolved}: {exc}") from exc

    loaded = yaml.safe_load(raw_text)
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"TFEX configuration at {resolved} must be a YAML mapping")

    try:
        return TfexConfig.model_validate(loaded)
    except LiveTradingDisabledError:
        raise
    except ValidationError as exc:
        raise ConfigurationError(f"invalid TFEX configuration at {resolved}:\n{exc}") from exc
