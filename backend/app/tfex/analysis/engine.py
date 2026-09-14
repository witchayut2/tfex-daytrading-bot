"""TFEX-3 orchestration over immutable TFEX-2 replay frames."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.tfex.analysis.fvg import FairValueGap, FvgEngine, FvgUpdate
from app.tfex.analysis.models import AnalysisBar
from app.tfex.analysis.order_blocks import (
    OrderBlock,
    OrderBlockEngine,
    OrderBlockSelection,
    OrderBlockUpdate,
)
from app.tfex.analysis.pivots import ConfirmedPivot, PivotRule
from app.tfex.analysis.regime import (
    CompositeRegime,
    StructureRegimeEngine,
    VolatilityClassifier,
)
from app.tfex.analysis.structure import (
    MarketStructureEngine,
    StructureBias,
    StructureBreak,
    StructureUpdate,
    SwingClassification,
)
from app.tfex.errors import ReplayError
from app.tfex.liquidity.engine import LiquidityEngine
from app.tfex.liquidity.importance import LiquidityImportanceEngine, LiquidityImportanceVector
from app.tfex.liquidity.levels import LiquidityLevel
from app.tfex.liquidity.session_levels import SessionLiquiditySourceEngine
from app.tfex.liquidity.sweep import LiquidityInteraction, LiquiditySweep
from app.tfex.marketdata.aggregation import AggregatedBar
from app.tfex.marketdata.models import BarInterval
from app.tfex.marketdata.replay import ReplayFrame, ReplayRun

__all__ = [
    "Tfex3Engine",
    "Tfex3Frame",
    "Tfex3Run",
    "TimeframeBias",
    "analysis_digest",
]

_TIMEFRAMES = (
    BarInterval.ONE_MINUTE,
    BarInterval.FIVE_MINUTE,
    BarInterval.FIFTEEN_MINUTE,
)


@dataclass(frozen=True, slots=True)
class TimeframeBias:
    timeframe: BarInterval
    bias: StructureBias


@dataclass(frozen=True, slots=True)
class Tfex3Frame:
    source_sequence: int
    event_time: datetime
    confirmed_at: datetime
    structure_updates: tuple[StructureUpdate, ...]
    fvg_updates: tuple[FvgUpdate, ...]
    order_block_updates: tuple[OrderBlockUpdate, ...]
    new_liquidity_levels: tuple[LiquidityLevel, ...]
    liquidity_interactions: tuple[LiquidityInteraction, ...]
    new_sweeps: tuple[LiquiditySweep, ...]
    biases: tuple[TimeframeBias, ...]
    regime: CompositeRegime


@dataclass(frozen=True, slots=True)
class Tfex3Run:
    symbol: str
    source_bar_count: int
    frames: tuple[Tfex3Frame, ...]
    pivots: tuple[ConfirmedPivot, ...]
    swings: tuple[SwingClassification, ...]
    structure_breaks: tuple[StructureBreak, ...]
    liquidity_levels: tuple[LiquidityLevel, ...]
    liquidity_interactions: tuple[LiquidityInteraction, ...]
    sweeps: tuple[LiquiditySweep, ...]
    fair_value_gaps: tuple[FairValueGap, ...]
    order_blocks: tuple[OrderBlock, ...]
    order_block_selections: tuple[OrderBlockSelection, ...]
    liquidity_importance: tuple[LiquidityImportanceVector, ...]
    digest: str
    dataset_id: str | None
    dataset_sha256: str | None

    @property
    def bos_count(self) -> int:
        return sum(item.kind.value == "BOS" for item in self.structure_breaks)

    @property
    def choch_count(self) -> int:
        return sum(item.kind.value == "CHOCH" for item in self.structure_breaks)


class Tfex3Engine:
    """Incremental neutral analysis; no strategy, risk, broker, or order surface exists."""

    def __init__(
        self,
        pivot_rule: PivotRule,
        *,
        liquidity_price_tolerance_ticks: int | None = None,
        liquidity_tick_size: Decimal | None = None,
    ) -> None:
        self.pivot_rule = pivot_rule
        self._dataset_id: str | None = None
        self._dataset_sha256: str | None = None
        self._structures: dict[BarInterval, MarketStructureEngine] = {}
        self._fvgs: dict[BarInterval, FvgEngine] = {}
        self._order_blocks: dict[BarInterval, OrderBlockEngine] = {}
        self._liquidity = LiquidityEngine()
        self._importance = LiquidityImportanceEngine(
            price_tolerance_ticks=liquidity_price_tolerance_ticks,
            tick_size=liquidity_tick_size,
        )
        self._structure_regime = StructureRegimeEngine()
        self._session_levels = SessionLiquiditySourceEngine()
        self._frames: list[Tfex3Frame] = []
        self._symbol: str | None = None
        self._next_sequence: int = 1
        self._reset()

    @property
    def frames(self) -> tuple[Tfex3Frame, ...]:
        return tuple(self._frames)

    def update(self, frame: ReplayFrame) -> Tfex3Frame:
        sequence = frame.event.sequence
        if sequence != self._next_sequence:
            raise ReplayError(
                f"TFEX-3 expected source sequence {self._next_sequence}, got {sequence}"
            )
        symbol = frame.event.bar.symbol
        if self._symbol is None:
            self._symbol = symbol
        elif symbol != self._symbol:
            raise ReplayError("TFEX-3 cannot mix raw contract symbols")

        bars = [self._one_minute_bar(frame)]
        if frame.confirmed_5m is not None:
            bars.append(self._aggregated_bar(frame.confirmed_5m))
        if frame.confirmed_15m is not None:
            bars.append(self._aggregated_bar(frame.confirmed_15m))

        primary = bars[0]
        liquidity_update = self._liquidity.observe(primary)
        structure_updates: list[StructureUpdate] = []
        fvg_updates: list[FvgUpdate] = []
        order_block_updates: list[OrderBlockUpdate] = []
        new_pivot_levels: list[LiquidityLevel] = []
        for bar in bars:
            structure = self._structures[bar.timeframe].update(bar)
            fvg = self._fvgs[bar.timeframe].update(bar)
            order_block = self._order_blocks[bar.timeframe].update(bar, structure.new_breaks)
            structure_updates.append(structure)
            fvg_updates.append(fvg)
            order_block_updates.append(order_block)
            if bar.timeframe is BarInterval.FIFTEEN_MINUTE:
                self._structure_regime.update(structure)
            new_pivot_levels.extend(
                self._liquidity.register_pivots(
                    structure.new_pivots,
                    created_at=bar.confirmed_at,
                )
            )

        session_levels = self._session_levels.update(frame)
        new_session_levels = self._liquidity.register_levels(session_levels)
        analysis_frame = Tfex3Frame(
            source_sequence=sequence,
            event_time=frame.event.event_time,
            confirmed_at=frame.event.confirmed_at,
            structure_updates=tuple(structure_updates),
            fvg_updates=tuple(fvg_updates),
            order_block_updates=tuple(order_block_updates),
            new_liquidity_levels=tuple(new_pivot_levels) + new_session_levels,
            liquidity_interactions=liquidity_update.interactions,
            new_sweeps=liquidity_update.sweeps,
            biases=tuple(
                TimeframeBias(timeframe, self._structures[timeframe].bias)
                for timeframe in _TIMEFRAMES
            ),
            regime=CompositeRegime(
                structure=self._structure_regime.state,
                volatility=VolatilityClassifier.classify(None, None),
                evaluated_at=frame.event.confirmed_at,
            ),
        )
        self._frames.append(analysis_frame)
        self._next_sequence += 1
        return analysis_frame

    def run(self, replay: ReplayRun) -> Tfex3Run:
        """Restart from source frame one and process the complete TFEX-2 run."""
        self._reset()
        self._dataset_id = replay.dataset_id
        self._dataset_sha256 = replay.dataset_sha256
        for frame in replay.frames:
            self.update(frame)
        return self.result()

    def result(self) -> Tfex3Run:
        if self._symbol is None or not self._frames:
            raise ReplayError("TFEX-3 result requires at least one processed TFEX-2 frame")
        frames = tuple(self._frames)
        pivots = tuple(
            item for timeframe in _TIMEFRAMES for item in self._structures[timeframe].pivots
        )
        swings = tuple(
            item for timeframe in _TIMEFRAMES for item in self._structures[timeframe].swings
        )
        breaks = tuple(
            item for timeframe in _TIMEFRAMES for item in self._structures[timeframe].breaks
        )
        gaps = tuple(item for timeframe in _TIMEFRAMES for item in self._fvgs[timeframe].current)
        order_blocks = tuple(
            item for timeframe in _TIMEFRAMES for item in self._order_blocks[timeframe].current
        )
        selections = tuple(
            item for timeframe in _TIMEFRAMES for item in self._order_blocks[timeframe].selections
        )
        importance = self._importance.extract(
            self._liquidity.levels,
            as_of=frames[-1].confirmed_at,
        )
        return Tfex3Run(
            symbol=self._symbol,
            source_bar_count=len(frames),
            frames=frames,
            pivots=pivots,
            swings=swings,
            structure_breaks=breaks,
            liquidity_levels=self._liquidity.levels,
            liquidity_interactions=self._liquidity.interactions,
            sweeps=self._liquidity.sweeps,
            fair_value_gaps=gaps,
            order_blocks=order_blocks,
            order_block_selections=selections,
            liquidity_importance=importance,
            digest=analysis_digest(frames),
            dataset_id=self._dataset_id,
            dataset_sha256=self._dataset_sha256,
        )

    def _reset(self) -> None:
        self._structures = {
            timeframe: MarketStructureEngine(timeframe, self.pivot_rule)
            for timeframe in _TIMEFRAMES
        }
        self._fvgs = {timeframe: FvgEngine(timeframe) for timeframe in _TIMEFRAMES}
        self._order_blocks = {timeframe: OrderBlockEngine(timeframe) for timeframe in _TIMEFRAMES}
        self._liquidity = LiquidityEngine()
        self._structure_regime = StructureRegimeEngine()
        self._session_levels = SessionLiquiditySourceEngine()
        self._frames = []
        self._symbol = None
        self._next_sequence = 1

    @staticmethod
    def _one_minute_bar(frame: ReplayFrame) -> AnalysisBar:
        event = frame.event
        bar = event.bar
        return AnalysisBar(
            symbol=bar.symbol,
            timeframe=BarInterval.ONE_MINUTE,
            source_sequence=event.sequence,
            session=event.continuous_session,
            open_time=bar.timestamp,
            event_time=event.event_time,
            confirmed_at=event.confirmed_at,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

    @staticmethod
    def _aggregated_bar(bar: AggregatedBar) -> AnalysisBar:
        if not bar.is_closed or bar.confirmed_at is None:
            raise ReplayError("TFEX-3 accepts only confirmed higher-timeframe bars")
        return AnalysisBar(
            symbol=bar.symbol,
            timeframe=bar.interval,
            source_sequence=bar.last_source_sequence,
            session=bar.session,
            open_time=bar.open_time,
            event_time=bar.event_time,
            confirmed_at=bar.confirmed_at,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
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


def analysis_digest(frames: tuple[Tfex3Frame, ...] | list[Tfex3Frame]) -> str:
    payload = json.dumps(
        _jsonable(tuple(frames)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
