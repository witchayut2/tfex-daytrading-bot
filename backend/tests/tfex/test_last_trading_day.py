"""The last-trading-day rule (`CLAUDE_TFEX.md` section 3).

> last trading day: business day immediately before the last business day of the contract
> month

"Business day" means *trading day*, which means the imported holiday set. These tests pin
that down with month layouts chosen so a wrong reading gives a visibly wrong date.

The holidays used here are fixtures, not real TFEX holidays — see ``conftest.py``.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import ContractExpiry, LastTradingDaySource
from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from tests.tfex.conftest import BANGKOK, build_year

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=BANGKOK)


@pytest.mark.parametrize(
    ("month", "expected_last_business_day", "expected_last_trading_day", "why"),
    [
        (
            1,
            date(2026, 1, 30),
            date(2026, 1, 29),
            "31 Jan is a Saturday, so the month ends Thu 29 / Fri 30",
        ),
        (
            3,
            date(2026, 3, 31),
            date(2026, 3, 30),
            "no closures near month end: plain Mon 30 / Tue 31",
        ),
        (
            6,
            date(2026, 6, 29),
            date(2026, 6, 26),
            "30 Jun is a fixture holiday, so the last business day falls back to Mon 29 "
            "and the last trading day skips the weekend to Fri 26",
        ),
        (
            9,
            date(2026, 9, 30),
            date(2026, 9, 28),
            "29 Sep is a fixture holiday sitting between the last two business days",
        ),
        (
            12,
            date(2026, 12, 30),
            date(2026, 12, 29),
            "31 Dec is a fixture holiday",
        ),
    ],
)
def test_derived_last_trading_day_for_each_contract_month(
    calendar: TradingCalendar,
    month: int,
    expected_last_business_day: date,
    expected_last_trading_day: date,
    why: str,
) -> None:
    trading_days = calendar.trading_days.trading_days_in_month(2026, month)
    assert trading_days[-1] == expected_last_business_day, why

    expiry = calendar.contract_expiry(2026, month, resolved_at=NOW)
    assert expiry.last_trading_date == expected_last_trading_day, why
    assert expiry.source is LastTradingDaySource.DERIVED_RULE


def test_a_month_end_holiday_actually_moves_the_last_trading_day(
    config: TfexConfig,
) -> None:
    """The same month with and without the fixture holiday must give different answers."""
    with_holiday = TradingCalendar(
        config, HolidayStore("/nonexistent", preloaded=[build_year(2026)])
    )
    without_holiday = TradingCalendar(
        config, HolidayStore("/nonexistent", preloaded=[build_year(2026, holidays=())])
    )

    assert with_holiday.contract_expiry(2026, 6, resolved_at=NOW).last_trading_date == date(
        2026, 6, 26
    )
    assert without_holiday.contract_expiry(2026, 6, resolved_at=NOW).last_trading_date == date(
        2026, 6, 29
    )


def test_trading_ceases_at_1630_on_the_last_trading_day(calendar: TradingCalendar) -> None:
    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)

    assert expiry.last_trading_time == time(16, 30)
    assert expiry.last_trading_timestamp == datetime(2026, 12, 29, 16, 30, tzinfo=BANGKOK)
    assert expiry.last_trading_timestamp.tzinfo is not None


def test_the_last_trading_day_is_itself_a_trading_day(calendar: TradingCalendar) -> None:
    for month in range(1, 13):
        expiry = calendar.contract_expiry(2026, month, resolved_at=NOW)
        assert calendar.is_trading_day(expiry.last_trading_date)


def test_the_last_trading_day_precedes_the_last_business_day_by_one_trading_day(
    calendar: TradingCalendar,
) -> None:
    for month in range(1, 13):
        expiry = calendar.contract_expiry(2026, month, resolved_at=NOW)
        month_days = calendar.trading_days.trading_days_in_month(2026, month)
        assert calendar.next_trading_day(expiry.last_trading_date) == month_days[-1]


def test_expiry_date_and_last_trading_date_are_separate_fields(
    calendar: TradingCalendar,
) -> None:
    """Equal today for a cash-settled contract, but modelled separately on purpose."""
    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)
    assert expiry.expiry_date == expiry.last_trading_date
    assert "expiry_date" in ContractExpiry.model_fields
    assert "last_trading_date" in ContractExpiry.model_fields
