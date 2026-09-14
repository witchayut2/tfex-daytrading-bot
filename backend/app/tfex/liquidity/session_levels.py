"""Causal session, previous-day, and opening-range liquidity sources."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.tfex.liquidity.levels import (
    LiquidityLevel,
    LiquidityLevelSource,
    LiquiditySide,
)
from app.tfex.marketdata.models import BarInterval
from app.tfex.marketdata.replay import ReplayFrame
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.opening_range import OpeningRangeState
from app.tfex.sessions.snapshots import SessionProfile

__all__ = ["SessionLiquiditySourceEngine"]


class SessionLiquiditySourceEngine:
    """Emit each final reference once, never from provisional session extrema."""

    def __init__(self) -> None:
        self._emitted: set[str] = set()

    def update(self, frame: ReplayFrame) -> tuple[LiquidityLevel, ...]:
        created_at = frame.event.confirmed_at
        candidates: list[LiquidityLevel] = []
        previous = frame.sessions.previous_day
        if previous is not None and previous.is_final and previous.finalized_at is not None:
            candidates.extend(self._profile_levels(previous, created_at=created_at, previous=True))

        for profile in (frame.sessions.morning, frame.sessions.afternoon):
            if profile is not None and profile.is_final and profile.finalized_at is not None:
                candidates.extend(
                    self._profile_levels(profile, created_at=created_at, previous=False)
                )

        for opening_range in frame.opening_ranges.ranges:
            if opening_range.is_confirmed and opening_range.confirmed_at is not None:
                candidates.extend(self._opening_range_levels(opening_range, created_at=created_at))

        new = tuple(level for level in candidates if level.level_id not in self._emitted)
        self._emitted.update(level.level_id for level in new)
        return new

    @staticmethod
    def _profile_levels(
        profile: SessionProfile,
        *,
        created_at: datetime,
        previous: bool,
    ) -> tuple[LiquidityLevel, LiquidityLevel]:
        if profile.finalized_at is None:
            raise ValueError("session liquidity requires a finalized profile")
        if previous:
            high_source = LiquidityLevelSource.PREVIOUS_DAY_HIGH
            low_source = LiquidityLevelSource.PREVIOUS_DAY_LOW
            label = "previous-day"
            source_session = None
        elif profile.session is ContinuousSession.MORNING:
            high_source = LiquidityLevelSource.MORNING_HIGH
            low_source = LiquidityLevelSource.MORNING_LOW
            label = "morning"
            source_session = ContinuousSession.MORNING
        else:
            high_source = LiquidityLevelSource.AFTERNOON_HIGH
            low_source = LiquidityLevelSource.AFTERNOON_LOW
            label = "afternoon"
            source_session = ContinuousSession.AFTERNOON
        base_id = f"session:{profile.symbol}:{profile.trading_date.isoformat()}:{label}"
        return (
            SessionLiquiditySourceEngine._make_level(
                level_id=f"liquidity:{base_id}:high",
                profile=profile,
                price=profile.high,
                side=LiquiditySide.HIGH,
                source=high_source,
                source_session=source_session,
                created_at=created_at,
            ),
            SessionLiquiditySourceEngine._make_level(
                level_id=f"liquidity:{base_id}:low",
                profile=profile,
                price=profile.low,
                side=LiquiditySide.LOW,
                source=low_source,
                source_session=source_session,
                created_at=created_at,
            ),
        )

    @staticmethod
    def _make_level(
        *,
        level_id: str,
        profile: SessionProfile,
        price: Decimal,
        side: LiquiditySide,
        source: LiquidityLevelSource,
        source_session: ContinuousSession | None,
        created_at: datetime,
    ) -> LiquidityLevel:
        if profile.finalized_at is None:
            raise ValueError("session liquidity requires a confirmation time")
        return LiquidityLevel(
            level_id=level_id,
            symbol=profile.symbol,
            timeframe=BarInterval.ONE_MINUTE,
            side=side,
            source=source,
            price=price,
            event_time=profile.event_time,
            created_at=created_at,
            confirmed_at=profile.finalized_at,
            updated_at=created_at,
            source_object_ids=(base_profile_id(profile),),
            source_session=source_session,
        )

    @staticmethod
    def _opening_range_levels(
        opening_range: OpeningRangeState,
        *,
        created_at: datetime,
    ) -> tuple[LiquidityLevel, LiquidityLevel]:
        if (
            opening_range.confirmed_at is None
            or opening_range.confirmed_high is None
            or opening_range.confirmed_low is None
        ):
            raise ValueError("opening-range liquidity requires confirmed bounds")
        base = (
            f"or:{opening_range.symbol}:{opening_range.trading_date.isoformat()}:"
            f"{opening_range.session.value}:{opening_range.window_minutes}m"
        )
        return (
            LiquidityLevel(
                level_id=f"liquidity:{base}:high",
                symbol=opening_range.symbol,
                timeframe=BarInterval.ONE_MINUTE,
                side=LiquiditySide.HIGH,
                source=LiquidityLevelSource.OPENING_RANGE_HIGH,
                price=opening_range.confirmed_high,
                event_time=opening_range.event_time,
                created_at=created_at,
                confirmed_at=opening_range.confirmed_at,
                updated_at=created_at,
                source_object_ids=(base,),
                source_session=opening_range.session,
            ),
            LiquidityLevel(
                level_id=f"liquidity:{base}:low",
                symbol=opening_range.symbol,
                timeframe=BarInterval.ONE_MINUTE,
                side=LiquiditySide.LOW,
                source=LiquidityLevelSource.OPENING_RANGE_LOW,
                price=opening_range.confirmed_low,
                event_time=opening_range.event_time,
                created_at=created_at,
                confirmed_at=opening_range.confirmed_at,
                updated_at=created_at,
                source_object_ids=(base,),
                source_session=opening_range.session,
            ),
        )


def base_profile_id(profile: SessionProfile) -> str:
    session = profile.session.value if profile.session is not None else "FULL_DAY"
    return f"profile:{profile.symbol}:{profile.trading_date.isoformat()}:{session}"
