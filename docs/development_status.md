# Development Status

Last updated: **2026-09-15**
Current status label: **TFEX-2 and TFEX-3 complete — not yet a trading system**

> Not ready for real money. `CLAUDE_TFEX.md` section 32 lists sixteen gates before real
> orders may even be considered; none are met, and no broker order route exists in this build.

---

## Milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| **TFEX-0** | Audit | ✅ Complete — `docs/tfex_repository_audit.md` |
| **TFEX-1** | Configuration, official-source registry, symbol parser, contract registry, trading calendar, holiday import, last-trading-day model, session state engine, tests | ✅ Complete, and now running on **real imported exchange data** |
| **Data-readiness gate** | Baseline preservation, real calendar import, fee semantics, market-data validator, acceptance gate, source research | ✅ **`READY_FOR_TFEX2`** — five-day real-data, validation, checksum, and lineage evidence passed (`docs/tfex_data_readiness_gate.md`) |
| **TFEX-2** | TFEX-aligned replay: CSV import, 1m/5m/15m aggregation, midday break, session snapshots, VWAP, opening ranges, gap engine | ✅ **Complete — real five-day replay and all mandatory acceptance checks pass.** Status `TFEX2_COMPLETE` |
| **TFEX-3** | Analysis: pivots, structure, BOS, CHoCH, liquidity map, sweeps, FVG, order blocks, regime | ✅ **Complete.** Status `TFEX3_COMPLETE`; numeric calibration remains future research |
| TFEX-4 | Strategies A and B, scoring, sizing, margin/expiry/session gates, kill switch | ⬜ **`TFEX4_NOT_STARTED`** — deterministic definition locked; research prerequisites and implementation remain outstanding |
| TFEX-5 | Paper execution: broker, order state machine, costs, next-bar fills, P&L, EOD flatten | ⬜ Not started — dormant state contract/unit scaffold only |
| TFEX-6 | Visual dashboard | ⬜ Not started |
| TFEX-7 | Read-only real-time adapter | ⬜ Not started |

## Checks (last run 2026-09-14)

| Command | Result |
| --- | --- |
| `uv run pytest tests/tfex/test_tfex3_definition_lock.py tests/tfex/test_tfex3_structure.py` | **36 passed** |
| `uv run pytest tests/tfex` | **570 passed, 1 skipped** |
| `uv run pytest -m anti_repaint` | **56 passed, 515 deselected** |
| `uv run pytest -m real_market_data` | **38 passed, 533 deselected** — validator, TFEX-2, and causal TFEX-3 acceptance on parent and five-day child |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 125 files already formatted |
| `uv run mypy .` | Success — 122 source files |
| `scripts/validate_calendar_data.py --year 2026` | PASS — all 9 proofs |
| `scripts/import_tfex_contracts.py` | 6 contracts, **0 conflicts** |
| Frontend | Not applicable until TFEX-6 |
| Docker | Not applicable — no compose file yet |

Baseline before the gate: 277 passed / 12 anti-repaint / 71 mypy files
(`docs/data_readiness_baseline.md`). No test was weakened.

## Real exchange data now in the repository

| Data | Coverage | Status |
| --- | --- | --- |
| TFEX holiday calendar | **2026 only** — 20 holidays, 2 exchange special holidays | `VERIFIED_OFFICIAL` |
| SET50 futures contract calendar | 6 listed contracts (Q26, U26, V26, Z26, H27, M27) | 4 `VERIFIED`, 2 `PUBLISHED_UNVERIFIED` |
| Contract terms (tick size, point value) | corroborated against the exchange series endpoint | `CROSS_CHECKED` |
| 1-minute market data | S50U26, five dates from 2026-09-08 through 2026-09-14, 1,775 rows | `REAL_DATA_VALIDATED`; five-day minimum met with lineage/checksums verified |

Licensed raw market captures and normalized derivatives live under
`backend/data/tfex/historical/` and remain ignored by Git. Their manifests retain SHA-256
provenance. The sanitized Settrade capability result is also local/untracked because it is
operator/application-specific; universal SDK/API facts are kept in tests and canonical docs.

## Future risk/order contract locked without activation

`docs/tfex_risk_order_position_contract.md` now fixes the mandatory
`TradeProposal -> RiskEngine -> ApprovedTradePlan -> future execution` boundary, exact THB
risk equations, stop/partial-fill/EOD/kill behaviour, lifecycle/recovery states, and audit
shape. The corresponding pure models/reducers are deterministic unit-test scaffolding only:
no strategy, broker adapter, runtime wiring, or order method was added. All numerical risk
thresholds ship `null`/`UNCALIBRATED`, so the scaffold fails closed by default.

## Future strategy-research protocol locked without activation

`docs/tfex_strategy_research_validation_protocol.md` now fixes chronological A/B/C/D
partitions, single-use final holdouts, anchored/rolling walk-forward evidence, leakage and
next-event execution rules, research cost provenance, complete metrics, append-only trial
history, independent strategy/subgroup reporting, forward/paper distinctions, and fail-closed
acceptance states. Its pure model/test scaffold contains no replay, strategy, optimizer,
broker, or order route. Performance and risk thresholds remain `UNCALIBRATED`, so no
strategy can advance beyond `RESEARCH_ONLY`.

## TFEX-4 definition locked without implementation

`docs/tfex4_definition_lock.md` fixes the causal Strategy A/B state machines, deterministic
zone/entry/stop semantics, explanatory scoring, the quantity-free `TradeProposal` boundary,
pre-trade gate order, research-mode health evidence, margin history contract, and the exact
meaning of eventual `TFEX4_COMPLETE`. Numeric alpha/risk choices remain uncalibrated or
deferred to research. The total-post-trade portfolio margin free-equity formula is locked;
its numeric required buffer remains uncalibrated. TFEX-4 remains `TFEX4_NOT_STARTED`.

## Completed boundary and outstanding work

1. **TFEX-3 is complete under explicit authorization.** The locked neutral layer includes
   causal pivots/structure/BOS/CHoCH, deterministic Order Blocks, liquidity levels/sweeps
   and unweighted importance features, FVGs, and structure x volatility regimes. Numeric
   volatility calibration and total ranking remain future declared research. TFEX-4
   implementation and strategy research have not started; its deterministic scope is now
   locked in `docs/tfex4_definition_lock.md`. See `docs/tfex3_definition_lock.md` and
   `docs/tfex3_acceptance.md`.
2. **Import the 2027 holiday calendar** when TFEX publishes it. The endpoint serves only the
   current display year; 2025 and 2027 return HTTP 401 today. Until 2027 lands, S50H27 and
   S50M27 have no cross-checked expiry and anything reaching into 2027 fails closed.
3. **Verify the actual exchange fee and broker commission** against a statement or agreement.

## Known gaps and risks

- **The holiday calendar covers one year.** A replay spanning a year boundary will fail
  closed, which is correct but limiting. `required_years_for` now pads a neighbouring year
  only when the range comes within 31 days of the boundary, so mid-year work is not blocked
  by a year nobody has published yet.
- **Shortened sessions are unverified.** The annual trading calendar page was not retrieved,
  so announced early closes are not in the data. An unannounced early close would make the
  expected bar grid over-strict, showing up as a `SOURCE_DATA_GAP` warning.
- **`symbol.minimum_contract_year: 2006` is still a research default.** Verify against the
  exchange's listing history before relying on it to reject old symbols.
- **Every roll threshold is a research default**, uncalibrated. Section 7 says so explicitly.
- **Six of ten official sources remain `NOT_VERIFIED`**, including both margin pages.
- **No cost figure is production-ready.** The exchange fee cap is verified as a *cap*; the
  actual fee and the commission are `UNKNOWN` and cannot be charged in any scenario.
- **Risk limits are intentionally uncalibrated.** The future policy needs research-backed
  values for per-trade/daily loss, consecutive-loss, contract, RRR, slippage, and execution
  error limits before paper-strategy work can use it.
- **TFEX-3 numeric research remains uncalibrated by design.** Volatility cutoffs, nonzero
  confluence tolerance, and a total liquidity source/weight ranking require declared
  calibration evidence. Neutral infrastructure fails closed or stays partially ordered.
- Audit repaint risks R1–R7 and R10–R12 now have structural/behavioral coverage in their
  implemented layers. R8 (same-bar fills) and R9 (retroactive margin) remain future runtime
  concerns; their dormant contracts do not activate execution.

## Definition of done (section 34) — progress

**Met:** official contract metadata represented and versioned · calendar and holiday logic,
now on real data · expiry and last-trading-day logic, cross-checked against the exchange ·
raw contract symbols preserved · contract roll deterministic and audited · TFEX-aligned
1m/5m/15m candle construction and midday-break isolation · full-day/session VWAP ·
morning/afternoon opening ranges · causal gap engine · deterministic replay and current
anti-repaint suites · causal pivots/swing labels/BOS/CHoCH · deterministic Order Blocks ·
confirmed liquidity levels/reclaimed sweeps and importance features · causal three-candle
FVGs · closed-15m structure and fail-closed volatility regimes · backend tests, lint and
type checks pass · no real broker order route enabled.

**Design locked but not runtime-complete:** proposal/risk/approved-plan boundary · stop-based
THB sizing · no-widening stops · protected partial fills · deterministic kill and recovery
states · EOD/no-overnight contract.

**Not met:** calibrated strategy/regime thresholds · researched liquidity total ranking ·
strategy signals · runtime position sizing · margin gate · paper execution
transport/semantics · runtime EOD and expiry-day flattening · anti-repaint coverage for
future strategy/execution milestones · frontend · Playwright end-to-end tests.
