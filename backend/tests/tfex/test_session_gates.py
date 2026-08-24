"""Session-level trading gates (`CLAUDE_TFEX.md` section 9).

Section 9 forbids opening a new position during pre-open, during the midday break, after
the entry cutoff, after 16:30 on the last trading day, and *"while the calendar is unknown
or stale"*. Each of those is a test here, plus the rule that a blocked entry must never
block an exit.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.tfex.calendar.models import ContractExpiry
from app.tfex.calendar.service import TradingCalendar
from app.tfex.errors import SessionNotEligibleError
from app.tfex.sessions.boundaries import SessionState
from app.tfex.sessions.engine import SessionEngine
from tests.tfex.conftest import bkk

REGULAR_DAY = date(2026, 12, 23)  # Wednesday
LAST_TRADING_DAY = date(2026, 12, 29)
HOLIDAY = date(2026, 12, 31)
WEEKEND = date(2026, 12, 26)
RESOLVED_AT = bkk(date(2026, 8, 23), time(10, 0))


@pytest.fixture
def expiry(calendar: TradingCalendar) -> ContractExpiry:
    return calendar.contract_expiry(2026, 12, resolved_at=RESOLVED_AT)


def test_a_new_position_is_allowed_mid_session(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    decision = engine.new_position_decision(bkk(REGULAR_DAY, time(10, 30)), expiry=expiry)

    assert decision.allowed
    assert bool(decision) is True
    assert decision.reasons == ()
    assert decision.state is SessionState.MORNING_OPEN


def test_a_decision_without_contract_context_is_refused(engine: SessionEngine) -> None:
    """Section 6: the contract must come from the registry before any trading decision."""
    decision = engine.new_position_decision(bkk(REGULAR_DAY, time(10, 30)))

    assert not decision.allowed
    assert any("no contract expiry context" in reason for reason in decision.reasons)


@pytest.mark.parametrize(
    ("at", "fragment"),
    [
        (time(9, 30), "pre-open"),
        (time(12, 45), "midday break"),
        (time(13, 20), "pre-open"),
        (time(8, 0), "no continuous session"),
        (time(17, 30), "no continuous session"),
    ],
)
def test_entries_are_blocked_outside_a_continuous_session(
    engine: SessionEngine, expiry: ContractExpiry, at: time, fragment: str
) -> None:
    decision = engine.new_position_decision(bkk(REGULAR_DAY, at), expiry=expiry)

    assert not decision.allowed
    assert any(fragment in reason for reason in decision.reasons)


def test_the_afternoon_preopen_reports_both_reasons(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    """The overlap is real, so the audit log should show both, not just the first hit."""
    decision = engine.new_position_decision(bkk(REGULAR_DAY, time(13, 20)), expiry=expiry)
    joined = " | ".join(decision.reasons)

    assert "pre-open" in joined
    assert "midday break" in joined


@pytest.mark.parametrize("day", [HOLIDAY, WEEKEND])
def test_entries_are_blocked_on_a_non_trading_day(
    engine: SessionEngine, expiry: ContractExpiry, day: date
) -> None:
    decision = engine.new_position_decision(bkk(day, time(10, 30)), expiry=expiry)

    assert not decision.allowed
    assert any("not a TFEX trading day" in reason for reason in decision.reasons)


def test_entries_stop_at_the_regular_entry_cutoff(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    before = engine.new_position_decision(bkk(REGULAR_DAY, time(16, 29)), expiry=expiry)
    after = engine.new_position_decision(bkk(REGULAR_DAY, time(16, 30)), expiry=expiry)

    assert before.allowed
    assert not after.allowed
    assert any("entry cutoff" in reason for reason in after.reasons)


def test_entries_stop_once_end_of_day_flattening_is_due(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    decision = engine.new_position_decision(bkk(REGULAR_DAY, time(16, 51)), expiry=expiry)
    assert not decision.allowed
    assert any("flatten time" in reason for reason in decision.reasons)


def test_the_last_trading_day_uses_the_stricter_cutoff(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    allowed = engine.new_position_decision(bkk(LAST_TRADING_DAY, time(15, 44)), expiry=expiry)
    blocked = engine.new_position_decision(bkk(LAST_TRADING_DAY, time(15, 46)), expiry=expiry)

    assert allowed.allowed
    assert not blocked.allowed
    assert any("last-trading-day entry cutoff" in reason for reason in blocked.reasons)


def test_the_closing_window_blocks_entries_but_the_market_is_still_open(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    at = bkk(LAST_TRADING_DAY, time(16, 20))

    assert not engine.new_position_decision(at, expiry=expiry).allowed
    assert engine.exit_decision(at, expiry=expiry).allowed
    assert engine.is_executable(at, expiry=expiry)


def test_nothing_is_tradable_after_cessation_on_the_last_trading_day(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    at = bkk(LAST_TRADING_DAY, time(16, 40))

    assert not engine.new_position_decision(at, expiry=expiry).allowed
    assert not engine.exit_decision(at, expiry=expiry).allowed
    assert engine.state_at(at, expiry=expiry) is SessionState.POST_CLOSE


def test_an_unknown_calendar_year_blocks_entries(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    """Section 9: no new positions while the calendar is unknown or stale."""
    decision = engine.new_position_decision(bkk(date(2031, 6, 16), time(10, 30)), expiry=expiry)

    assert not decision.allowed
    assert any("calendar data unusable" in reason for reason in decision.reasons)


def test_a_failing_data_quality_gate_blocks_entries(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    decision = engine.new_position_decision(
        bkk(REGULAR_DAY, time(10, 30)),
        expiry=expiry,
        data_quality_ok=False,
        data_quality_reason="missing 5m bar at 10:25",
    )

    assert not decision.allowed
    assert "missing 5m bar at 10:25" in decision.reasons


def test_a_naive_timestamp_is_refused_rather_than_guessed(engine: SessionEngine) -> None:
    decision = engine.new_position_decision(datetime(2026, 12, 23, 10, 30))
    assert not decision.allowed
    assert any("timezone-aware" in reason for reason in decision.reasons)


def test_raise_if_denied_carries_the_reasons(engine: SessionEngine, expiry: ContractExpiry) -> None:
    decision = engine.new_position_decision(bkk(REGULAR_DAY, time(12, 45)), expiry=expiry)
    with pytest.raises(SessionNotEligibleError, match="midday break"):
        decision.raise_if_denied()

    engine.new_position_decision(bkk(REGULAR_DAY, time(10, 30)), expiry=expiry).raise_if_denied()


# --- exits ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "allowed"),
    [
        (time(10, 30), True),
        (time(12, 45), False),
        (time(13, 20), False),
        (time(14, 30), True),
        (time(16, 54), True),
        (time(17, 30), False),
    ],
)
def test_exits_are_permitted_only_while_the_market_matches_trades(
    engine: SessionEngine, expiry: ContractExpiry, at: time, allowed: bool
) -> None:
    """Section 9/24: exits are allowed where the exchange permits them, never fabricated."""
    assert engine.exit_decision(bkk(REGULAR_DAY, at), expiry=expiry).allowed is allowed


def test_an_exit_denial_explains_that_it_cannot_be_fabricated(
    engine: SessionEngine, expiry: ContractExpiry
) -> None:
    decision = engine.exit_decision(bkk(REGULAR_DAY, time(12, 45)), expiry=expiry)
    assert any("cannot be fabricated" in reason for reason in decision.reasons)


# --- flattening ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "at", "flattening"),
    [
        (REGULAR_DAY, time(16, 49), False),
        (REGULAR_DAY, time(16, 50), True),
        (REGULAR_DAY, time(16, 54), True),
        (REGULAR_DAY, time(16, 55), False),  # closed; there is nothing left to do
        (LAST_TRADING_DAY, time(16, 14), False),
        (LAST_TRADING_DAY, time(16, 15), True),
        (LAST_TRADING_DAY, time(16, 29), True),
        (LAST_TRADING_DAY, time(16, 30), False),
    ],
)
def test_flattening_starts_before_the_close(
    engine: SessionEngine, expiry: ContractExpiry, day: date, at: time, flattening: bool
) -> None:
    assert engine.should_flatten(bkk(day, at), expiry=expiry) is flattening


def test_no_flattening_on_a_non_trading_day(engine: SessionEngine, expiry: ContractExpiry) -> None:
    assert engine.should_flatten(bkk(HOLIDAY, time(16, 50)), expiry=expiry) is False


# --- plans -----------------------------------------------------------------------------------


def test_the_same_date_is_a_different_plan_for_a_different_contract(
    engine: SessionEngine, expiry: ContractExpiry, calendar: TradingCalendar
) -> None:
    """29 Dec is cessation day for Z26 and an ordinary session for H27."""
    march = calendar.contract_expiry(2027, 3, resolved_at=RESOLVED_AT)

    expiring = engine.plan_for(LAST_TRADING_DAY, expiry=expiry)
    ordinary = engine.plan_for(LAST_TRADING_DAY, expiry=march)

    assert expiring.is_last_trading_day
    assert expiring.afternoon_close_at == bkk(LAST_TRADING_DAY, time(16, 30))
    assert not ordinary.is_last_trading_day
    assert ordinary.afternoon_close_at == bkk(LAST_TRADING_DAY, time(16, 55))
