"""The TFEX trading-calendar service (`CLAUDE_TFEX.md` section 8).

One object that owns the imported calendar data, the trading-day arithmetic built on it,
and the expiry resolution built on that. Everything date-sensitive in the platform goes
through here so that freshness and verification policy is applied in exactly one place.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.tfex.calendar.expiry import ExpiryResolver
from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import (
    ContractExpiry,
    DayClassification,
    HolidayCalendarYear,
    ShortenedSession,
)
from app.tfex.calendar.trading_day import TradingDayCalculator
from app.tfex.config import TfexConfig

__all__ = ["TradingCalendar"]


class TradingCalendar:
    """Facade over holiday data, trading-day arithmetic and expiry resolution."""

    def __init__(
        self,
        config: TfexConfig,
        store: HolidayStore | None = None,
    ) -> None:
        self._config = config
        self._store = store if store is not None else HolidayStore()
        self._trading_days = TradingDayCalculator(self._store)
        self._expiry = ExpiryResolver(config, self._store, self._trading_days)
        self._tz = ZoneInfo(config.market.timezone)
        self._expiry_cache: dict[tuple[int, int], ContractExpiry] = {}

    # --- context ----------------------------------------------------------------------

    @property
    def config(self) -> TfexConfig:
        return self._config

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    @property
    def store(self) -> HolidayStore:
        return self._store

    @property
    def trading_days(self) -> TradingDayCalculator:
        return self._trading_days

    def localize(self, day: date, at: time) -> datetime:
        """Combine a date and a local time into an Asia/Bangkok-aware datetime."""
        return datetime.combine(day, at, tzinfo=self._tz)

    def to_market_time(self, moment: datetime) -> datetime:
        """Convert an aware datetime into market local time.

        Naive datetimes are rejected: a naive timestamp in a cross-timezone system is an
        unanswerable question, and guessing produces silently wrong session states.
        """
        if moment.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware; naive input is ambiguous")
        return moment.astimezone(self._tz)

    # --- day classification -----------------------------------------------------------

    def classify(self, day: date) -> DayClassification:
        return self._trading_days.classify(day)

    def is_trading_day(self, day: date) -> bool:
        return self._trading_days.is_trading_day(day)

    def next_trading_day(self, day: date, *, inclusive: bool = False) -> date:
        return self._trading_days.next_trading_day(day, inclusive=inclusive)

    def previous_trading_day(self, day: date, *, inclusive: bool = False) -> date:
        return self._trading_days.previous_trading_day(day, inclusive=inclusive)

    def trading_days_between(self, start: date, end: date) -> int:
        return self._trading_days.count_trading_days_between(start, end)

    def shortened_session(self, day: date) -> ShortenedSession | None:
        return self._trading_days.shortened_session(day)

    def year_data(self, year: int) -> HolidayCalendarYear:
        return self._store.year(year)

    # --- expiry -----------------------------------------------------------------------

    def contract_expiry(
        self, contract_year: int, contract_month: int, *, resolved_at: datetime | None = None
    ) -> ContractExpiry:
        """Resolved expiry for a contract month, cached per process.

        The cache is keyed on the contract month alone because calendar data is immutable
        once loaded; a changed calendar means a new process, not a mutated answer.
        """
        key = (contract_year, contract_month)
        cached = self._expiry_cache.get(key)
        if cached is not None:
            return cached
        resolved = self._expiry.resolve(
            contract_year,
            contract_month,
            resolved_at=resolved_at or datetime.now(self._tz),
        )
        self._expiry_cache[key] = resolved
        return resolved

    def is_last_trading_day(self, day: date, contract_year: int, contract_month: int) -> bool:
        return self.contract_expiry(contract_year, contract_month).last_trading_date == day

    # --- data policy ------------------------------------------------------------------

    def require_usable(self, day: date, *, as_of: datetime) -> None:
        """Raise unless the calendar data covering ``day`` may be relied on at ``as_of``.

        Applies the freshness window and, when ``metadata.require_verified_sources`` is set,
        the verification requirement. Section 28 requires order-capable modes to stop on
        critical data-quality failures; this is the calendar's contribution to that gate.
        """
        year_data = self._store.year(day.year)
        provenance = year_data.provenance
        if provenance.stale_after is None and provenance.retrieved_at is not None:
            provenance = provenance.with_staleness(
                days=self._config.metadata.holiday_data_stale_after_days
            )
        provenance.require_usable(
            as_of,
            require_verified=self._config.metadata.require_verified_sources,
        )

    def data_health(self, day: date, *, as_of: datetime) -> dict[str, object]:
        """Non-raising view of the same policy, for dashboards and diagnostics."""
        try:
            year_data = self._store.year(day.year)
        except Exception as exc:  # broad on purpose: reported to the caller, not swallowed
            return {"year": day.year, "loaded": False, "problem": str(exc)}
        provenance = year_data.provenance
        return {
            "year": day.year,
            "loaded": True,
            "verified": provenance.verified,
            "retrieved_at": provenance.retrieved_at,
            "stale": provenance.is_stale(as_of),
            "source": provenance.source_name,
            "holidays": len(year_data.holidays),
            "shortened_sessions": len(year_data.shortened_sessions),
            "effective_overrides": len(year_data.effective_overrides),
        }

    #: How close to a year boundary a range must come before the neighbouring year's data is
    #: genuinely needed. Previous/next-trading-day walks and end-of-month expiry rules cross
    #: the boundary, but never by more than a few days; a month of margin covers every walk
    #: this platform performs.
    YEAR_BOUNDARY_MARGIN_DAYS = 31

    def required_years_for(self, start: date, end: date) -> tuple[int, ...]:
        """Years whose data must be imported to answer questions across ``[start, end]``.

        A neighbouring year is required only when the range comes within
        :data:`YEAR_BOUNDARY_MARGIN_DAYS` of the boundary, because that is when a
        previous/next-trading-day walk or an end-of-month expiry rule actually reaches into
        it. A mid-year range does not need the adjacent years, and demanding them would be a
        false blocker — TFEX publishes next year's calendar only late in the current year.

        This is a *precision* change, not a relaxation. The fail-closed guarantee lives in
        :meth:`HolidayStore.year`, which still raises the moment any operation actually
        touches an unimported year. :meth:`preflight` is an early warning built on top of it.
        """
        first = min(start, end)
        last = max(start, end)
        margin = timedelta(days=self.YEAR_BOUNDARY_MARGIN_DAYS)

        years = set(range(first.year, last.year + 1))
        if (first - date(first.year, 1, 1)) < margin:
            years.add(first.year - 1)
        if (date(last.year, 12, 31) - last) < margin:
            years.add(last.year + 1)
        return tuple(sorted(years))

    def preflight(self, start: date, end: date) -> None:
        """Fail before a run starts rather than in the middle of it."""
        self._store.require_years(self.required_years_for(start, end))

    # --- convenience ------------------------------------------------------------------

    def previous_trading_day_of(self, day: date) -> date:
        """The session whose levels are the "previous day" levels for ``day``.

        Used by section 11 session profiles: previous-day levels become available at the
        next valid session, and that session is not simply ``day - 1``.
        """
        return self._trading_days.previous_trading_day(day)

    def session_dates_in_range(self, start: date, end: date) -> tuple[date, ...]:
        return tuple(self._trading_days.iter_trading_days(start, end))

    def days_to_expiry(self, day: date, expiry: ContractExpiry) -> tuple[int, int]:
        """``(calendar_days, trading_days)`` remaining until the last trading day.

        Both are returned because section 5 asks for ``days_to_expiry`` without stating a
        unit. Gates use the trading-day figure: it is holiday-aware and never optimistic.
        """
        calendar_days = (expiry.last_trading_date - day).days
        trading_days = self._trading_days.count_trading_days_between(day, expiry.last_trading_date)
        return calendar_days, trading_days

    def month_of(self, moment: datetime) -> tuple[int, int]:
        local = self.to_market_time(moment)
        return local.year, local.month

    def next_contract_month(self, contract_year: int, contract_month: int) -> tuple[int, int]:
        following = date(contract_year, contract_month, 1) + timedelta(days=32)
        return following.year, following.month
