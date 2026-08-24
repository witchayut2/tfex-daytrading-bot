"""Trading-day arithmetic over imported official calendar data.

Section 8: *"Do not derive trading days only from weekdays."* The weekend rule here is a
necessary condition, never a sufficient one — every answer also consults the imported
holiday set, and a year without imported data produces an error rather than a guess.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, time, timedelta

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import (
    CalendarOverrideKind,
    DayClassification,
    HolidayCalendarYear,
    ShortenedSession,
)
from app.tfex.errors import CalendarDataUnavailableError, NotATradingDayError

__all__ = ["TradingDayCalculator", "last_day_of_month"]

_WEEKEND = frozenset({5, 6})  # Saturday, Sunday
_MAX_SEARCH_DAYS = 400  # a full year of closures would be a data error, not a market event


def last_day_of_month(year: int, month: int) -> date:
    """Calendar last day of the month (not the last *trading* day)."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


class TradingDayCalculator:
    """Answers "is this a trading day?" and the walks built on top of that question."""

    def __init__(self, store: HolidayStore) -> None:
        self._store = store

    # --- classification ---------------------------------------------------------------

    def classify(self, day: date) -> DayClassification:
        """Classify ``day``. Raises when the year's official data is not imported."""
        year_data = self._store.year(day.year)
        if day.weekday() in _WEEKEND:
            return DayClassification.WEEKEND
        if day in self._holiday_dates(year_data):
            return DayClassification.HOLIDAY
        return DayClassification.TRADING_DAY

    def is_trading_day(self, day: date) -> bool:
        return self.classify(day) is DayClassification.TRADING_DAY

    def require_trading_day(self, day: date) -> None:
        classification = self.classify(day)
        if classification is not DayClassification.TRADING_DAY:
            raise NotATradingDayError(
                f"{day.isoformat()} is not a TFEX trading day ({classification})"
            )

    def _holiday_dates(self, year_data: HolidayCalendarYear) -> frozenset[date]:
        """Imported holidays with approved administrative overrides applied.

        Only ``APPROVED`` overrides count: a pending request must never move a trading day.
        """
        dates = {h.holiday_date for h in year_data.holidays}
        for override in year_data.effective_overrides:
            if override.target_date is None:
                continue
            if override.kind is CalendarOverrideKind.ADD_HOLIDAY:
                dates.add(override.target_date)
            elif override.kind is CalendarOverrideKind.REMOVE_HOLIDAY:
                dates.discard(override.target_date)
        return frozenset(dates)

    # --- shortened sessions -----------------------------------------------------------

    def shortened_session(self, day: date) -> ShortenedSession | None:
        """Announced early close for ``day``, if any (approved overrides win)."""
        year_data = self._store.year(day.year)
        override_result: ShortenedSession | None = None
        for override in year_data.effective_overrides:
            if (
                override.kind is CalendarOverrideKind.SHORTEN_SESSION
                and override.target_date == day
            ):
                override_result = ShortenedSession(
                    session_date=day,
                    morning_close=override.morning_close,
                    afternoon_close=override.afternoon_close,
                    reason=override.reason,
                    note=f"administrative override by {override.operator}",
                )
        if override_result is not None:
            return override_result
        for shortened in year_data.shortened_sessions:
            if shortened.session_date == day:
                return shortened
        return None

    def afternoon_close_override(self, day: date) -> time | None:
        shortened = self.shortened_session(day)
        return shortened.afternoon_close if shortened else None

    # --- walks ------------------------------------------------------------------------

    def next_trading_day(self, day: date, *, inclusive: bool = False) -> date:
        candidate = day if inclusive else day + timedelta(days=1)
        for _ in range(_MAX_SEARCH_DAYS):
            if self.is_trading_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        raise CalendarDataUnavailableError(
            f"no trading day found within {_MAX_SEARCH_DAYS} days after {day.isoformat()}"
        )

    def previous_trading_day(self, day: date, *, inclusive: bool = False) -> date:
        candidate = day if inclusive else day - timedelta(days=1)
        for _ in range(_MAX_SEARCH_DAYS):
            if self.is_trading_day(candidate):
                return candidate
            candidate -= timedelta(days=1)
        raise CalendarDataUnavailableError(
            f"no trading day found within {_MAX_SEARCH_DAYS} days before {day.isoformat()}"
        )

    def shift_trading_days(self, day: date, offset: int) -> date:
        """Move ``offset`` trading days from ``day`` (negative moves backwards)."""
        if offset == 0:
            return day
        step = self.next_trading_day if offset > 0 else self.previous_trading_day
        current = day
        for _ in range(abs(offset)):
            current = step(current)
        return current

    def iter_trading_days(self, start: date, end: date) -> Iterator[date]:
        """Trading days in the inclusive range ``[start, end]``."""
        if end < start:
            return
        current = start
        while current <= end:
            if self.is_trading_day(current):
                yield current
            current += timedelta(days=1)

    def trading_days_in_month(self, year: int, month: int) -> tuple[date, ...]:
        first = date(year, month, 1)
        return tuple(self.iter_trading_days(first, last_day_of_month(year, month)))

    def count_trading_days_between(self, start: date, end: date) -> int:
        """Trading days strictly after ``start`` up to and including ``end``.

        Negative when ``end`` precedes ``start``. This is the unit used for
        ``trading_days_to_expiry``: the count of remaining opportunities to trade.
        """
        if end == start:
            return 0
        if end < start:
            return -self.count_trading_days_between(end, start)
        return sum(1 for _ in self.iter_trading_days(start + timedelta(days=1), end))
