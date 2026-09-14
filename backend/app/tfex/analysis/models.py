"""Shared immutable inputs for causal TFEX-3 analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.tfex.errors import ReplayError
from app.tfex.marketdata.models import BarInterval
from app.tfex.sessions.boundaries import ContinuousSession

__all__ = ["AnalysisBar"]


@dataclass(frozen=True, slots=True)
class AnalysisBar:
    """One closed bar made available to TFEX-3 at ``confirmed_at``."""

    symbol: str
    timeframe: BarInterval
    source_sequence: int
    session: ContinuousSession
    open_time: datetime
    event_time: datetime
    confirmed_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ReplayError("analysis bar requires a raw contract symbol")
        if self.source_sequence <= 0:
            raise ReplayError("analysis bar source_sequence must be positive")
        if any(
            moment.tzinfo is None for moment in (self.open_time, self.event_time, self.confirmed_at)
        ):
            raise ReplayError("analysis bar timestamps must be timezone-aware")
        if self.confirmed_at <= self.event_time:
            raise ReplayError("analysis bar must be confirmed after its market event")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ReplayError("analysis bar violates OHLC ordering")
        if self.high < self.low:
            raise ReplayError("analysis bar high is below low")
        if self.volume < 0:
            raise ReplayError("analysis bar volume cannot be negative")

    @property
    def bar_id(self) -> str:
        return (
            f"bar:{self.symbol}:{self.timeframe.value}:"
            f"{self.open_time.isoformat()}:{self.source_sequence}"
        )
