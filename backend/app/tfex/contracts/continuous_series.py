"""Research continuous series (`CLAUDE_TFEX.md` section 7).

Not implemented — **Milestone TFEX-2**.

The rule it must not break, recorded here so it is not rediscovered later: two datasets
exist, the **raw contract series** (never adjusted, the only thing execution may touch) and
the **research continuous series** (explicitly labelled, long-window context only). Section
27 forbids continuous-series adjustment from altering execution prices, and section 30
forbids reporting continuous-series performance without raw-contract execution validation.
That is repaint risk R7 in `docs/tfex_repository_audit.md`.
"""

from __future__ import annotations

__all__: list[str] = []
