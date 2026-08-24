"""The midday break as an anti-repaint boundary (`CLAUDE_TFEX.md` sections 10 and 27).

Section 27: *"No candle may span the midday break."* The aggregation that enforces it
arrives in TFEX-2; the predicate it will use is tested here.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from app.tfex.calendar.models import ShortenedSession
from app.tfex.config import TfexConfig
from app.tfex.errors import SessionError
from app.tfex.sessions.boundaries import DaySessionPlan, build_day_plan
from app.tfex.sessions.midday_break import (
    assert_does_not_span_break,
    break_phase,
    is_in_midday_break,
    spans_midday_break,
)
from tests.tfex.conftest import bkk

DAY = date(2026, 12, 23)


@pytest.fixture
def plan(config: TfexConfig) -> DaySessionPlan:
    return build_day_plan(config, DAY, is_trading_day=True)


def test_the_break_runs_from_the_morning_close_to_the_afternoon_open(
    plan: DaySessionPlan,
) -> None:
    phase = break_phase(plan)
    assert phase is not None
    assert phase.start == bkk(DAY, time(12, 30))
    assert phase.end == bkk(DAY, time(13, 45))


@pytest.mark.parametrize(
    ("at", "inside"),
    [
        (time(12, 29, 59), False),
        (time(12, 30), True),
        (time(13, 0), True),
        (time(13, 20), True),  # afternoon pre-open overlaps the break
        (time(13, 44, 59), True),
        (time(13, 45), False),
    ],
)
def test_is_in_midday_break_covers_the_overlapping_preopen(
    plan: DaySessionPlan, at: time, inside: bool
) -> None:
    assert is_in_midday_break(plan, bkk(DAY, at)) is inside


@pytest.mark.anti_repaint
@pytest.mark.parametrize(
    ("start", "end", "crosses"),
    [
        (time(12, 15), time(12, 30), False),  # a bar ending exactly at the close is legal
        (time(13, 45), time(14, 0), False),  # a bar starting exactly at the reopen is legal
        (time(12, 25), time(12, 35), True),  # straddles the close
        (time(12, 15), time(13, 45), True),  # morning bar stretched over the break
        (time(12, 30), time(13, 45), True),  # a "bar" that is the break
        (time(13, 40), time(13, 50), True),  # straddles the reopen
        (time(11, 0), time(16, 0), True),  # a whole-day bar
        (time(10, 0), time(10, 15), False),
        (time(14, 0), time(14, 15), False),
    ],
)
def test_bars_may_touch_the_break_boundaries_but_never_cross_them(
    plan: DaySessionPlan, start: time, end: time, crosses: bool
) -> None:
    result = spans_midday_break(plan, bkk(DAY, start), bkk(DAY, end))
    assert bool(result) is crosses


@pytest.mark.anti_repaint
def test_assert_does_not_span_break_raises_with_the_rule_it_protects(
    plan: DaySessionPlan,
) -> None:
    with pytest.raises(SessionError, match="section 10"):
        assert_does_not_span_break(plan, bkk(DAY, time(12, 25)), bkk(DAY, time(12, 35)))


def test_a_legal_bar_passes_the_assertion(plan: DaySessionPlan) -> None:
    assert_does_not_span_break(plan, bkk(DAY, time(12, 15)), bkk(DAY, time(12, 30)))
    assert_does_not_span_break(plan, bkk(DAY, time(13, 45)), bkk(DAY, time(14, 0)))


def test_a_reversed_interval_is_a_programming_error(plan: DaySessionPlan) -> None:
    with pytest.raises(ValueError, match="must be before end"):
        spans_midday_break(plan, bkk(DAY, time(14, 0)), bkk(DAY, time(13, 0)))


@pytest.mark.anti_repaint
def test_an_early_morning_close_moves_the_boundary_a_bar_must_respect(
    config: TfexConfig,
) -> None:
    """A hard-coded 12:30 would let a bar cover 11:45-12:00 on an early-close day."""
    plan = build_day_plan(
        config,
        DAY,
        is_trading_day=True,
        shortened=ShortenedSession(
            session_date=DAY, morning_close=time(11, 30), reason="fixture early close"
        ),
    )
    assert spans_midday_break(plan, bkk(DAY, time(11, 45)), bkk(DAY, time(12, 0)))
    assert not spans_midday_break(plan, bkk(DAY, time(11, 15)), bkk(DAY, time(11, 30)))


def test_a_non_trading_day_has_no_break_to_cross(config: TfexConfig) -> None:
    plan = build_day_plan(config, date(2026, 12, 26), is_trading_day=False)
    assert break_phase(plan) is None
    assert not spans_midday_break(plan, bkk(DAY, time(12, 0)), bkk(DAY, time(14, 0)))
