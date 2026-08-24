"""The ranked liquidity map. Every level must carry event_time, confirmed_at,.

Not implemented — **Milestone TFEX-3**.

The ranked liquidity map. Every level must carry event_time, confirmed_at,
availability status, contract symbol, source session and source object IDs —
``confirmed_at`` is what stops a level leaking backwards (repaint risk R5).
"""

from __future__ import annotations

__all__: list[str] = []
