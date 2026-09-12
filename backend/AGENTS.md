# backend/AGENTS.md — TFEX Backend

This file extends the repository-root `AGENTS.md`.

## Verification commands
After meaningful backend changes:

```bash
uv run pytest tests/tfex
uv run pytest -m anti_repaint
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

When real licensed market data is locally available:

```bash
uv run pytest -m real_market_data
```

Skipped `real_market_data` tests do not count as real-data validation.

## Settrade integration boundary
Current Settrade work is READ-ONLY.

Allowed:
- authentication capability check
- symbol lookup
- market-data lookup
- historical candlestick probe/download where authorized

Forbidden:
- place order
- change order
- cancel order
- production/live execution

## Credentials
Read process environment variables only:

- SETTRADE_APP_ID
- SETTRADE_APP_SECRET
- SETTRADE_BROKER_ID
- SETTRADE_APP_CODE

Never print secret values.

## Market-data validation
Real data must pass the existing validator before replay/acceptance use.

Checks include at least:
- timestamp
- timezone
- OHLC
- tick compatibility
- volume
- duplicate/conflicting duplicate
- missing bars
- session boundaries
- contract identity
- expiry/LTD
- provenance/checksum

Raw input is immutable.

Preferred layout:

```text
data/tfex/historical/
  raw/<SYMBOL>/
  normalized/<SYMBOL>/
  manifests/
```

Do not commit licensed raw market data unless the license clearly permits it.

## Replay / aggregation
Replay exposes only data at or before cursor.

Seek rebuilds state deterministically; it must not retain future-derived state.

1m -> 5m / 15m aggregation follows TFEX session boundaries.

No bucket spans midday break.

## Fees
Keep distinct:
- verified exchange fee cap
- broker actual exchange fee
- broker commission
- estimated/slippage costs
- actual cost

A cap is not an actual charge.
