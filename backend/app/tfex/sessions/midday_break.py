"""Midday-break predicates.

Section 10 and section 27 both state the same hard rule from different angles: **no candle
may span the midday break**, and no price may be forward-filled through it. Those rules are
enforced by the aggregation layer in TFEX-2, but the predicates they depend on belong here,
next to the session model, so there is exactly one definition of "crosses the break".

The break is not a fixed 12:30-13:45 window. An announced early morning close lengthens it,
so every function takes a :class:`DaySessionPlan` rather than reading configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.tfex.errors import SessionError
from app.tfex.sessions.boundaries import DaySessionPlan, SessionPhase, SessionState

__all__ = [
    "BreakCrossing",
    "assert_does_not_span_break",
    "break_phase",
    "is_in_midday_break",
    "spans_midday_break",
]


@dataclass(frozen=True, slots=True)
class BreakCrossing:
    """Why a proposed interval is illegal, in enough detail to fix the caller."""

    crosses: bool
    break_start: datetime | None
    break_end: datetime | None
    reason: str

    def __bool__(self) -> bool:
        return self.crosses


def break_phase(plan: DaySessionPlan) -> SessionPhase | None:
    """The midday-break phase of ``plan``, or ``None`` on a non-trading day."""
    return plan.phase(SessionState.MIDDAY_BREAK)


def is_in_midday_break(plan: DaySessionPlan, moment: datetime) -> bool:
    """True when ``moment`` falls in the break.

    The afternoon pre-open overlaps the break, so this stays true at 13:20 even though the
    primary state is ``AFTERNOON_PREOPEN``. That is deliberate: for the purpose of "may a
    bar cover this instant?", the answer at 13:20 is still no.
    """
    return SessionState.MIDDAY_BREAK in plan.states_at(moment)


def spans_midday_break(plan: DaySessionPlan, start: datetime, end: datetime) -> BreakCrossing:
    """Test a half-open interval ``[start, end)`` against the break.

    Touching a boundary is fine: a bar ending exactly at 12:30 and a bar starting exactly at
    13:45 are both legal. Only an interval with real overlap inside the break is a crossing.
    """
    if start >= end:
        raise ValueError(f"interval start {start} must be before end {end}")

    phase = break_phase(plan)
    if phase is None:
        return BreakCrossing(False, None, None, "no midday break on a non-trading day")

    overlaps = start < phase.end and end > phase.start
    if not overlaps:
        return BreakCrossing(False, phase.start, phase.end, "interval does not touch the break")

    return BreakCrossing(
        True,
        phase.start,
        phase.end,
        f"interval [{start.isoformat()}, {end.isoformat()}) overlaps the midday break "
        f"[{phase.start.isoformat()}, {phase.end.isoformat()})",
    )


def assert_does_not_span_break(plan: DaySessionPlan, start: datetime, end: datetime) -> None:
    """Raise when a bar or order window would cross the break.

    Raises:
        SessionError: the interval crosses the midday break.
    """
    crossing = spans_midday_break(plan, start, end)
    if crossing:
        raise SessionError(
            f"{crossing.reason}; CLAUDE_TFEX.md section 10 forbids a bar spanning the "
            f"midday break, and section 24 forbids fabricated fills during it"
        )
