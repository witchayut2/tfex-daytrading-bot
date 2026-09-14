# TFEX-2 Acceptance Matrix

Status: **TFEX2_COMPLETE**

Data-readiness remains `READY_FOR_TFEX2`. This matrix covers only the canonical TFEX-2
market-data/replay milestone. It does not authorize TFEX-3 strategies, risk activation,
paper execution, broker access, or live orders.

| Requirement | Implementation | Test | Status | Evidence |
| --- | --- | --- | --- | --- |
| Raw-contract CSV import | `feeds/csv_feed.py` uses the existing manifest/checksum loader and rejects parse loss, non-1m input, symbol disagreement, and synthetic input when real data is required | `test_manifest_aware_csv_replay_preserves_dataset_identity`; real replay tests | PASS | Dataset ID, raw S50U26 identity, and normalized SHA-256 survive replay |
| Chronological one-event replay | `marketdata/replay.py` releases one closed source bar per cursor step | `test_replay_controls_release_exactly_one_ordered_event_at_a_time` | PASS | Strict ordering, explicit sequence, `event_time`, and `confirmed_at` |
| Start/pause/step/end/restart/seek | `ReplayEngine`; seek performs full prefix reconstruction | `test_restart_and_reconstructive_seek_are_stable` | PASS | Restart and seek reproduce identical immutable frames |
| Verified TFEX session states | Existing `SessionEngine` plus `ContinuousSession` mapping | `test_5m_and_15m_buckets_are_session_aligned_and_never_bridge_lunch`; existing session suites | PASS | Canonical enum names retained; Bangkok timezone and LTD plan used |
| 1m source semantics | `MarketEvent` wraps each closed canonical `Bar` without mutation | replay control, identity, and real 1m tests | PASS | One frame per source row; five-day run emits 1,775 frames |
| 5m aggregation | `TimeframeAggregator(5m)` | OHLCV, lunch alignment, forming isolation, real 5m tests | PASS | Five-day S50U26 run emits 355 confirmed 5m bars |
| 15m aggregation | `TimeframeAggregator(15m)` | lunch alignment, forming isolation, real 15m tests | PASS | Five-day run emits 120 confirmed 15m bars; 10-minute close bucket explicit |
| Missing-minute fail closed | Aggregators require contiguous constituents | `test_missing_one_minute_constituents_fail_instead_of_being_filled` | PASS | No interpolation or forward fill |
| Midday/overnight isolation | Buckets are anchored independently to each session plan | aggregation tests; existing midday-break suite | PASS | No bucket spans 12:30–13:45, a date, or a contract |
| Full-day and session VWAP | `marketdata/vwap.py`; HLC3 basis; full-day pauses over lunch, session modes reset independently | VWAP causality/reset/zero-volume tests | PASS | No future volume; zero cumulative volume returns `None` |
| Morning/afternoon snapshots | `sessions/snapshots.py` separates running values from final profiles | `test_reference_levels_distinguish_current_from_confirmed` | PASS | Morning/final-day values confirm only at actual close |
| Opening ranges | `sessions/opening_range.py`; 5/15/30 minutes independently for both sessions | opening-range and reference tests | PASS | Final levels are `None` until range close and immutable afterward |
| Overnight/midday gaps | Timestamped `GapLevel` artifacts | reference-level test | PASS | Gaps appear after the opening one-minute event confirms |
| Roll gap | Informational `make_roll_gap` retains outgoing and incoming raw symbols | `test_roll_gap_is_informational_and_keeps_both_raw_symbols` | PASS | No splice, back-adjustment, or continuous series |
| Current versus confirmed levels | `ReferenceLevels` exposes provisional extrema separately from final fields | reference-level and future-mutation tests | PASS | Full morning high is unavailable as final at 10:00 |
| Batch/incremental equivalence | Batch API delegates to incremental replay | synthetic and real equivalence tests | PASS | Exact frame equality and matching deterministic digest |
| Prefix stability | Every frame is frozen and derived only from released prefix | synthetic and real prefix tests | PASS | Prefix output equals the corresponding full-run prefix |
| Future-mutation stability | No processor indexes a later source row | `test_batch_incremental_prefix_and_future_mutation_are_equivalent` | PASS | Mutating bar 501 leaves first 420 frames unchanged |
| Forming-candle isolation | Forming aggregate is separate and carries no `confirmed_at` | `test_forming_higher_timeframes_never_enter_confirmed_history` | PASS | 5m/15m enters history only at bucket close |
| Real-data acceptance | Existing validator plus matching replay completion guard | `test_only_minimum_history_real_replay_can_complete_tfex2` | PASS | Dataset `s50u26-1m-20260908-20260914-settrade-extended`, 1,775 rows |
| No trading/order path | TFEX-2 has no proposal, risk, broker, or order dependency | `test_replay_has_no_order_or_trading_activation_surface`; full safety suites | PASS | `live_orders_enabled` remains false |

## Five-day replay evidence

- Dataset SHA-256: `b916b86e595df0bfbdc6652871202be2c5619b2cfc3196fd6b6daaf0fed24456`
- Source events: 1,775
- Confirmed 5m bars: 355
- Confirmed 15m bars: 120
- Deterministic replay digest:
  `413e6430720ed94ad4e2ae7c283d60fd6eb32f555cb75b2b181d7ddb9aa121e6`

Licensed source and normalized rows remain ignored and are not reproduced here.

## Final verification

```text
uv run pytest tests/tfex          530 passed, 1 skipped
uv run pytest -m anti_repaint      31 passed, 500 deselected
uv run pytest -m real_market_data  34 passed, 497 deselected
uv run ruff check .                All checks passed
uv run ruff format --check .       113 files already formatted
uv run mypy .                      Success - 110 source files
```

The one skip is the existing optional installed Settrade SDK signature check. TFEX-2 is
complete; TFEX-3 remains not started and requires separate authorization.
