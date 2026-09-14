"""Incremental causal liquidity map orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.tfex.analysis.models import AnalysisBar
from app.tfex.analysis.pivots import ConfirmedPivot, PivotType
from app.tfex.liquidity.levels import (
    LiquidityLevel,
    equal_pivot_level,
    pivot_level,
)
from app.tfex.liquidity.sweep import (
    LiquidityInteraction,
    LiquiditySweep,
    apply_interaction,
)
from app.tfex.marketdata.models import BarInterval

__all__ = ["LiquidityEngine", "LiquidityUpdate"]


@dataclass(frozen=True, slots=True)
class LiquidityUpdate:
    interactions: tuple[LiquidityInteraction, ...]
    sweeps: tuple[LiquiditySweep, ...]
    changed_levels: tuple[LiquidityLevel, ...]


class LiquidityEngine:
    """Keep current immutable level revisions and append-only interaction histories."""

    def __init__(self) -> None:
        self._levels: dict[str, LiquidityLevel] = {}
        self._created: list[LiquidityLevel] = []
        self._interactions: list[LiquidityInteraction] = []
        self._sweeps: list[LiquiditySweep] = []
        self._previous_pivots: dict[tuple[BarInterval, PivotType], ConfirmedPivot] = {}

    @property
    def levels(self) -> tuple[LiquidityLevel, ...]:
        return tuple(self._levels.values())

    @property
    def created_levels(self) -> tuple[LiquidityLevel, ...]:
        return tuple(self._created)

    @property
    def interactions(self) -> tuple[LiquidityInteraction, ...]:
        return tuple(self._interactions)

    @property
    def sweeps(self) -> tuple[LiquiditySweep, ...]:
        return tuple(self._sweeps)

    def register_pivots(
        self,
        pivots: tuple[ConfirmedPivot, ...],
        *,
        created_at: datetime,
    ) -> tuple[LiquidityLevel, ...]:
        candidates: list[LiquidityLevel] = []
        for pivot in pivots:
            key = (pivot.timeframe, pivot.pivot_type)
            previous = self._previous_pivots.get(key)
            candidates.append(pivot_level(pivot, created_at=created_at))
            if previous is not None:
                equal = equal_pivot_level(previous, pivot, created_at=created_at)
                if equal is not None:
                    candidates.append(equal)
            self._previous_pivots[key] = pivot
        return self.register_levels(tuple(candidates))

    def register_levels(self, levels: tuple[LiquidityLevel, ...]) -> tuple[LiquidityLevel, ...]:
        added: list[LiquidityLevel] = []
        for level in levels:
            if level.level_id in self._levels:
                continue
            self._levels[level.level_id] = level
            self._created.append(level)
            added.append(level)
        return tuple(added)

    def observe(self, bar: AnalysisBar) -> LiquidityUpdate:
        interactions: list[LiquidityInteraction] = []
        sweeps: list[LiquiditySweep] = []
        changed: list[LiquidityLevel] = []
        for level_id, level in tuple(self._levels.items()):
            updated, interaction, sweep = apply_interaction(level, bar)
            if interaction is None:
                continue
            self._levels[level_id] = updated
            interactions.append(interaction)
            changed.append(updated)
            if sweep is not None:
                sweeps.append(sweep)
        self._interactions.extend(interactions)
        self._sweeps.extend(sweeps)
        return LiquidityUpdate(tuple(interactions), tuple(sweeps), tuple(changed))
