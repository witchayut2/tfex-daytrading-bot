"""Deterministic one-event-at-a-time TFEX-2 replay and market-state pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from app.tfex.calendar.models import ContractExpiry
from app.tfex.contracts.symbol_parser import parse_symbol
from app.tfex.errors import ReplayError
from app.tfex.feeds.base import MarketEvent, ReplayStatus
from app.tfex.feeds.csv_feed import CsvReplayInput, load_csv_replay_input
from app.tfex.marketdata.aggregation import AggregatedBar, TimeframeAggregator
from app.tfex.marketdata.models import Bar, BarInterval
from app.tfex.marketdata.vwap import VwapEngine, VwapSnapshot
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine
from app.tfex.sessions.opening_range import OpeningRangeEngine, OpeningRangeSnapshot
from app.tfex.sessions.snapshots import SessionSnapshotBundle, SessionSnapshotEngine

__all__ = [
    "ReplayEngine",
    "ReplayFrame",
    "ReplayRun",
    "process_batch",
    "replay_digest",
]


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    """All causal state produced by one newly released closed one-minute bar."""

    event: MarketEvent
    confirmed_5m: AggregatedBar | None
    confirmed_15m: AggregatedBar | None
    vwap: VwapSnapshot
    opening_ranges: OpeningRangeSnapshot
    sessions: SessionSnapshotBundle


@dataclass(frozen=True, slots=True)
class ReplayRun:
    symbol: str
    source_bar_count: int
    frames: tuple[ReplayFrame, ...]
    confirmed_5m: tuple[AggregatedBar, ...]
    confirmed_15m: tuple[AggregatedBar, ...]
    digest: str
    dataset_id: str | None = None
    dataset_sha256: str | None = None


class ReplayEngine:
    """Replay immutable source bars; every derived engine sees only the released prefix."""

    def __init__(
        self,
        bars: tuple[Bar, ...] | list[Bar],
        session_engine: SessionEngine,
        *,
        expiry: ContractExpiry | None = None,
        dataset_id: str | None = None,
        dataset_sha256: str | None = None,
    ) -> None:
        self._bars = tuple(bars)
        if not self._bars:
            raise ReplayError("replay requires at least one 1m source bar")
        self._sessions = session_engine
        self._symbol = self._bars[0].symbol
        self._validate_source_identity_and_order()
        self._expiry = expiry or self._resolve_expiry()
        self._dataset_id = dataset_id
        self._dataset_sha256 = dataset_sha256
        self._status = ReplayStatus.NOT_STARTED
        self._cursor = 0
        self._history: list[ReplayFrame] = []
        self._build_processors()

    @classmethod
    def from_csv(
        cls,
        path: Path | str,
        session_engine: SessionEngine,
        *,
        require_real: bool = False,
    ) -> ReplayEngine:
        source: CsvReplayInput = load_csv_replay_input(path, require_real=require_real)
        return cls(
            source.bars,
            session_engine,
            dataset_id=source.manifest.dataset_id,
            dataset_sha256=source.manifest.sha256,
        )

    @property
    def status(self) -> ReplayStatus:
        return self._status

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def total_events(self) -> int:
        return len(self._bars)

    @property
    def history(self) -> tuple[ReplayFrame, ...]:
        return tuple(self._history)

    @property
    def confirmed_5m(self) -> tuple[AggregatedBar, ...]:
        return self._five.confirmed

    @property
    def confirmed_15m(self) -> tuple[AggregatedBar, ...]:
        return self._fifteen.confirmed

    @property
    def forming_5m(self) -> AggregatedBar | None:
        return self._five.forming

    @property
    def forming_15m(self) -> AggregatedBar | None:
        return self._fifteen.forming

    def start(self) -> None:
        if self._status is ReplayStatus.END_OF_DATA:
            raise ReplayError("replay is at end-of-data; call restart() to begin again")
        self._status = ReplayStatus.RUNNING

    def pause(self) -> None:
        if self._status is not ReplayStatus.RUNNING:
            raise ReplayError(f"cannot pause replay while status is {self._status.value}")
        self._status = ReplayStatus.PAUSED

    def next_event(self) -> ReplayFrame | None:
        if self._status is not ReplayStatus.RUNNING:
            raise ReplayError("next_event requires a running replay")
        return self._advance()

    def step(self) -> ReplayFrame | None:
        if self._status not in {ReplayStatus.RUNNING, ReplayStatus.PAUSED}:
            raise ReplayError("step requires a started or paused replay")
        return self._advance()

    def restart(self) -> None:
        """Discard derived state and begin again at bar 1."""
        self._reset()
        self._status = ReplayStatus.RUNNING

    def seek(self, position: int) -> ReplayFrame | None:
        """Reconstruct state from bar 1 through ``position``; never reuse later state."""
        if not 0 <= position <= len(self._bars):
            raise ReplayError(f"seek position {position} is outside 0..{len(self._bars)}")
        self._reset()
        self._status = ReplayStatus.RUNNING
        last: ReplayFrame | None = None
        while self._cursor < position:
            last = self._advance()
        self._status = (
            ReplayStatus.END_OF_DATA if self._cursor == len(self._bars) else ReplayStatus.PAUSED
        )
        return last

    def run_to_end(self) -> ReplayRun:
        if self._status in {ReplayStatus.NOT_STARTED, ReplayStatus.PAUSED}:
            self.start()
        while self._status is ReplayStatus.RUNNING:
            self._advance()
        frames = tuple(self._history)
        return ReplayRun(
            symbol=self._symbol,
            source_bar_count=len(self._bars),
            frames=frames,
            confirmed_5m=self.confirmed_5m,
            confirmed_15m=self.confirmed_15m,
            digest=replay_digest(frames),
            dataset_id=self._dataset_id,
            dataset_sha256=self._dataset_sha256,
        )

    def _advance(self) -> ReplayFrame | None:
        if self._cursor >= len(self._bars):
            self._status = ReplayStatus.END_OF_DATA
            return None
        bar = self._bars[self._cursor]
        plan = self._sessions.plan_for(bar.trading_date, expiry=self._expiry)
        session = plan.continuous_session_at(bar.timestamp)
        confirmed_at = bar.timestamp + timedelta(minutes=1)
        if session is None or not plan.is_executable(bar.timestamp):
            raise ReplayError(f"source bar {bar.timestamp.isoformat()} is outside TFEX trading")
        session_close = (
            plan.morning_close_at
            if session is ContinuousSession.MORNING
            else plan.afternoon_close_at
        )
        if session_close is None or confirmed_at > session_close:
            raise ReplayError(f"source bar {bar.timestamp.isoformat()} crosses session close")

        event = MarketEvent(
            sequence=self._cursor + 1,
            bar=bar,
            event_time=bar.timestamp,
            confirmed_at=confirmed_at,
            session_state=plan.state_at(bar.timestamp),
            continuous_session=session,
        )
        five = self._five.update(event)
        fifteen = self._fifteen.update(event)
        vwap = self._vwap.update(event)
        opening = self._opening.update(event)
        sessions = self._snapshots.update(
            event,
            full_day_vwap=vwap.full_day.value,
            morning_vwap=vwap.morning.value if vwap.morning is not None else None,
            afternoon_vwap=vwap.afternoon.value if vwap.afternoon is not None else None,
        )
        frame = ReplayFrame(event, five, fifteen, vwap, opening, sessions)
        self._history.append(frame)
        self._cursor += 1
        if self._cursor == len(self._bars):
            self._status = ReplayStatus.END_OF_DATA
        return frame

    def _reset(self) -> None:
        self._cursor = 0
        self._history = []
        self._status = ReplayStatus.NOT_STARTED
        self._build_processors()

    def _build_processors(self) -> None:
        self._five = TimeframeAggregator(
            BarInterval.FIVE_MINUTE, self._sessions, expiry=self._expiry
        )
        self._fifteen = TimeframeAggregator(
            BarInterval.FIFTEEN_MINUTE, self._sessions, expiry=self._expiry
        )
        self._vwap = VwapEngine(self._sessions, expiry=self._expiry)
        self._opening = OpeningRangeEngine(self._sessions, expiry=self._expiry)
        self._snapshots = SessionSnapshotEngine(self._sessions, expiry=self._expiry)

    def _resolve_expiry(self) -> ContractExpiry:
        parsed = parse_symbol(
            self._symbol,
            config=self._sessions.calendar.config,
            reference_date=self._bars[0].trading_date,
        )
        return self._sessions.calendar.contract_expiry(
            parsed.contract_year,
            parsed.contract_month,
            resolved_at=self._bars[0].timestamp,
        )

    def _validate_source_identity_and_order(self) -> None:
        previous: datetime | None = None
        for bar in self._bars:
            if bar.symbol != self._symbol:
                raise ReplayError(
                    f"raw contract changed from {self._symbol} to {bar.symbol}; continuous "
                    "or spliced replay is forbidden"
                )
            if bar.timestamp.tzinfo is None:
                raise ReplayError("replay source timestamps must be timezone-aware")
            if bar.timestamp.tzinfo != self._sessions.calendar.timezone:
                raise ReplayError("replay source timestamps must be normalized to market timezone")
            if previous is not None and bar.timestamp <= previous:
                raise ReplayError("replay source bars must be strictly chronological and unique")
            previous = bar.timestamp


def process_batch(
    bars: tuple[Bar, ...] | list[Bar],
    session_engine: SessionEngine,
    *,
    expiry: ContractExpiry | None = None,
) -> ReplayRun:
    """Reference batch API that deliberately delegates to the incremental engine."""
    return ReplayEngine(bars, session_engine, expiry=expiry).run_to_end()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def replay_digest(frames: tuple[ReplayFrame, ...] | list[ReplayFrame]) -> str:
    """Stable content hash for reproducibility checks; processing time is never included."""
    payload = json.dumps(
        _jsonable(tuple(frames)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
