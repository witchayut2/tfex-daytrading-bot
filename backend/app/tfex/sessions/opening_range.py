"""Morning and afternoon opening ranges (`CLAUDE_TFEX.md` section 13).

Not implemented — **Milestone TFEX-2**. Deliberately left empty rather than stubbed with a
plausible-looking calculation: an opening range that can be read before its window closes
is repaint risk R4 in `docs/tfex_repository_audit.md`, and a half-implementation is how that
bug gets in.

When implemented it must provide 5/15/30-minute ranges for both sessions, become readable
only after the window ends, and require a *closed* candle outside the range for a breakout.
"""

from __future__ import annotations

__all__: list[str] = []
