"""Session phases for a single trading date (`CLAUDE_TFEX.md` section 9).

Section 9 says the overlap between the midday break (12:30-13:45) and the afternoon
pre-open (13:15-13:45) is *intentional*, and that market states must be modelled
explicitly rather than flattened into one continuous phase. This module therefore does two
distinct things:

* :meth:`DaySessionPlan.phases_at` returns **every** phase covering an instant — at 13:20
  that is both ``MIDDAY_BREAK`` and ``AFTERNOON_PREOPEN``, which is the truth.
* :meth:`DaySessionPlan.state_at` returns **one** primary state by a documented precedence,
  because dashboards and gates need a single answer.

All intervals are half-open ``[start, end)``. 12:30:00 is already the midday break; 16:55:00
is already post-close. Every timestamp is Asia/Bangkok-aware.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.tfex.calendar.models import ShortenedSession
from app.tfex.config import TfexConfig

__all__ = [
    "EXECUTABLE_STATES",
    "STATE_PRECEDENCE",
    "ContinuousSession",
    "DaySessionPlan",
    "SessionPhase",
    "SessionState",
    "build_day_plan",
]


class ContinuousSession(StrEnum):
    """The two independent TFEX continuous-trading segments."""

    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


class SessionState(StrEnum):
    """The session states enumerated in section 8."""

    CLOSED = "CLOSED"
    MORNING_PREOPEN = "MORNING_PREOPEN"
    MORNING_OPEN = "MORNING_OPEN"
    MIDDAY_BREAK = "MIDDAY_BREAK"
    AFTERNOON_PREOPEN = "AFTERNOON_PREOPEN"
    AFTERNOON_OPEN = "AFTERNOON_OPEN"
    LAST_TRADING_DAY_CLOSING_WINDOW = "LAST_TRADING_DAY_CLOSING_WINDOW"
    POST_CLOSE = "POST_CLOSE"


#: Primary-state precedence, most specific first. The last-trading-day closing window wins
#: over ``AFTERNOON_OPEN`` because its whole purpose is to be visible; the afternoon pre-open
#: wins over the midday break because it is the narrower, more informative statement.
STATE_PRECEDENCE: tuple[SessionState, ...] = (
    SessionState.LAST_TRADING_DAY_CLOSING_WINDOW,
    SessionState.AFTERNOON_PREOPEN,
    SessionState.MORNING_PREOPEN,
    SessionState.MORNING_OPEN,
    SessionState.AFTERNOON_OPEN,
    SessionState.MIDDAY_BREAK,
    SessionState.POST_CLOSE,
    SessionState.CLOSED,
)

#: States in which the exchange is matching continuous-session trades.
EXECUTABLE_STATES: frozenset[SessionState] = frozenset(
    {SessionState.MORNING_OPEN, SessionState.AFTERNOON_OPEN}
)

_PRECEDENCE_INDEX = {state: index for index, state in enumerate(STATE_PRECEDENCE)}


@dataclass(frozen=True, slots=True)
class SessionPhase:
    """One half-open ``[start, end)`` interval of a single state."""

    state: SessionState
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("session phase boundaries must be timezone-aware")
        if self.start >= self.end:
            raise ValueError(f"phase {self.state} has non-positive duration")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class DaySessionPlan:
    """The complete phase layout for one calendar date."""

    trading_date: date
    timezone_name: str
    is_trading_day: bool
    is_last_trading_day: bool
    phases: tuple[SessionPhase, ...]
    morning_open_at: datetime | None
    morning_close_at: datetime | None
    afternoon_open_at: datetime | None
    afternoon_close_at: datetime | None
    entry_cutoff_at: datetime | None
    flatten_at: datetime | None
    shortened: bool
    notes: tuple[str, ...] = ()

    # --- queries ----------------------------------------------------------------------

    def phases_at(self, moment: datetime) -> tuple[SessionPhase, ...]:
        """Every phase covering ``moment``, ordered by precedence.

        More than one is normal: the midday break and the afternoon pre-open genuinely
        overlap, and so do the afternoon session and the last-trading-day closing window.
        """
        matches = [phase for phase in self.phases if phase.contains(moment)]
        matches.sort(key=lambda p: _PRECEDENCE_INDEX[p.state])
        return tuple(matches)

    def state_at(self, moment: datetime) -> SessionState:
        """The single primary state at ``moment``, by :data:`STATE_PRECEDENCE`."""
        matches = self.phases_at(moment)
        if not matches:
            return SessionState.CLOSED
        return matches[0].state

    def states_at(self, moment: datetime) -> frozenset[SessionState]:
        return frozenset(phase.state for phase in self.phases_at(moment))

    def is_executable(self, moment: datetime) -> bool:
        """True only while the exchange is matching continuous-session trades.

        Section 24: never fabricate fills during closed periods. Anything that simulates an
        execution must consult this, not ``state_at``.
        """
        return bool(self.states_at(moment) & EXECUTABLE_STATES)

    def continuous_session_at(self, moment: datetime) -> ContinuousSession | None:
        """Return the matching continuous segment, including the LTD closing window."""
        if (
            self.morning_open_at is not None
            and self.morning_close_at is not None
            and self.morning_open_at <= moment < self.morning_close_at
        ):
            return ContinuousSession.MORNING
        if (
            self.afternoon_open_at is not None
            and self.afternoon_close_at is not None
            and self.afternoon_open_at <= moment < self.afternoon_close_at
        ):
            return ContinuousSession.AFTERNOON
        return None

    def phase(self, state: SessionState) -> SessionPhase | None:
        for candidate in self.phases:
            if candidate.state is state:
                return candidate
        return None


def _combine(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)


def build_day_plan(
    config: TfexConfig,
    trading_date: date,
    *,
    is_trading_day: bool,
    is_last_trading_day: bool = False,
    cessation_time: time | None = None,
    shortened: ShortenedSession | None = None,
) -> DaySessionPlan:
    """Compute the phase layout for ``trading_date``.

    Pure: it takes facts (is this a trading day? is it the last trading day? was an early
    close announced?) and turns them into intervals. The calendar decides those facts; this
    function never looks them up, which keeps the session layer testable without holiday
    data and keeps the dependency direction one-way.

    Args:
        cessation_time: contract-specific trading cessation on the last trading day
            (16:30 by configuration). Ignored unless ``is_last_trading_day``.
        shortened: an announced early close for this date.
    """
    tz = ZoneInfo(config.sessions.timezone)
    sessions = config.sessions
    day_start = _combine(trading_date, time(0, 0), tz)
    day_end = day_start + timedelta(days=1)
    notes: list[str] = []

    if not is_trading_day:
        return DaySessionPlan(
            trading_date=trading_date,
            timezone_name=sessions.timezone,
            is_trading_day=False,
            is_last_trading_day=False,
            phases=(SessionPhase(SessionState.CLOSED, day_start, day_end),),
            morning_open_at=None,
            morning_close_at=None,
            afternoon_open_at=None,
            afternoon_close_at=None,
            entry_cutoff_at=None,
            flatten_at=None,
            shortened=False,
            notes=("not a trading day",),
        )

    # --- resolve the two closes -------------------------------------------------------
    morning_close_time = sessions.morning.end
    if shortened is not None and shortened.morning_close is not None:
        if not sessions.morning.start < shortened.morning_close <= sessions.morning.end:
            raise ValueError(
                f"announced morning close {shortened.morning_close} is outside the morning "
                f"session {sessions.morning.start}-{sessions.morning.end}"
            )
        morning_close_time = shortened.morning_close
        notes.append(f"early morning close {morning_close_time} ({shortened.reason})")

    afternoon_close_time = sessions.afternoon.end
    if shortened is not None and shortened.afternoon_close is not None:
        if not sessions.afternoon.start < shortened.afternoon_close <= sessions.afternoon.end:
            raise ValueError(
                f"announced afternoon close {shortened.afternoon_close} is outside the "
                f"afternoon session {sessions.afternoon.start}-{sessions.afternoon.end}"
            )
        afternoon_close_time = shortened.afternoon_close
        notes.append(f"early afternoon close {afternoon_close_time} ({shortened.reason})")

    if is_last_trading_day:
        cessation = cessation_time or config.expiry.last_trading_day_cessation_time
        if cessation < afternoon_close_time:
            afternoon_close_time = cessation
        notes.append(f"last trading day: trading ceases {afternoon_close_time}")

    # --- phases -----------------------------------------------------------------------
    preopen_start = _combine(trading_date, sessions.morning_preopen.start, tz)
    morning_open = _combine(trading_date, sessions.morning.start, tz)
    morning_close = _combine(trading_date, morning_close_time, tz)
    afternoon_preopen_start = _combine(trading_date, sessions.afternoon_preopen.start, tz)
    afternoon_open = _combine(trading_date, sessions.afternoon.start, tz)
    afternoon_close = _combine(trading_date, afternoon_close_time, tz)

    phases: list[SessionPhase] = [
        SessionPhase(SessionState.CLOSED, day_start, preopen_start),
        SessionPhase(SessionState.MORNING_PREOPEN, preopen_start, morning_open),
        SessionPhase(SessionState.MORNING_OPEN, morning_open, morning_close),
        # The break runs from whenever the morning actually closed. An early morning close
        # lengthens the break; it does not create an unmodelled gap.
        SessionPhase(SessionState.MIDDAY_BREAK, morning_close, afternoon_open),
        SessionPhase(SessionState.AFTERNOON_PREOPEN, afternoon_preopen_start, afternoon_open),
        SessionPhase(SessionState.AFTERNOON_OPEN, afternoon_open, afternoon_close),
        SessionPhase(SessionState.POST_CLOSE, afternoon_close, day_end),
    ]

    if is_last_trading_day:
        window_minutes = config.expiry.closing_window_minutes
        window_start = max(afternoon_close - timedelta(minutes=window_minutes), afternoon_open)
        if window_start < afternoon_close:
            phases.append(
                SessionPhase(
                    SessionState.LAST_TRADING_DAY_CLOSING_WINDOW, window_start, afternoon_close
                )
            )

    # --- gates ------------------------------------------------------------------------
    if is_last_trading_day:
        cutoff_time = min(
            config.roll.prevent_new_positions_on_last_trading_day_after,
            sessions.entry_cutoff,
        )
        flatten = afternoon_close - timedelta(
            minutes=config.roll.force_flatten_before_last_trade_stop_minutes
        )
    else:
        cutoff_time = sessions.entry_cutoff
        flatten = afternoon_close - timedelta(
            minutes=sessions.end_of_day_flatten_minutes_before_close
        )

    entry_cutoff = min(_combine(trading_date, cutoff_time, tz), afternoon_close)
    flatten_at = max(min(flatten, afternoon_close), morning_open)

    return DaySessionPlan(
        trading_date=trading_date,
        timezone_name=sessions.timezone,
        is_trading_day=True,
        is_last_trading_day=is_last_trading_day,
        phases=tuple(phases),
        morning_open_at=morning_open,
        morning_close_at=morning_close,
        afternoon_open_at=afternoon_open,
        afternoon_close_at=afternoon_close,
        entry_cutoff_at=entry_cutoff,
        flatten_at=flatten_at,
        shortened=shortened is not None,
        notes=tuple(notes),
    )
