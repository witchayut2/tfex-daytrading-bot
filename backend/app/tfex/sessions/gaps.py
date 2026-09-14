"""Causal TFEX opening, midday, and informational raw-contract roll gaps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.errors import ReplayError

__all__ = ["GapKind", "GapLevel", "make_gap", "make_roll_gap"]


class GapKind(StrEnum):
    OVERNIGHT_FROM_CLOSE = "OVERNIGHT_FROM_CLOSE"
    OVERNIGHT_FROM_SETTLEMENT = "OVERNIGHT_FROM_SETTLEMENT"
    MIDDAY = "MIDDAY"
    ROLL = "ROLL"


@dataclass(frozen=True, slots=True)
class GapLevel:
    kind: GapKind
    from_symbol: str
    to_symbol: str
    reference_price: Decimal
    opening_price: Decimal
    points: Decimal
    event_time: datetime
    confirmed_at: datetime


def make_gap(
    *,
    kind: GapKind,
    from_symbol: str,
    to_symbol: str,
    reference_price: Decimal,
    opening_price: Decimal,
    event_time: datetime,
    confirmed_at: datetime,
) -> GapLevel:
    """Create a gap only when its opening event has become observable."""
    if event_time.tzinfo is None or confirmed_at.tzinfo is None:
        raise ReplayError("gap timestamps must be timezone-aware")
    if confirmed_at <= event_time:
        raise ReplayError("a gap may be confirmed only after its opening event")
    return GapLevel(
        kind=kind,
        from_symbol=from_symbol,
        to_symbol=to_symbol,
        reference_price=reference_price,
        opening_price=opening_price,
        points=opening_price - reference_price,
        event_time=event_time,
        confirmed_at=confirmed_at,
    )


def make_roll_gap(
    *,
    outgoing_symbol: str,
    outgoing_close: Decimal,
    incoming_symbol: str,
    incoming_open: Decimal,
    event_time: datetime,
    confirmed_at: datetime,
) -> GapLevel:
    """Describe, but never splice or back-adjust, a transition between two raw contracts."""
    if outgoing_symbol == incoming_symbol:
        raise ReplayError("a roll gap requires two distinct raw contract symbols")
    return make_gap(
        kind=GapKind.ROLL,
        from_symbol=outgoing_symbol,
        to_symbol=incoming_symbol,
        reference_price=outgoing_close,
        opening_price=incoming_open,
        event_time=event_time,
        confirmed_at=confirmed_at,
    )
