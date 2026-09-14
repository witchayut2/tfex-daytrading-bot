"""Deterministic BOS-confirmed Order Blocks for neutral TFEX-3 analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.analysis.models import AnalysisBar
from app.tfex.analysis.structure import BreakDirection, BreakKind, StructureBreak
from app.tfex.errors import ReplayError
from app.tfex.marketdata.models import BarInterval

__all__ = [
    "OrderBlock",
    "OrderBlockDirection",
    "OrderBlockEngine",
    "OrderBlockSelection",
    "OrderBlockSelectionOutcome",
    "OrderBlockStatus",
    "OrderBlockUpdate",
]


class OrderBlockDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class OrderBlockStatus(StrEnum):
    ACTIVE = "ACTIVE"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"


class OrderBlockSelectionOutcome(StrEnum):
    ORDER_BLOCK_CREATED = "ORDER_BLOCK_CREATED"
    NO_ORDER_BLOCK = "NO_ORDER_BLOCK"


@dataclass(frozen=True, slots=True)
class OrderBlock:
    order_block_id: str
    symbol: str
    timeframe: BarInterval
    direction: OrderBlockDirection
    lower_bound: Decimal
    upper_bound: Decimal
    source_bar_id: str
    source_sequence: int
    source_open: Decimal
    source_close: Decimal
    anchor_pivot_id: str
    bos_id: str
    event_time: datetime
    confirmed_at: datetime
    status: OrderBlockStatus
    updated_at: datetime
    mitigated_at: datetime | None = None
    invalidated_at: datetime | None = None
    rule_id: str = "LAST_OPPOSITE_CANDLE_AFTER_ANCHOR_V1"


@dataclass(frozen=True, slots=True)
class OrderBlockSelection:
    bos_id: str
    outcome: OrderBlockSelectionOutcome
    order_block_id: str | None
    reason: str
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class OrderBlockUpdate:
    timeframe: BarInterval
    formed: tuple[OrderBlock, ...]
    changed: tuple[OrderBlock, ...]
    selections: tuple[OrderBlockSelection, ...]


class OrderBlockEngine:
    """Select at most one historical opposite candle per confirmed BOS."""

    def __init__(self, timeframe: BarInterval) -> None:
        self.timeframe = timeframe
        self._bars: list[AnalysisBar] = []
        self._blocks: dict[str, OrderBlock] = {}
        self._formed: list[OrderBlock] = []
        self._selections: list[OrderBlockSelection] = []
        self._handled_breaks: set[str] = set()
        self._symbol: str | None = None

    @property
    def formed(self) -> tuple[OrderBlock, ...]:
        return tuple(self._formed)

    @property
    def current(self) -> tuple[OrderBlock, ...]:
        return tuple(self._blocks.values())

    @property
    def selections(self) -> tuple[OrderBlockSelection, ...]:
        return tuple(self._selections)

    def update(
        self,
        bar: AnalysisBar,
        breaks: tuple[StructureBreak, ...],
    ) -> OrderBlockUpdate:
        if bar.timeframe is not self.timeframe:
            raise ReplayError(
                f"Order Block engine {self.timeframe.value} received {bar.timeframe.value}"
            )
        if self._symbol is None:
            self._symbol = bar.symbol
        elif bar.symbol != self._symbol:
            raise ReplayError("Order Block engine cannot mix raw contract symbols")
        if self._bars and bar.confirmed_at <= self._bars[-1].confirmed_at:
            raise ReplayError("Order Block input must be strictly ordered by confirmation time")

        changed = self._update_existing(bar)
        formed: list[OrderBlock] = []
        selections: list[OrderBlockSelection] = []
        for structure_break in breaks:
            if structure_break.break_id in self._handled_breaks:
                continue
            self._handled_breaks.add(structure_break.break_id)
            if structure_break.kind is not BreakKind.BOS:
                continue
            block = self._select(structure_break, bar)
            if block is not None:
                self._blocks[block.order_block_id] = block
                self._formed.append(block)
                formed.append(block)
                selection = OrderBlockSelection(
                    bos_id=structure_break.break_id,
                    outcome=OrderBlockSelectionOutcome.ORDER_BLOCK_CREATED,
                    order_block_id=block.order_block_id,
                    reason="LAST_ELIGIBLE_OPPOSITE_CANDLE_SELECTED",
                    confirmed_at=structure_break.confirmed_at,
                )
            else:
                has_anchor = (
                    structure_break.anchor_pivot_id is not None
                    and structure_break.anchor_event_time is not None
                    and structure_break.anchor_confirmed_at is not None
                )
                selection = OrderBlockSelection(
                    bos_id=structure_break.break_id,
                    outcome=OrderBlockSelectionOutcome.NO_ORDER_BLOCK,
                    order_block_id=None,
                    reason=(
                        "NO_ELIGIBLE_OPPOSITE_CANDLE_AFTER_CONFIRMED_ANCHOR"
                        if has_anchor
                        else "NO_CONFIRMED_OPPOSITE_PIVOT_ANCHOR"
                    ),
                    confirmed_at=structure_break.confirmed_at,
                )
            self._selections.append(selection)
            selections.append(selection)
        self._bars.append(bar)
        return OrderBlockUpdate(self.timeframe, tuple(formed), changed, tuple(selections))

    def _update_existing(self, bar: AnalysisBar) -> tuple[OrderBlock, ...]:
        changed: list[OrderBlock] = []
        for block_id, block in tuple(self._blocks.items()):
            if block.status is OrderBlockStatus.INVALIDATED:
                continue
            if block.symbol != bar.symbol or block.confirmed_at > bar.event_time:
                continue
            trades_in_zone = bar.high >= block.lower_bound and bar.low <= block.upper_bound
            invalidated = (
                bar.close < block.lower_bound
                if block.direction is OrderBlockDirection.BULLISH
                else bar.close > block.upper_bound
            )
            replacement = block
            if invalidated:
                replacement = replace(
                    block,
                    status=OrderBlockStatus.INVALIDATED,
                    updated_at=bar.confirmed_at,
                    mitigated_at=block.mitigated_at or bar.confirmed_at,
                    invalidated_at=bar.confirmed_at,
                )
            elif trades_in_zone and block.status is OrderBlockStatus.ACTIVE:
                replacement = replace(
                    block,
                    status=OrderBlockStatus.MITIGATED,
                    updated_at=bar.confirmed_at,
                    mitigated_at=bar.confirmed_at,
                )
            if replacement != block:
                self._blocks[block_id] = replacement
                changed.append(replacement)
        return tuple(changed)

    def _select(self, structure_break: StructureBreak, bos_bar: AnalysisBar) -> OrderBlock | None:
        if (
            structure_break.symbol != bos_bar.symbol
            or structure_break.timeframe is not self.timeframe
            or structure_break.confirmed_at != bos_bar.confirmed_at
        ):
            raise ReplayError("Order Block BOS evidence does not match its confirming bar")
        if (
            structure_break.anchor_pivot_id is None
            or structure_break.anchor_event_time is None
            or structure_break.anchor_confirmed_at is None
        ):
            return None
        if structure_break.anchor_confirmed_at > structure_break.confirmed_at:
            raise ReplayError("Order Block anchor was not confirmed by the BOS close")
        direction = (
            OrderBlockDirection.BULLISH
            if structure_break.direction is BreakDirection.BULLISH
            else OrderBlockDirection.BEARISH
        )
        candidates = [
            candidate
            for candidate in self._bars
            if structure_break.anchor_event_time < candidate.event_time < bos_bar.event_time
            and (
                candidate.close < candidate.open
                if direction is OrderBlockDirection.BULLISH
                else candidate.close > candidate.open
            )
        ]
        if not candidates:
            return None
        source = candidates[-1]
        return OrderBlock(
            order_block_id=f"order-block:{structure_break.break_id}",
            symbol=source.symbol,
            timeframe=source.timeframe,
            direction=direction,
            lower_bound=source.low,
            upper_bound=source.high,
            source_bar_id=source.bar_id,
            source_sequence=source.source_sequence,
            source_open=source.open,
            source_close=source.close,
            anchor_pivot_id=structure_break.anchor_pivot_id,
            bos_id=structure_break.break_id,
            event_time=source.event_time,
            confirmed_at=structure_break.confirmed_at,
            status=OrderBlockStatus.ACTIVE,
            updated_at=structure_break.confirmed_at,
        )
