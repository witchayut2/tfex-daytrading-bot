"""Calendar data models (`CLAUDE_TFEX.md` section 8).

The calendar is the foundation everything date-sensitive stands on: expiry, the roll gate,
session state, and therefore every entry and exit. Section 8 forbids deriving trading days
from weekdays alone, so these models describe *imported* official data — including the
provenance of that data and the approval trail for any manual override.
"""

from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.provenance import Provenance

__all__ = [
    "ApprovalStatus",
    "CalendarOverride",
    "CalendarOverrideKind",
    "ContractExpiry",
    "DayClassification",
    "Holiday",
    "HolidayCalendarYear",
    "HolidayType",
    "LastTradingDaySource",
    "PublishedContractDates",
    "ShortenedSession",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HolidayType(StrEnum):
    FULL_CLOSURE = "FULL_CLOSURE"
    """No trading at all."""

    SPECIAL_HOLIDAY = "SPECIAL_HOLIDAY"
    """Government- or exchange-announced extra closure, distinguished from the annual set
    because it is announced late and therefore invalidates cached calendars."""


class Holiday(_Frozen):
    holiday_date: date
    name: str
    holiday_type: HolidayType = HolidayType.FULL_CLOSURE
    note: str | None = None


class ShortenedSession(_Frozen):
    """An announced early close.

    Section 8 requires shortened sessions to be known; section 10 forbids inventing bars
    beyond a session close, so a day with an early close must never produce full-length
    trailing bars.
    """

    session_date: date
    morning_close: time | None = None
    afternoon_close: time | None = None
    reason: str
    note: str | None = None

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        if self.morning_close is None and self.afternoon_close is None:
            raise ValueError(
                "a shortened session must shorten something: set morning_close, "
                "afternoon_close, or both"
            )
        return self


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CalendarOverrideKind(StrEnum):
    ADD_HOLIDAY = "ADD_HOLIDAY"
    REMOVE_HOLIDAY = "REMOVE_HOLIDAY"
    SHORTEN_SESSION = "SHORTEN_SESSION"
    SET_LAST_TRADING_DAY = "SET_LAST_TRADING_DAY"


class CalendarOverride(_Frozen):
    """A manual administrative correction to imported calendar data (section 8).

    Only ``APPROVED`` overrides take effect. A pending override is a request, not a fact,
    and the calendar ignores it — an unreviewed edit must never change trading behaviour.
    """

    kind: CalendarOverrideKind
    operator: str
    reason: str
    source: str
    created_at: datetime
    effective_date: date
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None

    target_date: date | None = None
    holiday_name: str | None = None
    morning_close: time | None = None
    afternoon_close: time | None = None
    contract_year: int | None = None
    contract_month: int | None = Field(default=None, ge=1, le=12)
    last_trading_date: date | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Self:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.approved_at is not None and self.approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")

        match self.kind:
            case CalendarOverrideKind.ADD_HOLIDAY:
                if self.target_date is None or not self.holiday_name:
                    raise ValueError("ADD_HOLIDAY requires target_date and holiday_name")
            case CalendarOverrideKind.REMOVE_HOLIDAY:
                if self.target_date is None:
                    raise ValueError("REMOVE_HOLIDAY requires target_date")
            case CalendarOverrideKind.SHORTEN_SESSION:
                if self.target_date is None:
                    raise ValueError("SHORTEN_SESSION requires target_date")
                if self.morning_close is None and self.afternoon_close is None:
                    raise ValueError("SHORTEN_SESSION requires morning_close or afternoon_close")
            case CalendarOverrideKind.SET_LAST_TRADING_DAY:
                if (
                    self.contract_year is None
                    or self.contract_month is None
                    or self.last_trading_date is None
                ):
                    raise ValueError(
                        "SET_LAST_TRADING_DAY requires contract_year, contract_month and "
                        "last_trading_date"
                    )

        if self.approval_status is ApprovalStatus.APPROVED and not self.approved_by:
            raise ValueError("an APPROVED override must record approved_by")
        return self

    @property
    def is_effective(self) -> bool:
        return self.approval_status is ApprovalStatus.APPROVED


class PublishedContractDates(_Frozen):
    """Exchange-published dates for one contract month (product trading calendar).

    Preferred over the derived last-trading-day rule whenever available: the rule is our
    reading of the specification, this is the exchange's own answer.
    """

    contract_year: int
    contract_month: int = Field(ge=1, le=12)
    first_trading_date: date | None = None
    last_trading_date: date
    note: str | None = None


class HolidayCalendarYear(_Frozen):
    """One year of official calendar data, versioned and attributed.

    Loaded from ``data/tfex/holidays/<year>.json``. The platform holds no built-in holiday
    dates; an unloaded year is an error, never an empty holiday set.
    """

    schema_version: int = 1
    year: int = Field(ge=1900, le=2999)
    timezone: str = "Asia/Bangkok"
    provenance: Provenance
    holidays: tuple[Holiday, ...] = ()
    shortened_sessions: tuple[ShortenedSession, ...] = ()
    published_contract_dates: tuple[PublishedContractDates, ...] = ()
    overrides: tuple[CalendarOverride, ...] = ()

    @model_validator(mode="after")
    def _dates_belong_to_this_year(self) -> Self:
        for holiday in self.holidays:
            if holiday.holiday_date.year != self.year:
                raise ValueError(
                    f"holiday {holiday.holiday_date} does not belong to calendar year {self.year}"
                )
        for shortened in self.shortened_sessions:
            if shortened.session_date.year != self.year:
                raise ValueError(
                    f"shortened session {shortened.session_date} does not belong to calendar "
                    f"year {self.year}"
                )
        seen: set[date] = set()
        for holiday in self.holidays:
            if holiday.holiday_date in seen:
                raise ValueError(f"duplicate holiday entry for {holiday.holiday_date}")
            seen.add(holiday.holiday_date)
        shortened_seen: set[date] = set()
        for shortened in self.shortened_sessions:
            if shortened.session_date in shortened_seen:
                raise ValueError(f"duplicate shortened-session entry for {shortened.session_date}")
            shortened_seen.add(shortened.session_date)
        return self

    @model_validator(mode="after")
    def _no_shortened_session_on_a_holiday(self) -> Self:
        holiday_dates = {h.holiday_date for h in self.holidays}
        clash = holiday_dates & {s.session_date for s in self.shortened_sessions}
        if clash:
            raise ValueError(
                f"{sorted(clash)} are listed both as holidays and as shortened sessions"
            )
        return self

    @property
    def effective_overrides(self) -> tuple[CalendarOverride, ...]:
        return tuple(o for o in self.overrides if o.is_effective)


class DayClassification(StrEnum):
    TRADING_DAY = "TRADING_DAY"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


class LastTradingDaySource(StrEnum):
    EXCHANGE_PUBLISHED = "EXCHANGE_PUBLISHED"
    """Taken from the product trading calendar. Authoritative."""

    DERIVED_RULE = "DERIVED_RULE"
    """Computed from the contract-specification rule plus imported holidays. A fallback."""

    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"
    """Set by an approved administrative override."""


class ContractExpiry(_Frozen):
    """Resolved expiry facts for one contract month.

    ``expiry_date`` and ``last_trading_date`` are separate fields even though SET50 futures
    are cash-settled on the last trading day: keeping them distinct means a future exchange
    change is a data change, not a schema migration.
    """

    contract_year: int
    contract_month: int = Field(ge=1, le=12)
    last_trading_date: date
    last_trading_time: time
    last_trading_timestamp: datetime
    expiry_date: date
    source: LastTradingDaySource
    calendar_version: str
    resolved_at: datetime

    @model_validator(mode="after")
    def _timestamps_are_aware_and_consistent(self) -> Self:
        if self.last_trading_timestamp.tzinfo is None:
            raise ValueError("last_trading_timestamp must be timezone-aware")
        if self.resolved_at.tzinfo is None:
            raise ValueError("resolved_at must be timezone-aware")
        if self.last_trading_timestamp.date() != self.last_trading_date:
            raise ValueError("last_trading_timestamp must fall on last_trading_date")
        if self.last_trading_timestamp.timetz().replace(tzinfo=None) != self.last_trading_time:
            raise ValueError("last_trading_timestamp must carry last_trading_time")
        if self.last_trading_date.year != self.contract_year:
            raise ValueError(
                f"last trading date {self.last_trading_date} is outside contract year "
                f"{self.contract_year}"
            )
        if self.last_trading_date.month != self.contract_month:
            raise ValueError(
                f"last trading date {self.last_trading_date} is outside contract month "
                f"{self.contract_month}"
            )
        return self
