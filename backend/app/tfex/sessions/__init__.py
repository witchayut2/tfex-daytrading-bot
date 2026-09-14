"""TFEX session model: phases, the midday break, and session-level trading gates."""

from app.tfex.sessions.boundaries import (
    EXECUTABLE_STATES,
    STATE_PRECEDENCE,
    ContinuousSession,
    DaySessionPlan,
    SessionPhase,
    SessionState,
    build_day_plan,
)
from app.tfex.sessions.engine import SessionEngine, SessionGateDecision
from app.tfex.sessions.midday_break import (
    BreakCrossing,
    assert_does_not_span_break,
    is_in_midday_break,
    spans_midday_break,
)

__all__ = [
    "EXECUTABLE_STATES",
    "STATE_PRECEDENCE",
    "BreakCrossing",
    "ContinuousSession",
    "DaySessionPlan",
    "SessionEngine",
    "SessionGateDecision",
    "SessionPhase",
    "SessionState",
    "assert_does_not_span_break",
    "build_day_plan",
    "is_in_midday_break",
    "spans_midday_break",
]
