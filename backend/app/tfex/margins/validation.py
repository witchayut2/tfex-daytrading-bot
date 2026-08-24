"""Freshness and sanity checks on imported margin data. With.

Not implemented — **Milestone TFEX-4**.

Freshness and sanity checks on imported margin data. With
``margin.reject_when_stale`` set, stale margin blocks new positions rather than
falling back to the last known value (repaint/risk hazard R9).
"""

from __future__ import annotations

__all__: list[str] = []
