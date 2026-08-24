"""Session phases and boundary instants (`CLAUDE_TFEX.md` sections 8 and 9)."""

from __future__ import annotations

from datetime import date, time

import pytest

from app.tfex.calendar.models import ShortenedSession
from app.tfex.config import TfexConfig
from app.tfex.sessions.boundaries import (
    EXECUTABLE_STATES,
    DaySessionPlan,
    SessionState,
    build_day_plan,
)
from tests.tfex.conftest import bkk

REGULAR_DAY = date(2026, 12, 23)  # Wednesday, ordinary session
LAST_TRADING_DAY = date(2026, 12, 29)  # last trading day of the December 2026 contract


def regular_plan(config: TfexConfig) -> DaySessionPlan:
    return build_day_plan(config, REGULAR_DAY, is_trading_day=True)


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (time(0, 0), SessionState.CLOSED),
        (time(9, 14, 59), SessionState.CLOSED),
        (time(9, 15), SessionState.MORNING_PREOPEN),
        (time(9, 44, 59), SessionState.MORNING_PREOPEN),
        (time(9, 45), SessionState.MORNING_OPEN),
        (time(12, 29, 59), SessionState.MORNING_OPEN),
        (time(12, 30), SessionState.MIDDAY_BREAK),
        (time(13, 14, 59), SessionState.MIDDAY_BREAK),
        (time(13, 15), SessionState.AFTERNOON_PREOPEN),
        (time(13, 44, 59), SessionState.AFTERNOON_PREOPEN),
        (time(13, 45), SessionState.AFTERNOON_OPEN),
        (time(16, 54, 59), SessionState.AFTERNOON_OPEN),
        (time(16, 55), SessionState.POST_CLOSE),
        (time(23, 59, 59), SessionState.POST_CLOSE),
    ],
)
def test_primary_state_across_a_regular_day(
    config: TfexConfig, at: time, expected: SessionState
) -> None:
    assert regular_plan(config).state_at(bkk(REGULAR_DAY, at)) is expected


def test_intervals_are_half_open_so_no_instant_belongs_to_two_sequential_phases(
    config: TfexConfig,
) -> None:
    """12:30:00 is already the break; 16:55:00 is already post-close."""
    plan = regular_plan(config)
    assert plan.state_at(bkk(REGULAR_DAY, time(12, 30))) is SessionState.MIDDAY_BREAK
    assert plan.state_at(bkk(REGULAR_DAY, time(16, 55))) is SessionState.POST_CLOSE
    assert plan.state_at(bkk(REGULAR_DAY, time(9, 45))) is SessionState.MORNING_OPEN


def test_the_midday_break_and_afternoon_preopen_overlap_is_reported_as_both(
    config: TfexConfig,
) -> None:
    """Section 9: model the overlap explicitly, do not flatten it into one phase."""
    plan = regular_plan(config)
    states = plan.states_at(bkk(REGULAR_DAY, time(13, 20)))

    assert states == {SessionState.MIDDAY_BREAK, SessionState.AFTERNOON_PREOPEN}
    assert plan.state_at(bkk(REGULAR_DAY, time(13, 20))) is SessionState.AFTERNOON_PREOPEN


@pytest.mark.parametrize(
    ("at", "executable"),
    [
        (time(9, 30), False),  # pre-open
        (time(10, 0), True),
        (time(12, 30), False),  # break
        (time(13, 20), False),  # afternoon pre-open, still inside the break
        (time(14, 0), True),
        (time(17, 0), False),
    ],
)
def test_only_continuous_sessions_are_executable(
    config: TfexConfig, at: time, executable: bool
) -> None:
    """Section 24: nothing may fabricate a fill outside a continuous session."""
    assert regular_plan(config).is_executable(bkk(REGULAR_DAY, at)) is executable


def test_executable_states_are_exactly_the_two_continuous_sessions() -> None:
    actual = set(EXECUTABLE_STATES)
    assert actual == {SessionState.MORNING_OPEN, SessionState.AFTERNOON_OPEN}


def test_a_non_trading_day_is_closed_all_day(config: TfexConfig) -> None:
    plan = build_day_plan(config, date(2026, 12, 26), is_trading_day=False)

    assert plan.is_trading_day is False
    assert plan.phases[0].state is SessionState.CLOSED
    assert len(plan.phases) == 1
    assert plan.state_at(bkk(date(2026, 12, 26), time(10, 0))) is SessionState.CLOSED
    assert plan.entry_cutoff_at is None
    assert plan.morning_open_at is None


def test_regular_day_cutoff_and_flatten_times(config: TfexConfig) -> None:
    plan = regular_plan(config)

    assert plan.entry_cutoff_at == bkk(REGULAR_DAY, time(16, 30))
    assert plan.flatten_at == bkk(REGULAR_DAY, time(16, 50))  # 16:55 close minus 5 minutes
    assert plan.afternoon_close_at == bkk(REGULAR_DAY, time(16, 55))


# --- last trading day -------------------------------------------------------------------


def last_trading_day_plan(config: TfexConfig) -> DaySessionPlan:
    return build_day_plan(
        config,
        LAST_TRADING_DAY,
        is_trading_day=True,
        is_last_trading_day=True,
        cessation_time=time(16, 30),
    )


def test_the_afternoon_session_ends_at_cessation_on_the_last_trading_day(
    config: TfexConfig,
) -> None:
    plan = last_trading_day_plan(config)

    assert plan.afternoon_close_at == bkk(LAST_TRADING_DAY, time(16, 30))
    assert plan.is_executable(bkk(LAST_TRADING_DAY, time(16, 29)))
    assert not plan.is_executable(bkk(LAST_TRADING_DAY, time(16, 30)))
    assert plan.state_at(bkk(LAST_TRADING_DAY, time(16, 40))) is SessionState.POST_CLOSE


def test_the_closing_window_is_visible_while_the_market_is_still_open(
    config: TfexConfig,
) -> None:
    plan = last_trading_day_plan(config)
    at = bkk(LAST_TRADING_DAY, time(16, 20))

    assert plan.state_at(at) is SessionState.LAST_TRADING_DAY_CLOSING_WINDOW
    assert SessionState.AFTERNOON_OPEN in plan.states_at(at)
    assert plan.is_executable(at)


def test_last_trading_day_uses_the_stricter_entry_cutoff(config: TfexConfig) -> None:
    plan = last_trading_day_plan(config)

    assert plan.entry_cutoff_at == bkk(LAST_TRADING_DAY, time(15, 45))
    assert plan.flatten_at == bkk(LAST_TRADING_DAY, time(16, 15))  # 16:30 minus 15 minutes


def test_a_regular_day_has_no_closing_window_phase(config: TfexConfig) -> None:
    assert regular_plan(config).phase(SessionState.LAST_TRADING_DAY_CLOSING_WINDOW) is None


# --- shortened sessions ------------------------------------------------------------------


def test_an_early_afternoon_close_truncates_the_session(config: TfexConfig) -> None:
    plan = build_day_plan(
        config,
        REGULAR_DAY,
        is_trading_day=True,
        shortened=ShortenedSession(
            session_date=REGULAR_DAY, afternoon_close=time(15, 0), reason="fixture early close"
        ),
    )

    assert plan.afternoon_close_at == bkk(REGULAR_DAY, time(15, 0))
    assert plan.state_at(bkk(REGULAR_DAY, time(15, 30))) is SessionState.POST_CLOSE
    assert not plan.is_executable(bkk(REGULAR_DAY, time(15, 30)))
    assert plan.entry_cutoff_at == bkk(REGULAR_DAY, time(15, 0))
    assert plan.shortened is True


def test_an_early_morning_close_lengthens_the_break_rather_than_leaving_a_gap(
    config: TfexConfig,
) -> None:
    plan = build_day_plan(
        config,
        REGULAR_DAY,
        is_trading_day=True,
        shortened=ShortenedSession(
            session_date=REGULAR_DAY, morning_close=time(11, 30), reason="fixture early close"
        ),
    )

    assert plan.morning_close_at == bkk(REGULAR_DAY, time(11, 30))
    assert plan.state_at(bkk(REGULAR_DAY, time(12, 0))) is SessionState.MIDDAY_BREAK
    assert not plan.is_executable(bkk(REGULAR_DAY, time(12, 0)))

    break_phase = plan.phase(SessionState.MIDDAY_BREAK)
    assert break_phase is not None
    assert break_phase.start == bkk(REGULAR_DAY, time(11, 30))
    assert break_phase.end == bkk(REGULAR_DAY, time(13, 45))


def test_an_announced_close_outside_its_session_is_rejected(config: TfexConfig) -> None:
    with pytest.raises(ValueError, match="outside the afternoon session"):
        build_day_plan(
            config,
            REGULAR_DAY,
            is_trading_day=True,
            shortened=ShortenedSession(
                session_date=REGULAR_DAY, afternoon_close=time(17, 30), reason="fixture"
            ),
        )


def test_every_instant_of_a_trading_day_is_covered_by_at_least_one_phase(
    config: TfexConfig,
) -> None:
    """No unmodelled gaps: a timestamp that matches nothing would default to CLOSED silently."""
    plan = regular_plan(config)
    for hour in range(24):
        for minute in (0, 15, 30, 45):
            moment = bkk(REGULAR_DAY, time(hour, minute))
            assert plan.phases_at(moment), f"no phase covers {hour:02d}:{minute:02d}"
