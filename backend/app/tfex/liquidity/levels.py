"""Immutable causal liquidity levels for TFEX-3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.analysis.pivots import ConfirmedPivot, PivotType
from app.tfex.marketdata.models import BarInterval
from app.tfex.sessions.boundaries import ContinuousSession

__all__ = [
    "LiquidityLevel",
    "LiquidityLevelSource",
    "LiquidityLevelStatus",
    "LiquiditySide",
    "equal_pivot_level",
    "pivot_level",
]


class LiquiditySide(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class LiquidityLevelSource(StrEnum):
    CONFIRMED_SWING_HIGH = "CONFIRMED_SWING_HIGH"
    CONFIRMED_SWING_LOW = "CONFIRMED_SWING_LOW"
    EQUAL_HIGHS = "EQUAL_HIGHS"
    EQUAL_LOWS = "EQUAL_LOWS"
    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    MORNING_HIGH = "MORNING_HIGH"
    MORNING_LOW = "MORNING_LOW"
    AFTERNOON_HIGH = "AFTERNOON_HIGH"
    AFTERNOON_LOW = "AFTERNOON_LOW"
    OPENING_RANGE_HIGH = "OPENING_RANGE_HIGH"
    OPENING_RANGE_LOW = "OPENING_RANGE_LOW"


class LiquidityLevelStatus(StrEnum):
    ACTIVE = "ACTIVE"
    TOUCHED = "TOUCHED"
    SWEPT = "SWEPT"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    level_id: str
    symbol: str
    timeframe: BarInterval
    side: LiquiditySide
    source: LiquidityLevelSource
    price: Decimal
    event_time: datetime
    created_at: datetime
    confirmed_at: datetime
    updated_at: datetime
    source_object_ids: tuple[str, ...]
    source_session: ContinuousSession | None
    status: LiquidityLevelStatus = LiquidityLevelStatus.ACTIVE
    touch_count: int = 0
    swept_at: datetime | None = None
    invalidated_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status in {LiquidityLevelStatus.ACTIVE, LiquidityLevelStatus.TOUCHED}


def pivot_level(pivot: ConfirmedPivot, *, created_at: datetime) -> LiquidityLevel:
    side = LiquiditySide.HIGH if pivot.pivot_type is PivotType.HIGH else LiquiditySide.LOW
    source = (
        LiquidityLevelSource.CONFIRMED_SWING_HIGH
        if side is LiquiditySide.HIGH
        else LiquidityLevelSource.CONFIRMED_SWING_LOW
    )
    return LiquidityLevel(
        level_id=f"liquidity:{pivot.pivot_id}",
        symbol=pivot.symbol,
        timeframe=pivot.timeframe,
        side=side,
        source=source,
        price=pivot.price,
        event_time=pivot.event_time,
        created_at=created_at,
        confirmed_at=pivot.confirmed_at,
        updated_at=created_at,
        source_object_ids=(pivot.pivot_id,),
        source_session=None,
    )


def equal_pivot_level(
    previous: ConfirmedPivot,
    current: ConfirmedPivot,
    *,
    created_at: datetime,
) -> LiquidityLevel | None:
    """Create equality only for exact same-tick prices; no hidden tolerance exists."""
    if previous.pivot_type is not current.pivot_type or previous.price != current.price:
        return None
    side = LiquiditySide.HIGH if current.pivot_type is PivotType.HIGH else LiquiditySide.LOW
    source = (
        LiquidityLevelSource.EQUAL_HIGHS
        if side is LiquiditySide.HIGH
        else LiquidityLevelSource.EQUAL_LOWS
    )
    return LiquidityLevel(
        level_id=f"liquidity:equal:{previous.pivot_id}:{current.pivot_id}",
        symbol=current.symbol,
        timeframe=current.timeframe,
        side=side,
        source=source,
        price=current.price,
        event_time=current.event_time,
        created_at=created_at,
        confirmed_at=current.confirmed_at,
        updated_at=created_at,
        source_object_ids=(previous.pivot_id, current.pivot_id),
        source_session=None,
    )
