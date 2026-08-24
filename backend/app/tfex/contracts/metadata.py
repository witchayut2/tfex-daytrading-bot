"""Resolved contract identity and status (`CLAUDE_TFEX.md` section 5).

:class:`ParsedContractSymbol` says which contract a string names.
:class:`TfexContractSymbol` says what that contract *is* at a point in time — when it
expires, how long it has left, and whether it may be traded.

The gap between the two is calendar and registry data, and section 5 is emphatic that the
gap must not be closed by guessing: a contract whose expiry cannot be resolved is
``UNKNOWN``, and ``UNKNOWN`` is never tradable.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.calendar.models import ContractExpiry, LastTradingDaySource
from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.contracts.symbol_parser import ParsedContractSymbol, parse_symbol
from app.tfex.errors import CalendarError

__all__ = ["ContractResolver", "ContractStatus", "TfexContractSymbol"]


class ContractStatus(StrEnum):
    """Lifecycle status from section 5."""

    PRE_LISTED = "PRE_LISTED"
    ACTIVE = "ACTIVE"
    ROLL_CANDIDATE = "ROLL_CANDIDATE"
    """Close enough to expiry that the roll policy should be considering the next month."""

    LAST_TRADING_DAY = "LAST_TRADING_DAY"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    """Expiry could not be resolved from imported data. Never tradable."""


#: Statuses in which a *new* position may be opened, subject to every other gate.
_OPENABLE_STATUSES = frozenset({ContractStatus.ACTIVE, ContractStatus.ROLL_CANDIDATE})


class TfexContractSymbol(BaseModel):
    """A contract, resolved as far as the available data allows, at a stated instant.

    Every field that depends on data the platform might not have is optional, and its
    absence is reflected in ``status``. There is no "probably fine" state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_symbol: str
    root: str
    month_code: str = Field(min_length=1, max_length=1)
    year_2digit: int = Field(ge=0, le=99)
    contract_year: int
    contract_month: int = Field(ge=1, le=12)

    expiry_date: date | None = None
    last_trading_date: date | None = None
    last_trading_timestamp: datetime | None = None
    expiry_source: LastTradingDaySource | None = None

    status: ContractStatus = ContractStatus.UNKNOWN
    is_near_month: bool = False
    """Set by the registry, which is the only component allowed to rank contracts."""

    days_to_expiry: int | None = None
    """Calendar days until the last trading day. Negative once past it."""

    trading_days_to_expiry: int | None = None
    """Trading days until the last trading day. This is what the roll and expiry gates use:
    it is holiday-aware and never more optimistic than the calendar-day count."""

    listing_date: date | None = None
    metadata_version: str
    as_of: datetime | None = None
    resolution_note: str | None = None

    @model_validator(mode="after")
    def _status_is_supported_by_data(self) -> Self:
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.last_trading_timestamp is not None and self.last_trading_timestamp.tzinfo is None:
            raise ValueError("last_trading_timestamp must be timezone-aware")
        if self.status is not ContractStatus.UNKNOWN and self.last_trading_timestamp is None:
            raise ValueError(
                f"status {self.status} claims knowledge of the contract lifecycle, but no "
                f"last_trading_timestamp was resolved"
            )
        return self

    @property
    def normalized_symbol(self) -> str:
        return f"{self.root}{self.month_code}{self.year_2digit:02d}"

    @property
    def contract_month_key(self) -> tuple[int, int]:
        return self.contract_year, self.contract_month

    @property
    def can_open_new_position(self) -> bool:
        """Contract-level permission only. Session, margin and risk gates still apply."""
        return self.status in _OPENABLE_STATUSES

    def __str__(self) -> str:
        return self.normalized_symbol


class ContractResolver:
    """Turns parsed symbols into resolved contracts using the trading calendar."""

    def __init__(self, config: TfexConfig, calendar: TradingCalendar) -> None:
        self._config = config
        self._calendar = calendar

    def parse(self, raw: str, *, reference_date: date) -> ParsedContractSymbol:
        return parse_symbol(raw, config=self._config, reference_date=reference_date)

    def resolve(
        self,
        parsed: ParsedContractSymbol,
        *,
        as_of: datetime,
        listing_date: date | None = None,
        is_near_month: bool = False,
    ) -> TfexContractSymbol:
        """Resolve ``parsed`` against the calendar as at ``as_of``.

        Returns an ``UNKNOWN``-status contract when the calendar cannot answer, rather than
        raising: an unresolvable contract is a normal condition for a registry that has been
        handed a symbol from an unimported year, and ``UNKNOWN`` is already untradable.
        """
        local = self._calendar.to_market_time(as_of)
        try:
            expiry = self._calendar.contract_expiry(
                parsed.contract_year, parsed.contract_month, resolved_at=local
            )
        except CalendarError as exc:
            return self._unresolved(parsed, as_of=local, note=str(exc))

        calendar_days, trading_days = self._calendar.days_to_expiry(local.date(), expiry)
        status = self._status(
            expiry=expiry,
            as_of=local,
            trading_days_to_expiry=trading_days,
            listing_date=listing_date,
        )

        return TfexContractSymbol(
            raw_symbol=parsed.raw,
            root=parsed.root,
            month_code=parsed.month_code,
            year_2digit=parsed.year_2digit,
            contract_year=parsed.contract_year,
            contract_month=parsed.contract_month,
            expiry_date=expiry.expiry_date,
            last_trading_date=expiry.last_trading_date,
            last_trading_timestamp=expiry.last_trading_timestamp,
            expiry_source=expiry.source,
            status=status,
            is_near_month=is_near_month,
            days_to_expiry=calendar_days,
            trading_days_to_expiry=trading_days,
            listing_date=listing_date,
            metadata_version=expiry.calendar_version,
            as_of=local,
        )

    def resolve_symbol(
        self,
        raw: str,
        *,
        as_of: datetime,
        listing_date: date | None = None,
        is_near_month: bool = False,
    ) -> TfexContractSymbol:
        """Parse and resolve in one step, using ``as_of`` as the parse reference date."""
        local = self._calendar.to_market_time(as_of)
        parsed = self.parse(raw, reference_date=local.date())
        return self.resolve(
            parsed, as_of=local, listing_date=listing_date, is_near_month=is_near_month
        )

    # --- internals --------------------------------------------------------------------

    def _status(
        self,
        *,
        expiry: ContractExpiry,
        as_of: datetime,
        trading_days_to_expiry: int,
        listing_date: date | None,
    ) -> ContractStatus:
        if listing_date is not None and as_of.date() < listing_date:
            return ContractStatus.PRE_LISTED
        if as_of >= expiry.last_trading_timestamp:
            # At or after cessation the contract is done. ">=" not ">": 16:30:00 sharp is
            # already past the point where a new order could be worked.
            return ContractStatus.EXPIRED
        if as_of.date() > expiry.last_trading_date:
            return ContractStatus.EXPIRED
        if as_of.date() == expiry.last_trading_date:
            return ContractStatus.LAST_TRADING_DAY
        if trading_days_to_expiry <= self._config.roll.minimum_days_before_expiry:
            return ContractStatus.ROLL_CANDIDATE
        return ContractStatus.ACTIVE

    def _unresolved(
        self, parsed: ParsedContractSymbol, *, as_of: datetime, note: str
    ) -> TfexContractSymbol:
        return TfexContractSymbol(
            raw_symbol=parsed.raw,
            root=parsed.root,
            month_code=parsed.month_code,
            year_2digit=parsed.year_2digit,
            contract_year=parsed.contract_year,
            contract_month=parsed.contract_month,
            status=ContractStatus.UNKNOWN,
            metadata_version=f"{self._config.metadata.version}/unresolved",
            as_of=as_of,
            resolution_note=note,
        )
