"""Causal morning and afternoon opening ranges (`CLAUDE_TFEX.md` section 13).

TFEX-2 provides immutable 5/15/30-minute levels. Breakout interpretation remains strategy
work: this module exposes market state and never creates a long/short decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.tfex.calendar.models import ContractExpiry
from app.tfex.errors import ReplayError
from app.tfex.feeds.base import MarketEvent
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine

__all__ = ["OpeningRangeEngine", "OpeningRangeSnapshot", "OpeningRangeState"]

_WINDOWS = (5, 15, 30)


@dataclass(frozen=True, slots=True)
class OpeningRangeState:
    symbol: str
    trading_date: date
    session: ContinuousSession
    window_minutes: int
    range_start: datetime
    range_end: datetime
    current_high: Decimal
    current_low: Decimal
    confirmed_high: Decimal | None
    confirmed_low: Decimal | None
    source_bar_count: int
    event_time: datetime
    confirmed_at: datetime | None
    is_confirmed: bool


@dataclass(frozen=True, slots=True)
class OpeningRangeSnapshot:
    ranges: tuple[OpeningRangeState, ...]

    def get(
        self,
        session: ContinuousSession,
        window_minutes: int,
    ) -> OpeningRangeState | None:
        for state in self.ranges:
            if state.session is session and state.window_minutes == window_minutes:
                return state
        return None


@dataclass(slots=True)
class _Range:
    symbol: str
    trading_date: date
    session: ContinuousSession
    window_minutes: int
    range_start: datetime
    range_end: datetime
    high: Decimal
    low: Decimal
    source_bar_count: int
    last_timestamp: datetime
    event_time: datetime
    confirmed_at: datetime | None = None

    def state(self) -> OpeningRangeState:
        confirmed = self.confirmed_at is not None
        return OpeningRangeState(
            symbol=self.symbol,
            trading_date=self.trading_date,
            session=self.session,
            window_minutes=self.window_minutes,
            range_start=self.range_start,
            range_end=self.range_end,
            current_high=self.high,
            current_low=self.low,
            confirmed_high=self.high if confirmed else None,
            confirmed_low=self.low if confirmed else None,
            source_bar_count=self.source_bar_count,
            event_time=self.event_time,
            confirmed_at=self.confirmed_at,
            is_confirmed=confirmed,
        )


class OpeningRangeEngine:
    """Build 5/15/30-minute ranges without exposing final levels early."""

    def __init__(
        self,
        session_engine: SessionEngine,
        *,
        expiry: ContractExpiry | None = None,
    ) -> None:
        self._sessions = session_engine
        self._expiry = expiry
        self._day: date | None = None
        self._ranges: dict[tuple[ContinuousSession, int], _Range] = {}

    def update(self, event: MarketEvent) -> OpeningRangeSnapshot:
        bar = event.bar
        if self._day != bar.trading_date:
            self._day = bar.trading_date
            self._ranges = {}

        plan = self._sessions.plan_for(bar.trading_date, expiry=self._expiry)
        session_start = (
            plan.morning_open_at
            if event.continuous_session is ContinuousSession.MORNING
            else plan.afternoon_open_at
        )
        if session_start is None:
            raise ReplayError("opening range requires a continuous-session start")

        for minutes in _WINDOWS:
            range_end = session_start + timedelta(minutes=minutes)
            if bar.timestamp >= range_end:
                continue
            key = (event.continuous_session, minutes)
            current = self._ranges.get(key)
            if current is None:
                if bar.timestamp != session_start:
                    raise ReplayError(
                        f"{event.continuous_session.value} {minutes}m opening range starts "
                        f"at {session_start.isoformat()}, not {bar.timestamp.isoformat()}"
                    )
                current = _Range(
                    symbol=bar.symbol,
                    trading_date=bar.trading_date,
                    session=event.continuous_session,
                    window_minutes=minutes,
                    range_start=session_start,
                    range_end=range_end,
                    high=bar.high,
                    low=bar.low,
                    source_bar_count=1,
                    last_timestamp=bar.timestamp,
                    event_time=event.event_time,
                )
                self._ranges[key] = current
            else:
                expected = current.last_timestamp + timedelta(minutes=1)
                if bar.timestamp != expected:
                    raise ReplayError(
                        f"opening range expected {expected.isoformat()}, got "
                        f"{bar.timestamp.isoformat()}"
                    )
                current.high = max(current.high, bar.high)
                current.low = min(current.low, bar.low)
                current.source_bar_count += 1
                current.last_timestamp = bar.timestamp
                current.event_time = event.event_time

            if event.confirmed_at == range_end:
                if current.source_bar_count != minutes:
                    raise ReplayError(f"incomplete {minutes}m opening range cannot be confirmed")
                current.confirmed_at = event.confirmed_at

        ordered = sorted(
            (item.state() for item in self._ranges.values()),
            key=lambda item: (
                0 if item.session is ContinuousSession.MORNING else 1,
                item.window_minutes,
            ),
        )
        return OpeningRangeSnapshot(tuple(ordered))
