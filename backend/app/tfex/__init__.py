"""TFEX SET50 Index Futures specialization.

Implemented through Milestone TFEX-3: configuration and official metadata,
contract/session resolution, deterministic raw-contract replay, session-aligned 1m/5m/15m
market state, and neutral causal pivots, structure, Order Blocks, liquidity, sweeps, FVGs,
and regime infrastructure.

Not implemented: calibrated volatility thresholds or a researched total liquidity rank,
strategies/runtime risk wiring (TFEX-4), paper execution (TFEX-5), the dashboard (TFEX-6),
and the read-only real-time adapter (TFEX-7). There is no live order route in this build.
"""

from app.tfex.config import TfexConfig, default_config, load_config
from app.tfex.errors import TfexError

__all__ = ["TfexConfig", "TfexError", "default_config", "load_config"]
