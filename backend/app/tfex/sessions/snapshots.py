"""Immutable session profiles (`CLAUDE_TFEX.md` section 11).

Not implemented — **Milestone TFEX-2**.

The invariant it must carry: live session highs and lows are *provisional* until the session
closes, and a confirmed value may never be backdated. Every snapshot field will carry both
``event_time`` and ``confirmed_at`` so a strategy physically cannot read a level before the
system was allowed to know it (repaint risk R1).
"""

from __future__ import annotations

__all__: list[str] = []
