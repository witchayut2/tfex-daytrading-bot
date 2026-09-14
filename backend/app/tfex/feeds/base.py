"""Causal event types shared by replay and future read-only real-time sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from app.tfex.sessions.boundaries import ContinuousSession, SessionState

if TYPE_CHECKING:
    from app.tfex.marketdata.models import Bar

__all__ = ["MarketEvent", "ReplayStatus"]


class ReplayStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    END_OF_DATA = "END_OF_DATA"


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One closed source bar released at the replay cursor, never before bar close."""

    sequence: int
    bar: Bar
    event_time: datetime
    confirmed_at: datetime
    session_state: SessionState
    continuous_session: ContinuousSession
