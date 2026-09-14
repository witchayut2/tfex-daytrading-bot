"""Deterministic swing labels and close-confirmed BOS/CHoCH events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.analysis.models import AnalysisBar
from app.tfex.analysis.pivots import ConfirmedPivot, PivotEngine, PivotRule, PivotType
from app.tfex.errors import ReplayError
from app.tfex.marketdata.models import BarInterval

__all__ = [
    "BreakDirection",
    "BreakKind",
    "MarketStructureEngine",
    "StructureBias",
    "StructureBreak",
    "StructureUpdate",
    "SwingClassification",
    "SwingRelation",
]


class SwingRelation(StrEnum):
    UNCLASSIFIED = "UNCLASSIFIED"
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    EQUAL_HIGH = "EQUAL_HIGH"
    EQUAL_LOW = "EQUAL_LOW"


class StructureBias(StrEnum):
    STRUCTURE_BULLISH = "STRUCTURE_BULLISH"
    STRUCTURE_BEARISH = "STRUCTURE_BEARISH"
    STRUCTURE_RANGE = "STRUCTURE_RANGE"
    STRUCTURE_UNRESOLVED = "STRUCTURE_UNRESOLVED"


class BreakDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class BreakKind(StrEnum):
    BOS = "BOS"
    CHOCH = "CHOCH"


@dataclass(frozen=True, slots=True)
class SwingClassification:
    structure_id: str
    pivot_id: str
    previous_pivot_id: str | None
    symbol: str
    timeframe: BarInterval
    pivot_type: PivotType
    relation: SwingRelation
    price: Decimal
    previous_price: Decimal | None
    event_time: datetime
    confirmed_at: datetime
    bias_after: StructureBias


@dataclass(frozen=True, slots=True)
class StructureBreak:
    break_id: str
    kind: BreakKind
    direction: BreakDirection
    symbol: str
    timeframe: BarInterval
    broken_level_id: str
    broken_price: Decimal
    anchor_pivot_id: str | None
    anchor_event_time: datetime | None
    anchor_confirmed_at: datetime | None
    confirming_close: Decimal
    break_basis: str
    event_time: datetime
    confirmed_at: datetime
    prior_structural_regime: StructureBias


@dataclass(frozen=True, slots=True)
class StructureUpdate:
    timeframe: BarInterval
    new_pivots: tuple[ConfirmedPivot, ...]
    new_swings: tuple[SwingClassification, ...]
    new_breaks: tuple[StructureBreak, ...]
    bias: StructureBias


class MarketStructureEngine:
    """Use only confirmed pivots and closed bars; emitted histories are append-only."""

    def __init__(self, timeframe: BarInterval, pivot_rule: PivotRule) -> None:
        self.timeframe = timeframe
        self._pivots = PivotEngine(timeframe, pivot_rule)
        self._latest: dict[PivotType, ConfirmedPivot] = {}
        self._relations: dict[PivotType, SwingRelation] = {}
        self._swings: list[SwingClassification] = []
        self._breaks: list[StructureBreak] = []
        self._broken_pivots: set[str] = set()
        self._bias = StructureBias.STRUCTURE_UNRESOLVED

    @property
    def pivots(self) -> tuple[ConfirmedPivot, ...]:
        return self._pivots.confirmed

    @property
    def swings(self) -> tuple[SwingClassification, ...]:
        return tuple(self._swings)

    @property
    def breaks(self) -> tuple[StructureBreak, ...]:
        return tuple(self._breaks)

    @property
    def bias(self) -> StructureBias:
        return self._bias

    def update(self, bar: AnalysisBar) -> StructureUpdate:
        if bar.timeframe is not self.timeframe:
            raise ReplayError(
                f"structure engine {self.timeframe.value} received {bar.timeframe.value} bar"
            )
        pivots = self._pivots.update(bar)
        new_swings = tuple(self._classify(pivot) for pivot in pivots)
        new_breaks = self._detect_breaks(bar)
        return StructureUpdate(self.timeframe, pivots, new_swings, new_breaks, self._bias)

    def _classify(self, pivot: ConfirmedPivot) -> SwingClassification:
        previous = self._latest.get(pivot.pivot_type)
        if previous is None:
            relation = SwingRelation.UNCLASSIFIED
            previous_price = None
        elif pivot.pivot_type is PivotType.HIGH:
            previous_price = previous.price
            relation = (
                SwingRelation.HH
                if pivot.price > previous.price
                else SwingRelation.LH
                if pivot.price < previous.price
                else SwingRelation.EQUAL_HIGH
            )
        else:
            previous_price = previous.price
            relation = (
                SwingRelation.HL
                if pivot.price > previous.price
                else SwingRelation.LL
                if pivot.price < previous.price
                else SwingRelation.EQUAL_LOW
            )
        self._latest[pivot.pivot_type] = pivot
        self._relations[pivot.pivot_type] = relation
        self._bias = self._derive_bias()
        classification = SwingClassification(
            structure_id=f"structure:{pivot.pivot_id}",
            pivot_id=pivot.pivot_id,
            previous_pivot_id=previous.pivot_id if previous is not None else None,
            symbol=pivot.symbol,
            timeframe=pivot.timeframe,
            pivot_type=pivot.pivot_type,
            relation=relation,
            price=pivot.price,
            previous_price=previous_price,
            event_time=pivot.event_time,
            confirmed_at=pivot.confirmed_at,
            bias_after=self._bias,
        )
        self._swings.append(classification)
        return classification

    def _derive_bias(self) -> StructureBias:
        high = self._relations.get(PivotType.HIGH, SwingRelation.UNCLASSIFIED)
        low = self._relations.get(PivotType.LOW, SwingRelation.UNCLASSIFIED)
        if high is SwingRelation.HH and low is SwingRelation.HL:
            return StructureBias.STRUCTURE_BULLISH
        if high is SwingRelation.LH and low is SwingRelation.LL:
            return StructureBias.STRUCTURE_BEARISH
        if high is SwingRelation.UNCLASSIFIED or low is SwingRelation.UNCLASSIFIED:
            return StructureBias.STRUCTURE_UNRESOLVED
        return StructureBias.STRUCTURE_RANGE

    def _detect_breaks(self, bar: AnalysisBar) -> tuple[StructureBreak, ...]:
        candidates: list[tuple[PivotType, BreakDirection]] = [
            (PivotType.HIGH, BreakDirection.BULLISH),
            (PivotType.LOW, BreakDirection.BEARISH),
        ]
        found: list[StructureBreak] = []
        for pivot_type, direction in candidates:
            pivot = self._latest.get(pivot_type)
            if (
                pivot is None
                or pivot.pivot_id in self._broken_pivots
                or pivot.confirmed_at > bar.event_time
            ):
                continue
            broke = (
                bar.close > pivot.price if pivot_type is PivotType.HIGH else bar.close < pivot.price
            )
            if not broke:
                continue
            prior = self._bias
            contrary = (
                direction is BreakDirection.BULLISH and prior is StructureBias.STRUCTURE_BEARISH
            ) or (direction is BreakDirection.BEARISH and prior is StructureBias.STRUCTURE_BULLISH)
            kind = BreakKind.CHOCH if contrary else BreakKind.BOS
            anchor_type = PivotType.LOW if direction is BreakDirection.BULLISH else PivotType.HIGH
            anchor = self._latest.get(anchor_type)
            if anchor is not None and anchor.event_time >= bar.event_time:
                anchor = None
            event = StructureBreak(
                break_id=(f"break:{kind.value}:{pivot.pivot_id}:{bar.confirmed_at.isoformat()}"),
                kind=kind,
                direction=direction,
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                broken_level_id=pivot.pivot_id,
                broken_price=pivot.price,
                anchor_pivot_id=anchor.pivot_id if anchor is not None else None,
                anchor_event_time=anchor.event_time if anchor is not None else None,
                anchor_confirmed_at=anchor.confirmed_at if anchor is not None else None,
                confirming_close=bar.close,
                break_basis="STRICT_CLOSE_BEYOND_CONFIRMED_SWING_V1",
                event_time=bar.event_time,
                confirmed_at=bar.confirmed_at,
                prior_structural_regime=prior,
            )
            self._broken_pivots.add(pivot.pivot_id)
            self._breaks.append(event)
            found.append(event)
        return tuple(found)
