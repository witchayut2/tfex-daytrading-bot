"""Expiry resolution precedence and failure modes (`CLAUDE_TFEX.md` sections 2, 3 and 8)."""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import (
    ApprovalStatus,
    CalendarOverride,
    CalendarOverrideKind,
    HolidayCalendarYear,
    LastTradingDaySource,
    PublishedContractDates,
    ShortenedSession,
)
from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.errors import (
    CalendarDataInvalidError,
    CalendarDataUnavailableError,
    StaleMetadataError,
)
from app.tfex.provenance import Provenance
from tests.tfex.conftest import BANGKOK, build_year

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=BANGKOK)


def calendar_with(config: TfexConfig, *years: HolidayCalendarYear) -> TradingCalendar:
    return TradingCalendar(config, HolidayStore("/nonexistent", preloaded=years))


def test_an_exchange_published_date_beats_the_derived_rule(config: TfexConfig) -> None:
    """The rule is our reading of the specification; the published date is the exchange's."""
    published = PublishedContractDates(
        contract_year=2026, contract_month=12, last_trading_date=date(2026, 12, 28)
    )
    calendar = calendar_with(config, build_year(2026, published_contract_dates=[published]))

    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)
    assert expiry.last_trading_date == date(2026, 12, 28)
    assert expiry.source is LastTradingDaySource.EXCHANGE_PUBLISHED


def test_an_approved_override_beats_a_published_date(config: TfexConfig) -> None:
    published = PublishedContractDates(
        contract_year=2026, contract_month=12, last_trading_date=date(2026, 12, 28)
    )
    override = CalendarOverride(
        kind=CalendarOverrideKind.SET_LAST_TRADING_DAY,
        operator="risk.ops",
        reason="exchange notice 44/2026 corrected the published table",
        source="TFEX notice 44/2026",
        created_at=NOW,
        effective_date=date(2026, 12, 1),
        approval_status=ApprovalStatus.APPROVED,
        approved_by="head.of.risk",
        approved_at=NOW,
        contract_year=2026,
        contract_month=12,
        last_trading_date=date(2026, 12, 23),
    )
    calendar = calendar_with(
        config, build_year(2026, published_contract_dates=[published], overrides=[override])
    )

    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)
    assert expiry.last_trading_date == date(2026, 12, 23)
    assert expiry.source is LastTradingDaySource.ADMIN_OVERRIDE


def test_a_pending_override_changes_nothing(config: TfexConfig) -> None:
    """An unreviewed edit must never move a trading date (section 8)."""
    override = CalendarOverride(
        kind=CalendarOverrideKind.SET_LAST_TRADING_DAY,
        operator="someone",
        reason="looks wrong to me",
        source="a hunch",
        created_at=NOW,
        effective_date=date(2026, 12, 1),
        contract_year=2026,
        contract_month=12,
        last_trading_date=date(2026, 12, 23),
    )
    calendar = calendar_with(config, build_year(2026, overrides=[override]))

    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)
    assert expiry.last_trading_date == date(2026, 12, 29)
    assert expiry.source is LastTradingDaySource.DERIVED_RULE


def test_an_approved_override_must_name_its_approver() -> None:
    with pytest.raises(ValueError, match="must record approved_by"):
        CalendarOverride(
            kind=CalendarOverrideKind.ADD_HOLIDAY,
            operator="ops",
            reason="special closure",
            source="notice",
            created_at=NOW,
            effective_date=date(2026, 7, 1),
            approval_status=ApprovalStatus.APPROVED,
            target_date=date(2026, 7, 1),
            holiday_name="fixture special closure",
        )


def test_an_override_payload_must_match_its_kind() -> None:
    with pytest.raises(ValueError, match="ADD_HOLIDAY requires"):
        CalendarOverride(
            kind=CalendarOverrideKind.ADD_HOLIDAY,
            operator="ops",
            reason="special closure",
            source="notice",
            created_at=NOW,
            effective_date=date(2026, 7, 1),
        )


def test_an_approved_add_holiday_override_moves_the_last_trading_day(
    config: TfexConfig,
) -> None:
    override = CalendarOverride(
        kind=CalendarOverrideKind.ADD_HOLIDAY,
        operator="risk.ops",
        reason="late government special holiday announcement",
        source="cabinet resolution",
        created_at=NOW,
        effective_date=date(2026, 12, 1),
        approval_status=ApprovalStatus.APPROVED,
        approved_by="head.of.risk",
        approved_at=NOW,
        target_date=date(2026, 12, 30),
        holiday_name="fixture special holiday",
    )
    baseline = calendar_with(config, build_year(2026))
    adjusted = calendar_with(config, build_year(2026, overrides=[override]))

    assert baseline.contract_expiry(2026, 12, resolved_at=NOW).last_trading_date == date(
        2026, 12, 29
    )
    # 30 Dec removed => last business day becomes 29 Dec, last trading day 28 Dec.
    assert adjusted.contract_expiry(2026, 12, resolved_at=NOW).last_trading_date == date(
        2026, 12, 28
    )


def test_an_early_close_on_the_last_trading_day_moves_cessation_earlier(
    config: TfexConfig,
) -> None:
    shortened = ShortenedSession(
        session_date=date(2026, 12, 29), afternoon_close=time(12, 30), reason="fixture early close"
    )
    calendar = calendar_with(config, build_year(2026, shortened_sessions=[shortened]))

    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)
    assert expiry.last_trading_time == time(12, 30)
    assert expiry.last_trading_timestamp == datetime(2026, 12, 29, 12, 30, tzinfo=BANGKOK)


def test_a_later_announced_close_does_not_delay_cessation(config: TfexConfig) -> None:
    """16:30 is the exchange rule; an announcement may only bring it forward."""
    shortened = ShortenedSession(
        session_date=date(2026, 12, 29), afternoon_close=time(16, 45), reason="fixture"
    )
    calendar = calendar_with(config, build_year(2026, shortened_sessions=[shortened]))
    assert calendar.contract_expiry(2026, 12, resolved_at=NOW).last_trading_time == time(16, 30)


def test_a_published_date_that_is_not_a_trading_day_is_a_data_conflict(
    config: TfexConfig,
) -> None:
    """Our holidays and the exchange disagree; that must be investigated, not averaged."""
    published = PublishedContractDates(
        contract_year=2026, contract_month=12, last_trading_date=date(2026, 12, 31)
    )
    calendar = calendar_with(config, build_year(2026, published_contract_dates=[published]))

    with pytest.raises(CalendarDataInvalidError, match="is not a trading day"):
        calendar.contract_expiry(2026, 12, resolved_at=NOW)


def test_requiring_published_dates_makes_the_derived_rule_an_error(config: TfexConfig) -> None:
    strict = config.model_copy(
        update={
            "expiry": config.expiry.model_copy(update={"require_published_last_trading_day": True})
        }
    )
    calendar = calendar_with(strict, build_year(2026))

    with pytest.raises(CalendarDataInvalidError, match="no exchange-published last trading day"):
        calendar.contract_expiry(2026, 12, resolved_at=NOW)


def test_an_unimported_year_cannot_produce_an_expiry(config: TfexConfig) -> None:
    calendar = calendar_with(config, build_year(2026))
    with pytest.raises(CalendarDataUnavailableError):
        calendar.contract_expiry(2028, 3, resolved_at=NOW)


def test_a_naive_resolution_timestamp_is_rejected(calendar: TradingCalendar) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar.contract_expiry(2026, 12, resolved_at=datetime(2026, 8, 23, 10, 0))


def test_the_resolved_expiry_records_the_calendar_version(calendar: TradingCalendar) -> None:
    expiry = calendar.contract_expiry(2026, 12, resolved_at=NOW)
    assert expiry.calendar_version.startswith("1/2026:")
    assert expiry.resolved_at == NOW


def test_stale_calendar_data_is_refused_for_decisions(config: TfexConfig) -> None:
    stale = build_year(
        2026,
        provenance=Provenance(
            source_name="fixture",
            retrieved_at=datetime(2020, 1, 1, tzinfo=BANGKOK),
            stale_after=datetime(2020, 7, 1, tzinfo=BANGKOK),
        ),
    )
    calendar = calendar_with(config, stale)
    with pytest.raises(StaleMetadataError):
        calendar.require_usable(date(2026, 12, 29), as_of=NOW)


def test_data_health_reports_without_raising(config: TfexConfig) -> None:
    calendar = calendar_with(config, build_year(2026))
    healthy = calendar.data_health(date(2026, 12, 29), as_of=NOW)
    assert healthy["loaded"] is True
    assert healthy["stale"] is False

    missing = calendar.data_health(date(2031, 1, 5), as_of=NOW)
    assert missing["loaded"] is False
    assert "problem" in missing
