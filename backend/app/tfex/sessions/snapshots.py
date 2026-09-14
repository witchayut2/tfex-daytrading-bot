"""Immutable causal session profiles (`CLAUDE_TFEX.md` section 11).

Live highs and lows remain explicitly current/provisional until the session closes. Final
levels retain their true confirmation instant and are never backdated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.tfex.calendar.models import ContractExpiry
from app.tfex.feeds.base import MarketEvent
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine
from app.tfex.sessions.gaps import GapKind, GapLevel, make_gap

__all__ = [
    "ReferenceLevels",
    "SessionProfile",
    "SessionSnapshotBundle",
    "SessionSnapshotEngine",
]


@dataclass(frozen=True, slots=True)
class SessionProfile:
    symbol: str
    trading_date: date
    session: ContinuousSession | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Decimal | None
    settlement_price: Decimal | None
    event_time: datetime
    confirmed_at: datetime
    finalized_at: datetime | None
    is_final: bool


@dataclass(frozen=True, slots=True)
class ReferenceLevels:
    """Causal reference levels with provisional and final values kept distinct."""

    symbol: str
    trading_date: date
    session: ContinuousSession
    event_time: datetime
    confirmed_at: datetime
    session_open: Decimal
    current_session_high: Decimal
    current_session_low: Decimal
    confirmed_session_high: Decimal | None
    confirmed_session_low: Decimal | None
    confirmed_session_close: Decimal | None
    previous_day_open: Decimal | None
    previous_day_high: Decimal | None
    previous_day_low: Decimal | None
    previous_day_close: Decimal | None
    previous_day_settlement: Decimal | None
    previous_day_confirmed_at: datetime | None
    morning_current_high: Decimal | None
    morning_current_low: Decimal | None
    morning_confirmed_high: Decimal | None
    morning_confirmed_low: Decimal | None
    morning_confirmed_close: Decimal | None
    overnight_gap_from_close: GapLevel | None
    overnight_gap_from_settlement: GapLevel | None
    midday_gap: GapLevel | None


@dataclass(frozen=True, slots=True)
class SessionSnapshotBundle:
    full_day: SessionProfile
    morning: SessionProfile | None
    afternoon: SessionProfile | None
    previous_day: SessionProfile | None
    references: ReferenceLevels


@dataclass(slots=True)
class _Profile:
    symbol: str
    trading_date: date
    session: ContinuousSession | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    settlement_price: Decimal | None
    event_time: datetime
    confirmed_at: datetime
    finalized_at: datetime | None = None

    @classmethod
    def from_event(
        cls,
        event: MarketEvent,
        *,
        session: ContinuousSession | None,
    ) -> _Profile:
        bar = event.bar
        return cls(
            symbol=bar.symbol,
            trading_date=bar.trading_date,
            session=session,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            settlement_price=bar.settlement_price,
            event_time=event.event_time,
            confirmed_at=event.confirmed_at,
        )

    def update(self, event: MarketEvent, *, final: bool) -> None:
        bar = event.bar
        self.high = max(self.high, bar.high)
        self.low = min(self.low, bar.low)
        self.close = bar.close
        self.volume += bar.volume
        if bar.settlement_price is not None:
            self.settlement_price = bar.settlement_price
        self.event_time = event.event_time
        self.confirmed_at = event.confirmed_at
        if final:
            self.finalized_at = event.confirmed_at

    def snapshot(self, *, vwap: Decimal | None) -> SessionProfile:
        return SessionProfile(
            symbol=self.symbol,
            trading_date=self.trading_date,
            session=self.session,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            vwap=vwap,
            settlement_price=self.settlement_price,
            event_time=self.event_time,
            confirmed_at=self.confirmed_at,
            finalized_at=self.finalized_at,
            is_final=self.finalized_at is not None,
        )


class SessionSnapshotEngine:
    """Build running/final session profiles and causal gap/reference levels."""

    def __init__(
        self,
        session_engine: SessionEngine,
        *,
        expiry: ContractExpiry | None = None,
    ) -> None:
        self._sessions = session_engine
        self._expiry = expiry
        self._day: date | None = None
        self._full: _Profile | None = None
        self._morning: _Profile | None = None
        self._afternoon: _Profile | None = None
        self._previous_day: SessionProfile | None = None
        self._last_full_snapshot: SessionProfile | None = None
        self._overnight_gap_close: GapLevel | None = None
        self._overnight_gap_settlement: GapLevel | None = None
        self._midday_gap: GapLevel | None = None

    def update(
        self,
        event: MarketEvent,
        *,
        full_day_vwap: Decimal | None,
        morning_vwap: Decimal | None,
        afternoon_vwap: Decimal | None,
    ) -> SessionSnapshotBundle:
        bar = event.bar
        if self._day != bar.trading_date:
            self._begin_day(event)

        plan = self._sessions.plan_for(bar.trading_date, expiry=self._expiry)
        session_close = (
            plan.morning_close_at
            if event.continuous_session is ContinuousSession.MORNING
            else plan.afternoon_close_at
        )
        session_final = event.confirmed_at == session_close

        if self._full is None:
            raise RuntimeError("full-day session profile was not initialized")
        if self._full.event_time != event.event_time:
            self._full.update(
                event,
                final=bool(
                    event.continuous_session is ContinuousSession.AFTERNOON and session_final
                ),
            )
        elif event.continuous_session is ContinuousSession.AFTERNOON and session_final:
            self._full.finalized_at = event.confirmed_at

        if event.continuous_session is ContinuousSession.MORNING:
            if self._morning is None:
                self._morning = _Profile.from_event(event, session=ContinuousSession.MORNING)
            elif self._morning.event_time != event.event_time:
                self._morning.update(event, final=session_final)
            if session_final:
                self._morning.finalized_at = event.confirmed_at
        else:
            if self._afternoon is None:
                self._afternoon = _Profile.from_event(event, session=ContinuousSession.AFTERNOON)
                if self._morning is not None and self._morning.finalized_at is not None:
                    self._midday_gap = make_gap(
                        kind=GapKind.MIDDAY,
                        from_symbol=bar.symbol,
                        to_symbol=bar.symbol,
                        reference_price=self._morning.close,
                        opening_price=bar.open,
                        event_time=event.event_time,
                        confirmed_at=event.confirmed_at,
                    )
            elif self._afternoon.event_time != event.event_time:
                self._afternoon.update(event, final=session_final)
            if session_final:
                self._afternoon.finalized_at = event.confirmed_at

        morning = self._morning.snapshot(vwap=morning_vwap) if self._morning is not None else None
        afternoon = (
            self._afternoon.snapshot(vwap=afternoon_vwap) if self._afternoon is not None else None
        )
        full = self._full.snapshot(vwap=full_day_vwap)
        current = morning if event.continuous_session is ContinuousSession.MORNING else afternoon
        if current is None:
            raise RuntimeError("current continuous-session profile was not initialized")

        references = ReferenceLevels(
            symbol=bar.symbol,
            trading_date=bar.trading_date,
            session=event.continuous_session,
            event_time=event.event_time,
            confirmed_at=event.confirmed_at,
            session_open=current.open,
            current_session_high=current.high,
            current_session_low=current.low,
            confirmed_session_high=current.high if current.is_final else None,
            confirmed_session_low=current.low if current.is_final else None,
            confirmed_session_close=current.close if current.is_final else None,
            previous_day_open=self._previous_day.open if self._previous_day else None,
            previous_day_high=self._previous_day.high if self._previous_day else None,
            previous_day_low=self._previous_day.low if self._previous_day else None,
            previous_day_close=self._previous_day.close if self._previous_day else None,
            previous_day_settlement=(
                self._previous_day.settlement_price if self._previous_day else None
            ),
            previous_day_confirmed_at=(
                self._previous_day.finalized_at if self._previous_day else None
            ),
            morning_current_high=morning.high if morning else None,
            morning_current_low=morning.low if morning else None,
            morning_confirmed_high=morning.high if morning and morning.is_final else None,
            morning_confirmed_low=morning.low if morning and morning.is_final else None,
            morning_confirmed_close=morning.close if morning and morning.is_final else None,
            overnight_gap_from_close=self._overnight_gap_close,
            overnight_gap_from_settlement=self._overnight_gap_settlement,
            midday_gap=self._midday_gap,
        )
        self._last_full_snapshot = full
        return SessionSnapshotBundle(full, morning, afternoon, self._previous_day, references)

    def _begin_day(self, event: MarketEvent) -> None:
        new_day = event.bar.trading_date
        previous: SessionProfile | None = None
        if self._day is not None and self._last_full_snapshot is not None:
            candidate = self._last_full_snapshot
            expected = self._sessions.calendar.previous_trading_day_of(new_day)
            if candidate.is_final and candidate.trading_date == expected:
                previous = candidate

        self._day = new_day
        self._previous_day = previous
        self._full = _Profile.from_event(event, session=None)
        self._morning = None
        self._afternoon = None
        self._midday_gap = None
        if previous is None:
            self._overnight_gap_close = None
            self._overnight_gap_settlement = None
        else:
            self._overnight_gap_close = make_gap(
                kind=GapKind.OVERNIGHT_FROM_CLOSE,
                from_symbol=previous.symbol,
                to_symbol=event.bar.symbol,
                reference_price=previous.close,
                opening_price=event.bar.open,
                event_time=event.event_time,
                confirmed_at=event.confirmed_at,
            )
            self._overnight_gap_settlement = (
                make_gap(
                    kind=GapKind.OVERNIGHT_FROM_SETTLEMENT,
                    from_symbol=previous.symbol,
                    to_symbol=event.bar.symbol,
                    reference_price=previous.settlement_price,
                    opening_price=event.bar.open,
                    event_time=event.event_time,
                    confirmed_at=event.confirmed_at,
                )
                if previous.settlement_price is not None
                else None
            )
