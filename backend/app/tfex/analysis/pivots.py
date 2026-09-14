"""Delayed, strict-extrema swing pivots for TFEX-3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.analysis.models import AnalysisBar
from app.tfex.errors import ReplayError
from app.tfex.marketdata.models import BarInterval

__all__ = ["ConfirmedPivot", "PivotEngine", "PivotRule", "PivotType"]


class PivotType(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class PivotRule:
    """Explicit local-extrema evidence; no hidden/default lookahead is permitted."""

    left_bars: int
    right_bars: int
    rule_id: str = "STRICT_WICK_EXTREMA_V1"

    def __post_init__(self) -> None:
        if self.left_bars < 1 or self.right_bars < 1:
            raise ValueError("pivot rule requires at least one bar on each side")
        if not self.rule_id:
            raise ValueError("pivot rule requires a stable rule_id")


@dataclass(frozen=True, slots=True)
class ConfirmedPivot:
    pivot_id: str
    symbol: str
    pivot_type: PivotType
    timeframe: BarInterval
    price: Decimal
    source_bar_id: str
    source_sequence: int
    event_time: datetime
    confirmed_at: datetime
    left_strength: int
    right_strength: int
    rule_id: str


class PivotEngine:
    """Confirm a candidate only after every configured right-side bar has closed."""

    def __init__(self, timeframe: BarInterval, rule: PivotRule) -> None:
        self.timeframe = timeframe
        self.rule = rule
        self._bars: list[AnalysisBar] = []
        self._symbol: str | None = None
        self._confirmed: list[ConfirmedPivot] = []

    @property
    def confirmed(self) -> tuple[ConfirmedPivot, ...]:
        return tuple(self._confirmed)

    def update(self, bar: AnalysisBar) -> tuple[ConfirmedPivot, ...]:
        if bar.timeframe is not self.timeframe:
            raise ReplayError(
                f"pivot engine {self.timeframe.value} received {bar.timeframe.value} bar"
            )
        if self._symbol is None:
            self._symbol = bar.symbol
        elif bar.symbol != self._symbol:
            raise ReplayError("pivot engine cannot mix raw contract symbols")
        if self._bars and bar.confirmed_at <= self._bars[len(self._bars) - 1].confirmed_at:
            raise ReplayError("pivot input must be strictly ordered by confirmation time")

        self._bars.append(bar)
        candidate_index = len(self._bars) - self.rule.right_bars - 1
        if candidate_index < self.rule.left_bars:
            return ()

        candidate = self._bars[candidate_index]
        left = self._bars[candidate_index - self.rule.left_bars : candidate_index]
        right = self._bars[candidate_index + 1 : candidate_index + self.rule.right_bars + 1]
        confirmed_at = bar.confirmed_at
        found: list[ConfirmedPivot] = []
        if all(candidate.high > neighbor.high for neighbor in (*left, *right)):
            found.append(self._make(candidate, PivotType.HIGH, candidate.high, confirmed_at))
        if all(candidate.low < neighbor.low for neighbor in (*left, *right)):
            found.append(self._make(candidate, PivotType.LOW, candidate.low, confirmed_at))
        self._confirmed.extend(found)
        return tuple(found)

    def _make(
        self,
        candidate: AnalysisBar,
        pivot_type: PivotType,
        price: Decimal,
        confirmed_at: datetime,
    ) -> ConfirmedPivot:
        pivot_id = (
            f"pivot:{candidate.symbol}:{candidate.timeframe.value}:{pivot_type.value}:"
            f"{candidate.event_time.isoformat()}:{self.rule.rule_id}"
        )
        return ConfirmedPivot(
            pivot_id=pivot_id,
            symbol=candidate.symbol,
            pivot_type=pivot_type,
            timeframe=candidate.timeframe,
            price=price,
            source_bar_id=candidate.bar_id,
            source_sequence=candidate.source_sequence,
            event_time=candidate.event_time,
            confirmed_at=confirmed_at,
            left_strength=self.rule.left_bars,
            right_strength=self.rule.right_bars,
            rule_id=self.rule.rule_id,
        )
