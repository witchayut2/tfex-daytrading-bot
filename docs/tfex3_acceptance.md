# TFEX-3 Acceptance Matrix

Status: **`TFEX3_COMPLETE`**

TFEX-2 remains `TFEX2_COMPLETE`. TFEX-3 consumes immutable closed-bar market state and
emits neutral analysis only. It has no strategy, `TradeProposal`, risk-runtime, broker, or
order path. Live trading remains disabled. Canonical definitions and rejected alternatives
are recorded in `docs/tfex3_definition_lock.md`.

## Locked causal definitions

- **Pivot:** strict wick extremum against caller-supplied left/right closed bars. The real
  acceptance run declares `2x2`; confirmation waits for the final right bar.
- **Structure:** consecutive same-type confirmed pivots produce HH/HL/LH/LL/equality.
  Only a closed candle strictly beyond the latest confirmed swing creates BOS/CHoCH.
- **Order Block:** a BOS records the latest confirmed opposite-pivot leg anchor. The last
  opposite closed candle strictly after that anchor event and strictly before the BOS bar
  supplies its complete low/high zone. Bullish uses a bearish candle; bearish mirrors it.
  One or zero zones exist per BOS, confirmation equals BOS confirmation, and lifecycle is
  `ACTIVE -> MITIGATED -> INVALIDATED` from strictly later same-timeframe closed bars.
- **Structure regime:** closed 15m relations map HH+HL to `BULLISH_STRUCTURE`, LH+LL to
  `BEARISH_STRUCTURE`, LH+HL to `CONTRACTION_STRUCTURE`, HH+LL to
  `EXPANSION_STRUCTURE`, and all incomplete/equal conflicts to `UNRESOLVED`.
- **Volatility regime:** provenance-bearing external thresholds classify a causal supplied
  observation as `LOW`, `NORMAL`, or `HIGH`. Missing evidence returns `UNCALIBRATED`.
  There is no fitting method, evaluation-data calibration is rejected, and structure x
  volatility is a neutral composite rather than a trade direction.
- **Liquidity:** confirmed pivots, exact equal pivots, previous-day/session finalized
  high/low, and confirmed opening ranges create immutable raw-symbol levels. A later wick
  exceed plus closed reclaim is a sweep; close beyond invalidates.
- **Liquidity importance:** the engine exposes deterministic confirmation, timeframe,
  categorical source, confluence, age, and swept-state features. Stable level-ID order is
  presentation only. Homogeneous vectors have a Pareto partial order; different
  sources/timeframes are incomparable. No weights or source hierarchy are invented.
- **Confluence:** absent an explicit tick tolerance, only exact-price, same-symbol,
  confirmed levels count. A nonzero tolerance requires explicit ticks and tick size.
- **FVG:** three contiguous closed candles in one session form a strict gap at candle three
  close; later bars create immutable partial/fill/invalidation revisions.

## Requirement evidence

| Requirement | Implementation | Test/evidence | Status |
| --- | --- | --- | --- |
| TFEX-2 prerequisite | Existing `marketdata/replay.py` | `TFEX2_COMPLETE`, real five-day replay | PASS |
| Delayed 1m/5m/15m pivots | `analysis/pivots.py` | Explicit strength and delayed-right-bar tests | PASS |
| HH/HL/LH/LL and equality | `analysis/structure.py` | All relations from confirmed pivots | PASS |
| BOS / CHoCH | `analysis/structure.py` | Wick rejection, close break, anchor, prior-bias tests | PASS |
| Bullish/bearish OB selection | `analysis/order_blocks.py` | Last opposite candle after exact anchor | PASS |
| OB absence/lifecycle | `analysis/order_blocks.py` | No eligible candle, CHoCH exclusion, later mitigation/invalidation | PASS |
| Structure regime | `analysis/regime.py` | All four 15m mappings plus unresolved/forming isolation | PASS |
| Volatility infrastructure | `analysis/regime.py` | Supplied thresholds, absent thresholds, calibration leakage rejection | PASS |
| Composite regime | `analysis/regime.py` | Immutable structure x volatility label; no action | PASS |
| Liquidity sources/lifecycle | `liquidity/` | Final-session/opening-range leakage and sweep tests | PASS |
| Importance features | `liquidity/importance.py` | Deterministic extraction, stable presentation, partial order | PASS |
| Exact/configured confluence | `liquidity/importance.py` | Exact default and explicit one-tick test | PASS |
| Liquidity as-of safety | `liquidity/importance.py` | Future level excluded; future revision rejected | PASS |
| FVG formation/lifecycle | `analysis/fvg.py` | Third-close formation and later fill tests | PASS |
| Batch versus incremental | `analysis/engine.py` | Exact frames/results and digest | PASS |
| Prefix/future mutation/restart | Streaming engines | Confirmed prefixes remain identical | PASS |
| Raw contract/timezone | All artifacts retain identity/times | S50U26 and Bangkok-aware assertions | PASS |
| Real-data acceptance | Ignored validated five-day dataset | 1,775 causal frames and deterministic checks | PASS |
| Strategy/order isolation | No strategy or broker dependency | Forbidden order-surface assertion | PASS |
| Static leakage audit | TFEX source scan | No future shifts, centered windows, or future extrema | PASS |

## Real S50U26 observations

Dataset `s50u26-1m-20260908-20260914-settrade-extended`, normalized SHA-256
`b916b86e595df0bfbdc6652871202be2c5619b2cfc3196fd6b6daaf0fed24456`, produced these
observations with pivot rule `TFEX3_STRICT_WICK_2X2_V1`:

| Artifact | Observed count |
| --- | ---: |
| Source frames | 1,775 |
| Confirmed pivots | 393 |
| BOS | 106 |
| CHoCH | 32 |
| Liquidity levels | 514 |
| Confirmed sweeps | 152 |
| Fair-value gaps | 401 |
| Order Blocks | 70 |
| BOS with explicit `NO_ORDER_BLOCK` | 36 |
| Order Blocks active | 6 |
| Order Blocks mitigated | 2 |
| Order Blocks invalidated | 62 |

Structure-regime frame counts: `BULLISH_STRUCTURE=320`, `BEARISH_STRUCTURE=465`,
`CONTRACTION_STRUCTURE=250`, `EXPANSION_STRUCTURE=241`, `UNRESOLVED=499`.
Volatility-regime frame counts: `UNCALIBRATED=1775`.

Exact-price confluence distribution (`confluence_count: level_count`):
`1:34, 2:40, 3:60, 4:84, 5:30, 6:72, 7:70, 8:24, 9:27, 10:10, 11:22, 12:24, 17:17`.

TFEX-3 analysis digest:
`cb6bb31d9a4a812f57b8b97c7eab20d8c7f25f46473144fd71444a3e5f74ee8b`.

Counts are observations, not tuned acceptance targets or efficacy evidence. Licensed rows
remain local, immutable, and ignored.

## Verification

```text
uv run pytest tests/tfex/test_tfex3_definition_lock.py tests/tfex/test_tfex3_structure.py
                                                  36 passed
uv run pytest tests/tfex                    570 passed, 1 skipped
uv run pytest -m anti_repaint                56 passed, 515 deselected
uv run pytest -m real_market_data            38 passed, 533 deselected
uv run ruff check .                          All checks passed
uv run ruff format --check .                 125 files already formatted
uv run mypy .                                Success - 122 source files
```

The one skip is the existing optional installed Settrade SDK signature check.

## Decision and research boundary

Every mandatory TFEX-3 analysis component now has a deterministic, non-repainting rule and
passing fixture plus real-data evidence. **`TFEX3_COMPLETE`.**

Numeric volatility thresholds, nonzero confluence tolerance, and any liquidity source
hierarchy, weights, or total-ranking rule remain deliberately `UNCALIBRATED` and belong to
a future declared calibration/search protocol. They are not hidden defaults and are not
missing TFEX-3 infrastructure. No strategy research has started; TFEX-4 is
`TFEX4_NOT_STARTED`.
