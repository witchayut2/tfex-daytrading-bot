"""Causal full-day and independent-session VWAP for TFEX one-minute replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.calendar.models import ContractExpiry
from app.tfex.feeds.base import MarketEvent
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine

__all__ = ["VwapEngine", "VwapMode", "VwapSnapshot", "VwapState"]


class VwapMode(StrEnum):
    FULL_DAY = "FULL_DAY"
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


@dataclass(frozen=True, slots=True)
class VwapState:
    symbol: str
    trading_date: date
    mode: VwapMode
    price_basis: str
    cumulative_price_volume: Decimal
    cumulative_volume: int
    value: Decimal | None
    event_time: datetime
    confirmed_at: datetime
    is_final: bool


@dataclass(frozen=True, slots=True)
class VwapSnapshot:
    full_day: VwapState
    morning: VwapState | None
    afternoon: VwapState | None


@dataclass(slots=True)
class _Accumulator:
    symbol: str
    trading_date: date
    mode: VwapMode
    price_volume: Decimal = Decimal(0)
    volume: int = 0
    event_time: datetime | None = None
    confirmed_at: datetime | None = None
    is_final: bool = False

    def update(self, event: MarketEvent, *, final: bool) -> VwapState:
        bar = event.bar
        # Canonical TFEX-2 basis: typical price (H + L + C) / 3, weighted by bar volume.
        typical_price = (bar.high + bar.low + bar.close) / Decimal(3)
        self.price_volume += typical_price * bar.volume
        self.volume += bar.volume
        self.event_time = event.event_time
        self.confirmed_at = event.confirmed_at
        self.is_final = final
        return self.snapshot()

    def snapshot(self) -> VwapState:
        if self.event_time is None or self.confirmed_at is None:
            raise RuntimeError("VWAP accumulator has no market event")
        return VwapState(
            symbol=self.symbol,
            trading_date=self.trading_date,
            mode=self.mode,
            price_basis="TYPICAL_PRICE_HLC3",
            cumulative_price_volume=self.price_volume,
            cumulative_volume=self.volume,
            value=self.price_volume / self.volume if self.volume else None,
            event_time=self.event_time,
            confirmed_at=self.confirmed_at,
            is_final=self.is_final,
        )


class VwapEngine:
    """Update three VWAP modes from each released, closed one-minute event."""

    def __init__(
        self,
        session_engine: SessionEngine,
        *,
        expiry: ContractExpiry | None = None,
    ) -> None:
        self._sessions = session_engine
        self._expiry = expiry
        self._day: date | None = None
        self._full: _Accumulator | None = None
        self._morning: _Accumulator | None = None
        self._afternoon: _Accumulator | None = None

    def update(self, event: MarketEvent) -> VwapSnapshot:
        bar = event.bar
        if self._day != bar.trading_date:
            self._day = bar.trading_date
            self._full = _Accumulator(bar.symbol, bar.trading_date, VwapMode.FULL_DAY)
            self._morning = None
            self._afternoon = None

        plan = self._sessions.plan_for(bar.trading_date, expiry=self._expiry)
        session_close = (
            plan.morning_close_at
            if event.continuous_session is ContinuousSession.MORNING
            else plan.afternoon_close_at
        )
        if session_close is None:
            raise RuntimeError("trading session has no close boundary")
        session_final = event.confirmed_at == session_close

        if self._full is None:
            raise RuntimeError("full-day VWAP accumulator was not initialized")
        full_final = bool(event.continuous_session is ContinuousSession.AFTERNOON and session_final)
        full = self._full.update(event, final=full_final)

        morning: VwapState | None
        afternoon: VwapState | None
        if event.continuous_session is ContinuousSession.MORNING:
            if self._morning is None:
                self._morning = _Accumulator(bar.symbol, bar.trading_date, VwapMode.MORNING)
            morning = self._morning.update(event, final=session_final)
            afternoon = self._afternoon.snapshot() if self._afternoon is not None else None
        else:
            if self._afternoon is None:
                self._afternoon = _Accumulator(bar.symbol, bar.trading_date, VwapMode.AFTERNOON)
            afternoon = self._afternoon.update(event, final=session_final)
            morning = self._morning.snapshot() if self._morning is not None else None

        return VwapSnapshot(full_day=full, morning=morning, afternoon=afternoon)
