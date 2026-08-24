"""Trading-day arithmetic (`CLAUDE_TFEX.md` section 8).

Holiday dates here are fixtures, not real TFEX holidays — see ``conftest.py``.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import DayClassification
from app.tfex.calendar.service import TradingCalendar
from app.tfex.calendar.trading_day import last_day_of_month
from app.tfex.config import TfexConfig
from app.tfex.errors import CalendarDataUnavailableError, NotATradingDayError
from tests.tfex.conftest import BANGKOK, build_year

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=BANGKOK)


def test_weekends_are_not_trading_days(calendar: TradingCalendar) -> None:
    assert calendar.classify(date(2026, 1, 3)) is DayClassification.WEEKEND  # Saturday
    assert calendar.classify(date(2026, 1, 4)) is DayClassification.WEEKEND  # Sunday


def test_imported_holidays_are_not_trading_days(calendar: TradingCalendar) -> None:
    assert calendar.classify(date(2026, 1, 1)) is DayClassification.HOLIDAY
    assert not calendar.is_trading_day(date(2026, 1, 1))


def test_an_ordinary_weekday_is_a_trading_day(calendar: TradingCalendar) -> None:
    assert calendar.classify(date(2026, 1, 2)) is DayClassification.TRADING_DAY


def test_a_year_without_imported_data_is_an_error_not_a_weekday_rule(
    config: TfexConfig,
) -> None:
    """Section 8: do not derive trading days only from weekdays."""
    calendar = TradingCalendar(config, HolidayStore("/nonexistent", preloaded=[build_year(2026)]))
    with pytest.raises(CalendarDataUnavailableError):
        calendar.is_trading_day(date(2031, 6, 15))  # a plain Monday


def test_require_trading_day_names_the_reason(calendar: TradingCalendar) -> None:
    with pytest.raises(NotATradingDayError, match="HOLIDAY"):
        calendar.trading_days.require_trading_day(date(2026, 1, 1))
    with pytest.raises(NotATradingDayError, match="WEEKEND"):
        calendar.trading_days.require_trading_day(date(2026, 1, 3))


def test_next_trading_day_skips_a_holiday_and_a_weekend(calendar: TradingCalendar) -> None:
    # Fri 27 Feb -> Sat, Sun, Mon 2 Mar is a fixture holiday -> Tue 3 Mar
    assert calendar.next_trading_day(date(2026, 2, 27)) == date(2026, 3, 3)


def test_previous_trading_day_crosses_the_year_boundary(calendar: TradingCalendar) -> None:
    # Fri 2 Jan 2026 <- Thu 1 Jan (holiday) <- Wed 31 Dec 2025 (holiday) <- Tue 30 Dec 2025
    assert calendar.previous_trading_day(date(2026, 1, 2)) == date(2025, 12, 30)


def test_inclusive_walks_return_the_day_itself_when_it_trades(
    calendar: TradingCalendar,
) -> None:
    assert calendar.next_trading_day(date(2026, 1, 2), inclusive=True) == date(2026, 1, 2)
    assert calendar.previous_trading_day(date(2026, 1, 2), inclusive=True) == date(2026, 1, 2)
    assert calendar.next_trading_day(date(2026, 1, 1), inclusive=True) == date(2026, 1, 2)


def test_shift_trading_days_moves_by_sessions_not_calendar_days(
    calendar: TradingCalendar,
) -> None:
    assert calendar.trading_days.shift_trading_days(date(2026, 2, 27), 1) == date(2026, 3, 3)
    assert calendar.trading_days.shift_trading_days(date(2026, 3, 3), -1) == date(2026, 2, 27)
    assert calendar.trading_days.shift_trading_days(date(2026, 3, 3), 0) == date(2026, 3, 3)


def test_counting_trading_days_excludes_the_start_and_includes_the_end(
    calendar: TradingCalendar,
) -> None:
    # after Mon 2 Mar (holiday): Tue 3, Wed 4, Thu 5, Fri 6
    assert calendar.trading_days_between(date(2026, 3, 2), date(2026, 3, 6)) == 4
    assert calendar.trading_days_between(date(2026, 3, 6), date(2026, 3, 6)) == 0


def test_counting_backwards_is_negative(calendar: TradingCalendar) -> None:
    assert calendar.trading_days_between(date(2026, 3, 6), date(2026, 3, 2)) == -4


def test_trading_days_in_month_excludes_weekends_and_holidays(
    calendar: TradingCalendar,
) -> None:
    june = calendar.trading_days.trading_days_in_month(2026, 6)
    assert date(2026, 6, 30) not in june  # fixture holiday
    assert date(2026, 6, 27) not in june  # Saturday
    assert june[-1] == date(2026, 6, 29)


def test_previous_trading_day_of_is_not_simply_yesterday(calendar: TradingCalendar) -> None:
    """Section 11: previous-day levels come from the previous *session*."""
    assert calendar.previous_trading_day_of(date(2026, 3, 3)) == date(2026, 2, 27)


def test_required_years_pads_the_range_on_both_sides(calendar: TradingCalendar) -> None:
    assert calendar.required_years_for(date(2026, 1, 1), date(2026, 12, 31)) == (2025, 2026, 2027)


def test_preflight_fails_before_a_run_rather_than_during_it(config: TfexConfig) -> None:
    calendar = TradingCalendar(config, HolidayStore("/nonexistent", preloaded=[build_year(2026)]))
    with pytest.raises(CalendarDataUnavailableError, match="missing for"):
        calendar.preflight(date(2026, 1, 5), date(2026, 6, 30))


def test_preflight_passes_when_every_year_is_present(calendar: TradingCalendar) -> None:
    calendar.preflight(date(2026, 1, 5), date(2026, 6, 30))


def test_naive_timestamps_are_refused(calendar: TradingCalendar) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar.to_market_time(datetime(2026, 8, 23, 10, 0))


def test_timestamps_are_converted_into_market_time(calendar: TradingCalendar) -> None:
    from datetime import UTC

    utc_moment = datetime(2026, 8, 23, 3, 0, tzinfo=UTC)
    local = calendar.to_market_time(utc_moment)
    assert (local.hour, local.minute) == (10, 0)
    assert local.date() == date(2026, 8, 23)


def test_last_day_of_month_handles_december() -> None:
    assert last_day_of_month(2026, 12) == date(2026, 12, 31)
    assert last_day_of_month(2026, 2) == date(2026, 2, 28)
    assert last_day_of_month(2028, 2) == date(2028, 2, 29)


def test_next_contract_month_wraps_the_year(calendar: TradingCalendar) -> None:
    assert calendar.next_contract_month(2026, 12) == (2027, 1)
    assert calendar.next_contract_month(2026, 1) == (2026, 2)


def test_days_to_expiry_reports_both_units(calendar: TradingCalendar) -> None:
    """Section 5 leaves the unit unstated, so both are available and gates use trading days."""
    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)  # last trading day 29 Dec
    calendar_days, trading_days = calendar.days_to_expiry(date(2026, 12, 23), expiry)

    assert calendar_days == 6
    # 24 Thu, 25 Fri, 28 Mon, 29 Tue -> 4 trading days (26/27 are the weekend)
    assert trading_days == 4
    assert trading_days < calendar_days


def test_approved_remove_holiday_override_restores_a_trading_day(config: TfexConfig) -> None:
    from app.tfex.calendar.models import ApprovalStatus, CalendarOverride, CalendarOverrideKind

    override = CalendarOverride(
        kind=CalendarOverrideKind.REMOVE_HOLIDAY,
        operator="risk.ops",
        reason="the imported list contained a holiday the exchange later cancelled",
        source="TFEX notice",
        created_at=NOW,
        effective_date=date(2026, 3, 1),
        approval_status=ApprovalStatus.APPROVED,
        approved_by="head.of.risk",
        approved_at=NOW,
        target_date=date(2026, 3, 2),
    )
    calendar = TradingCalendar(
        config, HolidayStore("/nonexistent", preloaded=[build_year(2026, overrides=[override])])
    )
    assert calendar.is_trading_day(date(2026, 3, 2))
