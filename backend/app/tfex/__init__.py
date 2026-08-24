"""TFEX SET50 Index Futures specialization.

Implemented (Milestone TFEX-1): configuration, official-source provenance, the trading
calendar and holiday import, last-trading-day and expiry resolution, contract symbol
parsing and resolution, the contract registry, the roll policy, and the session state
engine.

Not implemented: candles and replay (TFEX-2), market structure and liquidity (TFEX-3),
strategies and the risk engine (TFEX-4), paper execution (TFEX-5), the dashboard (TFEX-6),
and the read-only real-time adapter (TFEX-7). There is no live order route in this build.
"""

from app.tfex.config import TfexConfig, default_config, load_config
from app.tfex.errors import TfexError

__all__ = ["TfexConfig", "TfexError", "default_config", "load_config"]
