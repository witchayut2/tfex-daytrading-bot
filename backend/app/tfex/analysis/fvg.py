"""Causal three-closed-candle fair-value gaps for TFEX-3."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.tfex.analysis.models import AnalysisBar
from app.tfex.errors import ReplayError
from app.tfex.marketdata.models import BarInterval

__all__ = ["FairValueGap", "FvgDirection", "FvgEngine", "FvgStatus", "FvgUpdate"]


class FvgDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FvgStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class FairValueGap:
    fvg_id: str
    symbol: str
    timeframe: BarInterval
    direction: FvgDirection
    lower_bound: Decimal
    upper_bound: Decimal
    source_bar_ids: tuple[str, str, str]
    formation_event_time: datetime
    confirmed_at: datetime
    status: FvgStatus
    updated_at: datetime
    filled_at: datetime | None = None
    invalidated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FvgUpdate:
    timeframe: BarInterval
    formed: tuple[FairValueGap, ...]
    changed: tuple[FairValueGap, ...]


class FvgEngine:
    """Form gaps at candle three close and update them only with later closed bars."""

    def __init__(self, timeframe: BarInterval) -> None:
        self.timeframe = timeframe
        self._bars: list[AnalysisBar] = []
        self._gaps: dict[str, FairValueGap] = {}
        self._symbol: str | None = None
        self._formed: list[FairValueGap] = []

    @property
    def formed(self) -> tuple[FairValueGap, ...]:
        return tuple(self._formed)

    @property
    def current(self) -> tuple[FairValueGap, ...]:
        return tuple(self._gaps.values())

    def update(self, bar: AnalysisBar) -> FvgUpdate:
        if bar.timeframe is not self.timeframe:
            raise ReplayError(f"FVG engine {self.timeframe.value} received {bar.timeframe.value}")
        if self._symbol is None:
            self._symbol = bar.symbol
        elif bar.symbol != self._symbol:
            raise ReplayError("FVG engine cannot mix raw contract symbols")
        if self._bars and bar.confirmed_at <= self._bars[len(self._bars) - 1].confirmed_at:
            raise ReplayError("FVG input must be strictly ordered by confirmation time")

        changed = self._update_existing(bar)
        self._bars.append(bar)
        formed = self._detect_formation()
        for gap in formed:
            self._gaps[gap.fvg_id] = gap
            self._formed.append(gap)
        return FvgUpdate(self.timeframe, formed, changed)

    def _update_existing(self, bar: AnalysisBar) -> tuple[FairValueGap, ...]:
        changed: list[FairValueGap] = []
        for gap_id, gap in tuple(self._gaps.items()):
            if gap.status in {FvgStatus.FILLED, FvgStatus.INVALIDATED}:
                continue
            if gap.confirmed_at > bar.event_time:
                continue
            replacement = self._updated_gap(gap, bar)
            if replacement != gap:
                self._gaps[gap_id] = replacement
                changed.append(replacement)
        return tuple(changed)

    @staticmethod
    def _updated_gap(gap: FairValueGap, bar: AnalysisBar) -> FairValueGap:
        if gap.direction is FvgDirection.BULLISH:
            if bar.close < gap.lower_bound:
                return replace(
                    gap,
                    status=FvgStatus.INVALIDATED,
                    updated_at=bar.confirmed_at,
                    invalidated_at=bar.confirmed_at,
                )
            if bar.low <= gap.lower_bound:
                return replace(
                    gap,
                    status=FvgStatus.FILLED,
                    updated_at=bar.confirmed_at,
                    filled_at=bar.confirmed_at,
                )
            if bar.low < gap.upper_bound and gap.status is FvgStatus.ACTIVE:
                return replace(
                    gap,
                    status=FvgStatus.PARTIALLY_FILLED,
                    updated_at=bar.confirmed_at,
                )
        else:
            if bar.close > gap.upper_bound:
                return replace(
                    gap,
                    status=FvgStatus.INVALIDATED,
                    updated_at=bar.confirmed_at,
                    invalidated_at=bar.confirmed_at,
                )
            if bar.high >= gap.upper_bound:
                return replace(
                    gap,
                    status=FvgStatus.FILLED,
                    updated_at=bar.confirmed_at,
                    filled_at=bar.confirmed_at,
                )
            if bar.high > gap.lower_bound and gap.status is FvgStatus.ACTIVE:
                return replace(
                    gap,
                    status=FvgStatus.PARTIALLY_FILLED,
                    updated_at=bar.confirmed_at,
                )
        return gap

    def _detect_formation(self) -> tuple[FairValueGap, ...]:
        if len(self._bars) < 3:
            return ()
        first = self._bars[len(self._bars) - 3]
        middle = self._bars[len(self._bars) - 2]
        third = self._bars[len(self._bars) - 1]
        if not self._is_contiguous_triplet(first, middle, third):
            return ()
        if third.low > first.high:
            return (self._make(first, middle, third, FvgDirection.BULLISH),)
        if third.high < first.low:
            return (self._make(first, middle, third, FvgDirection.BEARISH),)
        return ()

    def _is_contiguous_triplet(
        self,
        first: AnalysisBar,
        middle: AnalysisBar,
        third: AnalysisBar,
    ) -> bool:
        interval = timedelta(minutes=self.timeframe.minutes)
        return (
            first.session is middle.session
            and middle.session is third.session
            and first.open_time.date() == middle.open_time.date() == third.open_time.date()
            and middle.open_time == first.open_time + interval
            and third.open_time == middle.open_time + interval
        )

    @staticmethod
    def _make(
        first: AnalysisBar,
        middle: AnalysisBar,
        third: AnalysisBar,
        direction: FvgDirection,
    ) -> FairValueGap:
        lower, upper = (
            (first.high, third.low)
            if direction is FvgDirection.BULLISH
            else (third.high, first.low)
        )
        return FairValueGap(
            fvg_id=(
                f"fvg:{third.symbol}:{third.timeframe.value}:{direction.value}:"
                f"{third.event_time.isoformat()}"
            ),
            symbol=third.symbol,
            timeframe=third.timeframe,
            direction=direction,
            lower_bound=lower,
            upper_bound=upper,
            source_bar_ids=(first.bar_id, middle.bar_id, third.bar_id),
            formation_event_time=third.event_time,
            confirmed_at=third.confirmed_at,
            status=FvgStatus.ACTIVE,
            updated_at=third.confirmed_at,
        )
