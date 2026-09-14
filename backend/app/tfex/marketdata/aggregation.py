"""Causal 1m-to-5m/15m aggregation aligned to independent TFEX sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.tfex.calendar.models import ContractExpiry
from app.tfex.errors import ReplayError
from app.tfex.feeds.base import MarketEvent
from app.tfex.marketdata.models import BarInterval
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine

__all__ = ["AggregatedBar", "TimeframeAggregator"]


@dataclass(frozen=True, slots=True)
class AggregatedBar:
    """A higher-timeframe bar, either explicitly forming or immutably confirmed."""

    symbol: str
    interval: BarInterval
    session: ContinuousSession
    open_time: datetime
    close_time: datetime
    event_time: datetime
    confirmed_at: datetime | None
    is_closed: bool
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_bar_count: int
    expected_source_bar_count: int
    first_source_sequence: int
    last_source_sequence: int
    trade_count: int | None = None
    open_interest: int | None = None
    settlement_price: Decimal | None = None

    @property
    def is_short_session_close_bucket(self) -> bool:
        return self.expected_source_bar_count < self.interval.minutes


@dataclass(slots=True)
class _Bucket:
    symbol: str
    session: ContinuousSession
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_bar_count: int
    expected_source_bar_count: int
    first_source_sequence: int
    last_source_sequence: int
    last_timestamp: datetime
    trade_count: int | None
    open_interest: int | None
    settlement_price: Decimal | None


class TimeframeAggregator:
    """Incrementally aggregate closed one-minute events without seeing a future event."""

    def __init__(
        self,
        interval: BarInterval,
        session_engine: SessionEngine,
        *,
        expiry: ContractExpiry | None = None,
    ) -> None:
        if interval not in {BarInterval.FIVE_MINUTE, BarInterval.FIFTEEN_MINUTE}:
            raise ValueError("higher-timeframe aggregation supports only 5m and 15m")
        self.interval = interval
        self._sessions = session_engine
        self._expiry = expiry
        self._active: _Bucket | None = None
        self._confirmed: list[AggregatedBar] = []
        self._last_source_timestamp: datetime | None = None
        self._last_source_session: ContinuousSession | None = None

    @property
    def confirmed(self) -> tuple[AggregatedBar, ...]:
        return tuple(self._confirmed)

    @property
    def forming(self) -> AggregatedBar | None:
        if self._active is None:
            return None
        return self._materialize(self._active, is_closed=False, confirmed_at=None)

    def update(self, event: MarketEvent) -> AggregatedBar | None:
        bar = event.bar
        plan = self._sessions.plan_for(bar.trading_date, expiry=self._expiry)
        session = plan.continuous_session_at(bar.timestamp)
        if session is None:
            raise ReplayError(f"source bar {bar.timestamp.isoformat()} is outside a session")

        session_open, session_close = (
            (plan.morning_open_at, plan.morning_close_at)
            if session is ContinuousSession.MORNING
            else (plan.afternoon_open_at, plan.afternoon_close_at)
        )
        if session_open is None or session_close is None:
            raise ReplayError("trading-day session plan is missing continuous boundaries")
        if (
            self._last_source_timestamp is not None
            and self._last_source_session is session
            and self._last_source_timestamp.date() == bar.timestamp.date()
            and bar.timestamp != self._last_source_timestamp + timedelta(minutes=1)
        ):
            raise ReplayError(
                f"non-contiguous 1m input inside {session.value}: expected "
                f"{(self._last_source_timestamp + timedelta(minutes=1)).isoformat()}, got "
                f"{bar.timestamp.isoformat()}"
            )
        source_close = bar.timestamp + timedelta(minutes=1)
        if bar.timestamp < session_open or source_close > session_close:
            raise ReplayError(
                f"1m bar [{bar.timestamp.isoformat()}, {source_close.isoformat()}) crosses "
                "a session boundary"
            )

        elapsed_minutes = int((bar.timestamp - session_open).total_seconds() // 60)
        bucket_number = elapsed_minutes // self.interval.minutes
        bucket_open = session_open + timedelta(minutes=bucket_number * self.interval.minutes)
        bucket_close = min(
            bucket_open + timedelta(minutes=self.interval.minutes),
            session_close,
        )
        expected = int((bucket_close - bucket_open).total_seconds() // 60)

        if self._active is None:
            self._active = _Bucket(
                symbol=bar.symbol,
                session=session,
                open_time=bucket_open,
                close_time=bucket_close,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source_bar_count=1,
                expected_source_bar_count=expected,
                first_source_sequence=event.sequence,
                last_source_sequence=event.sequence,
                last_timestamp=bar.timestamp,
                trade_count=bar.trade_count,
                open_interest=bar.open_interest,
                settlement_price=bar.settlement_price,
            )
        else:
            active = self._active
            if active.open_time != bucket_open or active.session is not session:
                raise ReplayError(
                    f"{self.interval.value} bucket {active.open_time.isoformat()} did not "
                    "receive every 1m constituent before the next bucket"
                )
            expected_timestamp = active.last_timestamp + timedelta(minutes=1)
            if bar.timestamp != expected_timestamp:
                raise ReplayError(
                    f"non-contiguous 1m input inside {self.interval.value} bucket: expected "
                    f"{expected_timestamp.isoformat()}, got {bar.timestamp.isoformat()}"
                )
            active.high = max(active.high, bar.high)
            active.low = min(active.low, bar.low)
            active.close = bar.close
            active.volume += bar.volume
            active.source_bar_count += 1
            active.last_source_sequence = event.sequence
            active.last_timestamp = bar.timestamp
            active.trade_count = (
                active.trade_count + bar.trade_count
                if active.trade_count is not None and bar.trade_count is not None
                else None
            )
            active.open_interest = bar.open_interest
            if bar.settlement_price is not None:
                active.settlement_price = bar.settlement_price

        if source_close < bucket_close:
            self._last_source_timestamp = bar.timestamp
            self._last_source_session = session
            return None
        if source_close > bucket_close:
            raise ReplayError("source bar closes after its higher-timeframe bucket")

        completed = self._active
        if completed is None or completed.source_bar_count != completed.expected_source_bar_count:
            raise ReplayError(f"incomplete {self.interval.value} bucket cannot be confirmed")
        result = self._materialize(completed, is_closed=True, confirmed_at=bucket_close)
        self._confirmed.append(result)
        self._active = None
        self._last_source_timestamp = bar.timestamp
        self._last_source_session = session
        return result

    def _materialize(
        self,
        bucket: _Bucket,
        *,
        is_closed: bool,
        confirmed_at: datetime | None,
    ) -> AggregatedBar:
        return AggregatedBar(
            symbol=bucket.symbol,
            interval=self.interval,
            session=bucket.session,
            open_time=bucket.open_time,
            close_time=bucket.close_time,
            event_time=bucket.last_timestamp,
            confirmed_at=confirmed_at,
            is_closed=is_closed,
            open=bucket.open,
            high=bucket.high,
            low=bucket.low,
            close=bucket.close,
            volume=bucket.volume,
            source_bar_count=bucket.source_bar_count,
            expected_source_bar_count=bucket.expected_source_bar_count,
            first_source_sequence=bucket.first_source_sequence,
            last_source_sequence=bucket.last_source_sequence,
            trade_count=bucket.trade_count,
            open_interest=bucket.open_interest,
            settlement_price=bucket.settlement_price,
        )
