"""THB 200 per point sizing. risk_thb = |entry - stop| * 200 * contracts, plus.

Not implemented — **Milestone TFEX-4**.

THB 200 per point sizing. risk_thb = |entry - stop| * 200 * contracts, plus
round-trip costs. Section 21: never size a position from margin — margin is a
collateral requirement, not a maximum acceptable loss.
"""

from __future__ import annotations

__all__: list[str] = []
