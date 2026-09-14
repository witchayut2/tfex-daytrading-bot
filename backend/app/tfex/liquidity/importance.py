"""Causal liquidity importance features without invented ranking weights."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.errors import ReplayError
from app.tfex.liquidity.levels import (
    LiquidityLevel,
    LiquidityLevelSource,
    LiquidityLevelStatus,
)
from app.tfex.marketdata.models import BarInterval

__all__ = [
    "LiquidityImportanceEngine",
    "LiquidityImportanceVector",
    "PartialOrder",
]


class PartialOrder(StrEnum):
    DOMINATES = "DOMINATES"
    DOMINATED = "DOMINATED"
    EQUAL = "EQUAL"
    INCOMPARABLE = "INCOMPARABLE"


@dataclass(frozen=True, slots=True)
class LiquidityImportanceVector:
    level_id: str
    symbol: str
    is_confirmed: bool
    timeframe: BarInterval
    source_type: LiquidityLevelSource
    confluence_count: int
    age_seconds: int | None
    swept_state: LiquidityLevelStatus | None
    is_unswept: bool | None
    confirmed_at: datetime
    as_of: datetime


class LiquidityImportanceEngine:
    """Extract stable features and a Pareto-style partial order."""

    def __init__(
        self,
        *,
        price_tolerance_ticks: int | None = None,
        tick_size: Decimal | None = None,
    ) -> None:
        if price_tolerance_ticks is not None and price_tolerance_ticks < 0:
            raise ValueError("price_tolerance_ticks cannot be negative")
        if price_tolerance_ticks is not None and (tick_size is None or tick_size <= 0):
            raise ValueError("an explicit positive tick_size is required with tick tolerance")
        self.price_tolerance_ticks = price_tolerance_ticks
        self.tick_size = tick_size

    @property
    def tolerance(self) -> Decimal:
        if self.price_tolerance_ticks is None:
            return Decimal(0)
        if self.tick_size is None:  # guarded by the constructor; keeps type narrowing explicit
            raise ValueError("tick_size is required")
        return self.tick_size * self.price_tolerance_ticks

    def extract(
        self,
        levels: tuple[LiquidityLevel, ...] | list[LiquidityLevel],
        *,
        as_of: datetime,
    ) -> tuple[LiquidityImportanceVector, ...]:
        if as_of.tzinfo is None:
            raise ValueError("liquidity importance as_of must be timezone-aware")
        ordered = tuple(sorted(levels, key=lambda item: item.level_id))
        confirmed: list[LiquidityLevel] = []
        for level in ordered:
            available = level.confirmed_at <= as_of and level.created_at <= as_of
            if available and level.updated_at > as_of:
                raise ReplayError(
                    "a later liquidity revision cannot be used to reconstruct past importance"
                )
            if available:
                confirmed.append(level)

        vectors: list[LiquidityImportanceVector] = []
        tolerance = self.tolerance
        for level in ordered:
            available = level in confirmed
            confluence = (
                sum(
                    other.symbol == level.symbol and abs(other.price - level.price) <= tolerance
                    for other in confirmed
                )
                if available
                else 0
            )
            age = int((as_of - level.confirmed_at).total_seconds()) if available else None
            unswept = (
                level.status in {LiquidityLevelStatus.ACTIVE, LiquidityLevelStatus.TOUCHED}
                if available
                else None
            )
            vectors.append(
                LiquidityImportanceVector(
                    level_id=level.level_id,
                    symbol=level.symbol,
                    is_confirmed=available,
                    timeframe=level.timeframe,
                    source_type=level.source,
                    confluence_count=confluence,
                    age_seconds=age,
                    swept_state=level.status if available else None,
                    is_unswept=unswept,
                    confirmed_at=level.confirmed_at,
                    as_of=as_of,
                )
            )
        return tuple(vectors)

    @staticmethod
    def compare(
        left: LiquidityImportanceVector,
        right: LiquidityImportanceVector,
    ) -> PartialOrder:
        if left == right:
            return PartialOrder.EQUAL
        if (
            not left.is_confirmed
            or not right.is_confirmed
            or left.symbol != right.symbol
            or left.timeframe is not right.timeframe
            or left.source_type is not right.source_type
            or left.as_of != right.as_of
            or left.is_unswept is None
            or right.is_unswept is None
            or left.age_seconds is None
            or right.age_seconds is None
        ):
            return PartialOrder.INCOMPARABLE
        left_no_worse = (
            left.confluence_count >= right.confluence_count
            and int(left.is_unswept) >= int(right.is_unswept)
            and left.age_seconds <= right.age_seconds
        )
        right_no_worse = (
            left.confluence_count <= right.confluence_count
            and int(left.is_unswept) <= int(right.is_unswept)
            and left.age_seconds >= right.age_seconds
        )
        differs = (
            left.confluence_count != right.confluence_count
            or left.is_unswept is not right.is_unswept
            or left.age_seconds != right.age_seconds
        )
        if left_no_worse and differs:
            return PartialOrder.DOMINATES
        if right_no_worse and differs:
            return PartialOrder.DOMINATED
        return PartialOrder.INCOMPARABLE
