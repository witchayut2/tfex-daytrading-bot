"""Shared fixtures for the TFEX test suite.

**The holiday dates in this file are invented for testing and are not real TFEX holidays.**
They are chosen to exercise the awkward cases — a holiday on the last calendar day of a
month, a holiday *between* the last two business days, a closure spanning a year boundary —
because those are what break last-trading-day arithmetic. Real holiday data is imported by
an operator into ``backend/data/tfex/holidays/`` and is deliberately absent from the repo.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import (
    CalendarOverride,
    Holiday,
    HolidayCalendarYear,
    PublishedContractDates,
    ShortenedSession,
)
from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig, default_config
from app.tfex.contracts.registry import ContractMarketState, ContractRegistry
from app.tfex.provenance import Provenance
from app.tfex.sessions.engine import SessionEngine

BANGKOK = ZoneInfo("Asia/Bangkok")

RETRIEVED_AT = datetime(2026, 1, 1, 8, 0, tzinfo=BANGKOK)
STALE_AFTER = datetime(2030, 1, 1, 8, 0, tzinfo=BANGKOK)

#: Synthetic holidays. See the module docstring: these are test fixtures, not TFEX data.
FIXTURE_HOLIDAYS: dict[int, tuple[tuple[str, str], ...]] = {
    2025: (
        ("2025-01-01", "fixture new year"),
        ("2025-12-31", "fixture year end"),
    ),
    2026: (
        ("2026-01-01", "fixture new year"),
        ("2026-03-02", "fixture mid-month closure"),
        ("2026-06-30", "fixture closure on the last calendar day of the month"),
        ("2026-09-29", "fixture closure between the last two business days"),
        ("2026-12-31", "fixture year end"),
    ),
    2027: (("2027-01-01", "fixture new year"),),
}


def build_year(
    year: int,
    *,
    holidays: Iterable[tuple[str, str]] | None = None,
    shortened_sessions: Sequence[ShortenedSession] = (),
    published_contract_dates: Sequence[PublishedContractDates] = (),
    overrides: Sequence[CalendarOverride] = (),
    provenance: Provenance | None = None,
) -> HolidayCalendarYear:
    """Build one year of fixture calendar data."""
    entries = FIXTURE_HOLIDAYS.get(year, ()) if holidays is None else tuple(holidays)
    return HolidayCalendarYear(
        year=year,
        provenance=provenance
        or Provenance(
            source_name=f"fixture calendar {year}",
            retrieved_at=RETRIEVED_AT,
            stale_after=STALE_AFTER,
            verified=True,
        ),
        holidays=tuple(
            Holiday(holiday_date=date.fromisoformat(day), name=name) for day, name in entries
        ),
        shortened_sessions=tuple(shortened_sessions),
        published_contract_dates=tuple(published_contract_dates),
        overrides=tuple(overrides),
    )


@pytest.fixture
def config() -> TfexConfig:
    return default_config()


@pytest.fixture
def store() -> HolidayStore:
    """A store preloaded with 2025-2027 fixture data and no directory to fall back to."""
    return HolidayStore(
        directory="/nonexistent-so-unloaded-years-raise",
        preloaded=[build_year(year) for year in (2025, 2026, 2027)],
    )


@pytest.fixture
def calendar(config: TfexConfig, store: HolidayStore) -> TradingCalendar:
    return TradingCalendar(config, store)


@pytest.fixture
def engine(config: TfexConfig, calendar: TradingCalendar) -> SessionEngine:
    return SessionEngine(config, calendar)


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        source_name="fixture contract metadata",
        retrieved_at=RETRIEVED_AT,
        stale_after=STALE_AFTER,
        verified=True,
    )


@pytest.fixture
def registry(
    config: TfexConfig, calendar: TradingCalendar, provenance: Provenance
) -> ContractRegistry:
    """Registry holding the December 2026 and March 2027 contracts."""
    registry = ContractRegistry(config, calendar)
    registry.register_symbol(
        "S50Z26",
        reference_date=date(2026, 12, 1),
        provenance=provenance,
        listing_date=date(2025, 12, 1),
        market_state=ContractMarketState(daily_volume=100_000, open_interest=50_000),
    )
    registry.register_symbol(
        "S50H27",
        reference_date=date(2026, 12, 1),
        provenance=provenance,
        listing_date=date(2026, 3, 2),
        market_state=ContractMarketState(daily_volume=20_000, open_interest=15_000),
    )
    return registry


def bkk(day: date, at: time) -> datetime:
    """Asia/Bangkok-aware datetime helper."""
    return datetime.combine(day, at, tzinfo=BANGKOK)


#: Published dates matching what TFEX actually publishes for the December 2026 contract, so
#: market-data tests exercise the EXCHANGE_PUBLISHED path rather than the derived fallback.
FIXTURE_PUBLISHED_DATES = (
    PublishedContractDates(
        contract_year=2026,
        contract_month=12,
        first_trading_date=date(2025, 12, 29),
        last_trading_date=date(2026, 12, 29),
        note="S50Z26 fixture mirroring the exchange-published calendar",
    ),
)


@pytest.fixture
def published_calendar(config: TfexConfig) -> TradingCalendar:
    """Calendar whose December 2026 expiry comes from a published contract date."""
    return TradingCalendar(
        config,
        HolidayStore(
            "/nonexistent-so-unloaded-years-raise",
            preloaded=[
                build_year(2025),
                build_year(2026, published_contract_dates=FIXTURE_PUBLISHED_DATES),
                build_year(2027),
            ],
        ),
    )
