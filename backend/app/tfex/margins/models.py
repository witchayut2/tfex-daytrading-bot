"""Versioned margin records: contract family, series, outright/spread, initial,.

Not implemented — **Milestone TFEX-4**.

Versioned margin records: contract family, series, outright/spread, initial,
maintenance and force-close margin, effective timestamp, source, retrieved_at,
verified, stale_after and broker override. Section 22 forbids embedding a single
current margin number in strategy code, so there is no constant to add here now.
"""

from __future__ import annotations

__all__: list[str] = []
