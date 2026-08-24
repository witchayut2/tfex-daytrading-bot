"""The contract registry (`CLAUDE_TFEX.md` section 6).

Section 6 makes the registry the single source of truth for near-month selection, expiry
safety, continuous-series construction, roll recommendations and order-symbol validation,
and then states the rule that gives the registry its point:

> No strategy may select a contract directly. It must request an eligible contract from the
> registry.

Two design choices follow from that:

**Status is never cached.** A record stores what does not change (which contract it is, when
it was listed, what the feed last reported) and the registry resolves status, days to expiry
and eligibility *for a given instant* on every read. A cached ``ACTIVE`` is a repaint waiting
to happen — it would let a backtest see a contract as tradable on a day it was not.

**Ineligibility is loud.** Every rejection carries the reasons that produced it, so the audit
log answers "why was there no trade?" without a re-run.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.contracts.metadata import ContractResolver, ContractStatus, TfexContractSymbol
from app.tfex.contracts.roll import (
    ContractLiquidity,
    RollDecision,
    RollPolicy,
    RollStateMachine,
)
from app.tfex.contracts.symbol_parser import ParsedContractSymbol
from app.tfex.errors import (
    ContractNotEligibleError,
    ContractNotFoundError,
    NoEligibleContractError,
)
from app.tfex.provenance import Provenance

__all__ = ["ContractEligibility", "ContractMarketState", "ContractRecord", "ContractRegistry"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContractMarketState(_Frozen):
    """Latest feed-reported market data for one contract (section 6).

    Every field is optional because feeds differ. Missing data must degrade a decision, not
    be filled in with a plausible number.
    """

    session_date: date | None = None
    daily_volume: int | None = Field(default=None, ge=0)
    rolling_volume: int | None = Field(default=None, ge=0)
    open_interest: int | None = Field(default=None, ge=0)
    latest_settlement_price: Decimal | None = Field(default=None, gt=0)
    bid_ask_spread_points: Decimal | None = Field(default=None, ge=0)
    updated_at: datetime | None = None


class ContractRecord(_Frozen):
    """A listed contract as the registry knows it.

    Holds only what does not depend on the current time. Anything time-dependent — status,
    days to expiry, eligibility — is computed on read.
    """

    normalized_symbol: str
    parsed: ParsedContractSymbol
    listing_date: date | None = None
    market_state: ContractMarketState = ContractMarketState()
    margin_metadata_ref: str | None = None
    """Key into the margin provider (TFEX-4). The registry does not hold margin numbers."""

    provenance: Provenance
    source_version: str = "1"

    @property
    def contract_month_key(self) -> tuple[int, int]:
        return self.parsed.contract_month_key


class ContractEligibility(_Frozen):
    """Whether a contract may be traded at an instant, and why not when it may not."""

    contract: TfexContractSymbol
    eligible: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.eligible


class ContractRegistry:
    """The single source of truth for contract identity and eligibility."""

    def __init__(
        self,
        config: TfexConfig,
        calendar: TradingCalendar,
        *,
        records: Iterable[ContractRecord] = (),
    ) -> None:
        self._config = config
        self._calendar = calendar
        self._resolver = ContractResolver(config, calendar)
        self._policy = RollPolicy(config)
        self._roll = RollStateMachine(config)
        self._records: dict[str, ContractRecord] = {}
        for record in records:
            self.upsert(record)

    # --- storage ----------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[ContractRecord]:
        return iter(sorted(self._records.values(), key=lambda r: r.contract_month_key))

    def __contains__(self, symbol: object) -> bool:
        return isinstance(symbol, str) and symbol.strip().upper() in self._records

    def upsert(self, record: ContractRecord) -> ContractRecord:
        self._records[record.normalized_symbol] = record
        return record

    def register_symbol(
        self,
        raw_symbol: str,
        *,
        reference_date: date,
        provenance: Provenance,
        listing_date: date | None = None,
        market_state: ContractMarketState | None = None,
        source_version: str = "1",
    ) -> ContractRecord:
        """Parse ``raw_symbol`` and add it to the registry.

        Raises:
            SymbolParseError: the symbol is malformed. A registry that accepts junk symbols
                is worse than no registry.
        """
        parsed = self._resolver.parse(raw_symbol, reference_date=reference_date)
        return self.upsert(
            ContractRecord(
                normalized_symbol=parsed.normalized,
                parsed=parsed,
                listing_date=listing_date,
                market_state=market_state or ContractMarketState(),
                provenance=provenance,
                source_version=source_version,
            )
        )

    def update_market_state(self, symbol: str, market_state: ContractMarketState) -> ContractRecord:
        record = self.record(symbol)
        return self.upsert(record.model_copy(update={"market_state": market_state}))

    def record(self, symbol: str) -> ContractRecord:
        key = symbol.strip().upper()
        try:
            return self._records[key]
        except KeyError:
            raise ContractNotFoundError(
                f"no contract registered under {symbol!r}; the registry holds "
                f"{sorted(self._records)}"
            ) from None

    # --- resolution -------------------------------------------------------------------

    def resolve(self, symbol: str, *, as_of: datetime) -> TfexContractSymbol:
        """Resolve one registered contract at ``as_of``."""
        record = self.record(symbol)
        return self._resolve_record(record, as_of=as_of)

    def resolve_all(self, *, as_of: datetime) -> tuple[TfexContractSymbol, ...]:
        return tuple(self._resolve_record(record, as_of=as_of) for record in self)

    def _resolve_record(self, record: ContractRecord, *, as_of: datetime) -> TfexContractSymbol:
        return self._resolver.resolve(record.parsed, as_of=as_of, listing_date=record.listing_date)

    # --- eligibility ------------------------------------------------------------------

    def eligibility(self, symbol: str, *, as_of: datetime) -> ContractEligibility:
        """Full eligibility check for one contract: status, expiry cutoff and data freshness."""
        record = self.record(symbol)
        contract = self._resolve_record(record, as_of=as_of)
        reasons: list[str] = []

        if not contract.can_open_new_position:
            reasons.append(f"{contract.normalized_symbol} status is {contract.status}")
        if (
            self._config.expiry.require_published_last_trading_day
            and contract.expiry_source is not None
            and contract.expiry_source.value != "EXCHANGE_PUBLISHED"
        ):
            reasons.append(
                f"last trading day for {contract.normalized_symbol} came from "
                f"{contract.expiry_source}, but published dates are required"
            )
        if contract.trading_days_to_expiry is None:
            reasons.append(f"{contract.normalized_symbol} has no resolved time to expiry")
        elif contract.trading_days_to_expiry < self._config.roll.minimum_days_before_expiry:
            reasons.append(
                f"{contract.normalized_symbol} has {contract.trading_days_to_expiry} trading "
                f"day(s) to expiry, below the cutoff of "
                f"{self._config.roll.minimum_days_before_expiry}"
            )
        try:
            record.provenance.require_usable(
                as_of, require_verified=self._config.metadata.require_verified_sources
            )
        except Exception as exc:  # broad on purpose: the reason becomes a rejection reason
            reasons.append(f"contract metadata unusable: {exc}")

        return ContractEligibility(contract=contract, eligible=not reasons, reasons=tuple(reasons))

    def validate_order_symbol(self, symbol: str, *, as_of: datetime) -> TfexContractSymbol:
        """Section 6: order symbol validation.

        Raises:
            ContractNotEligibleError: the contract may not carry a new order at ``as_of``.
        """
        result = self.eligibility(symbol, as_of=as_of)
        if not result.eligible:
            raise ContractNotEligibleError(
                f"{symbol} is not eligible for orders at {as_of.isoformat()}: "
                + "; ".join(result.reasons)
            )
        return result.contract

    def eligible_contracts(self, *, as_of: datetime) -> tuple[TfexContractSymbol, ...]:
        """Every eligible contract at ``as_of``, nearest expiry first."""
        eligible = [
            result.contract
            for record in self
            if (result := self.eligibility(record.normalized_symbol, as_of=as_of)).eligible
        ]
        return tuple(sorted(eligible, key=_expiry_sort_key))

    # --- selection --------------------------------------------------------------------

    def request_eligible_contract(self, *, as_of: datetime) -> TfexContractSymbol:
        """The contract a strategy should trade at ``as_of``.

        Prefers the contract the roll state machine has settled on; falls back to the
        nearest eligible expiry. Never returns an ineligible contract, and never invents
        one.

        Raises:
            NoEligibleContractError: nothing in the registry may be traded right now.
        """
        candidates = self.eligible_contracts(as_of=as_of)
        if not candidates:
            raise NoEligibleContractError(
                f"no eligible SET50 futures contract at {as_of.isoformat()}; "
                f"{self._rejection_summary(as_of)}"
            )

        rolled = self._roll.current_symbol
        if rolled is not None:
            for index, candidate in enumerate(candidates):
                if candidate.normalized_symbol == rolled:
                    return candidate.model_copy(update={"is_near_month": index == 0})

        return candidates[0].model_copy(update={"is_near_month": True})

    def near_and_next(self, *, as_of: datetime) -> tuple[TfexContractSymbol, TfexContractSymbol]:
        """The two nearest listed contracts by expiry, eligible or not.

        Deliberately not filtered by eligibility: the roll machine has to *see* the near
        contract becoming ineligible in order to force a roll away from it.
        """
        resolved = sorted(
            (c for c in self.resolve_all(as_of=as_of) if c.status is not ContractStatus.EXPIRED),
            key=_expiry_sort_key,
        )
        if len(resolved) < 2:
            raise NoEligibleContractError(
                f"the registry holds {len(resolved)} unexpired contract(s) at "
                f"{as_of.isoformat()}; a roll comparison needs two"
            )
        return resolved[0], resolved[1]

    def liquidity_for(self, contract: TfexContractSymbol) -> ContractLiquidity:
        """Build the roll policy's input from the registry's stored market state."""
        state = self.record(contract.normalized_symbol).market_state
        return ContractLiquidity(
            symbol=contract.normalized_symbol,
            status=contract.status,
            trading_days_to_expiry=contract.trading_days_to_expiry,
            session_volume=state.daily_volume or 0,
            rolling_volume=state.rolling_volume,
            open_interest=state.open_interest,
            bid_ask_spread_points=state.bid_ask_spread_points,
        )

    def observe_roll_session(
        self,
        *,
        session_date: date,
        as_of: datetime,
        open_position_quantity: int = 0,
    ) -> RollDecision:
        """Run one session's roll evaluation and persist the decision (section 7.5)."""
        near, next_ = self.near_and_next(as_of=as_of)
        return self._roll.observe(
            session_date=session_date,
            decided_at=as_of,
            near=self.liquidity_for(near),
            next_=self.liquidity_for(next_),
            open_position_quantity=open_position_quantity,
        )

    @property
    def roll_history(self) -> tuple[RollDecision, ...]:
        return tuple(self._roll.history)

    @property
    def rolled_symbol(self) -> str | None:
        return self._roll.current_symbol

    # --- diagnostics ------------------------------------------------------------------

    def _rejection_summary(self, as_of: datetime) -> str:
        parts = []
        for record in self:
            result = self.eligibility(record.normalized_symbol, as_of=as_of)
            if not result.eligible:
                parts.append(f"{record.normalized_symbol}: {'; '.join(result.reasons)}")
        return " | ".join(parts) if parts else "the registry is empty"

    def status_report(self, *, as_of: datetime) -> tuple[dict[str, object], ...]:
        """Table-shaped view for the dashboard's contract panel (section 29)."""
        rows: list[dict[str, object]] = []
        for record in self:
            result = self.eligibility(record.normalized_symbol, as_of=as_of)
            contract = result.contract
            rows.append(
                {
                    "symbol": contract.normalized_symbol,
                    "status": contract.status.value,
                    "last_trading_date": contract.last_trading_date,
                    "expiry_source": contract.expiry_source,
                    "days_to_expiry": contract.days_to_expiry,
                    "trading_days_to_expiry": contract.trading_days_to_expiry,
                    "eligible": result.eligible,
                    "reasons": result.reasons,
                    "daily_volume": record.market_state.daily_volume,
                    "open_interest": record.market_state.open_interest,
                }
            )
        return tuple(rows)


def _expiry_sort_key(contract: TfexContractSymbol) -> tuple[int, int]:
    """Sort by contract month. Unresolved contracts sort last rather than first.

    An ``UNKNOWN`` contract must never win a "nearest expiry" comparison by having no date.
    """
    if contract.last_trading_date is None:
        return (1, 0)
    return (0, contract.last_trading_date.toordinal())
