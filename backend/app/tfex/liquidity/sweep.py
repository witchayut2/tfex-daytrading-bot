"""Neutral touch, break, invalidation, and reclaimed-wick sweep events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.tfex.analysis.models import AnalysisBar
from app.tfex.liquidity.levels import LiquidityLevel, LiquidityLevelStatus, LiquiditySide

__all__ = [
    "LiquidityInteraction",
    "LiquiditySweep",
    "SweepDirection",
    "apply_interaction",
]


class SweepDirection(StrEnum):
    ABOVE_HIGH = "ABOVE_HIGH"
    BELOW_LOW = "BELOW_LOW"


@dataclass(frozen=True, slots=True)
class LiquidityInteraction:
    interaction_id: str
    level_id: str
    symbol: str
    direction: SweepDirection
    touched: bool
    exceeded: bool
    reclaimed: bool
    event_time: datetime
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class LiquiditySweep:
    sweep_id: str
    level_id: str
    symbol: str
    direction: SweepDirection
    event_time: datetime
    confirmed_at: datetime
    interaction_id: str


def apply_interaction(
    level: LiquidityLevel,
    bar: AnalysisBar,
) -> tuple[LiquidityLevel, LiquidityInteraction | None, LiquiditySweep | None]:
    """Apply one later closed 1m bar; a wick alone never confirms a sweep."""
    if not level.active or level.symbol != bar.symbol or level.created_at > bar.event_time:
        return level, None, None
    if level.side is LiquiditySide.HIGH:
        touched = bar.high >= level.price
        exceeded = bar.high > level.price
        reclaimed = exceeded and bar.close < level.price
        invalidated = bar.close > level.price
        direction = SweepDirection.ABOVE_HIGH
    else:
        touched = bar.low <= level.price
        exceeded = bar.low < level.price
        reclaimed = exceeded and bar.close > level.price
        invalidated = bar.close < level.price
        direction = SweepDirection.BELOW_LOW
    if not touched:
        return level, None, None

    interaction_id = f"interaction:{level.level_id}:{bar.confirmed_at.isoformat()}"
    interaction = LiquidityInteraction(
        interaction_id=interaction_id,
        level_id=level.level_id,
        symbol=bar.symbol,
        direction=direction,
        touched=True,
        exceeded=exceeded,
        reclaimed=reclaimed,
        event_time=bar.event_time,
        confirmed_at=bar.confirmed_at,
    )
    if reclaimed:
        updated = replace(
            level,
            status=LiquidityLevelStatus.SWEPT,
            touch_count=level.touch_count + 1,
            updated_at=bar.confirmed_at,
            swept_at=bar.confirmed_at,
        )
        sweep = LiquiditySweep(
            sweep_id=f"sweep:{level.level_id}:{bar.confirmed_at.isoformat()}",
            level_id=level.level_id,
            symbol=bar.symbol,
            direction=direction,
            event_time=bar.event_time,
            confirmed_at=bar.confirmed_at,
            interaction_id=interaction_id,
        )
        return updated, interaction, sweep
    if invalidated:
        return (
            replace(
                level,
                status=LiquidityLevelStatus.INVALIDATED,
                touch_count=level.touch_count + 1,
                updated_at=bar.confirmed_at,
                invalidated_at=bar.confirmed_at,
            ),
            interaction,
            None,
        )
    return (
        replace(
            level,
            status=LiquidityLevelStatus.TOUCHED,
            touch_count=level.touch_count + 1,
            updated_at=bar.confirmed_at,
        ),
        interaction,
        None,
    )
