# Development Status

Last updated: **2026-08-24**
Current status label: **TFEX metadata, calendar and data-readiness foundation — not yet a trading system**

> Not ready for real money. `CLAUDE_TFEX.md` section 32 lists sixteen gates before real
> orders may even be considered; none are met, and no broker order route exists in this build.

---

## Milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| **TFEX-0** | Audit | ✅ Complete — `docs/tfex_repository_audit.md` |
| **TFEX-1** | Configuration, official-source registry, symbol parser, contract registry, trading calendar, holiday import, last-trading-day model, session state engine, tests | ✅ Complete, and now running on **real imported exchange data** |
| **Data-readiness gate** | Baseline preservation, real calendar import, fee semantics, market-data validator, acceptance gate, source research | ✅ Complete — decision **`BLOCKED_REAL_MARKET_DATA`** (`docs/tfex_data_readiness_gate.md`) |
| TFEX-2 | TFEX-aligned replay: CSV import, 1m/5m/15m aggregation, midday break, session snapshots, VWAP, opening ranges, gap engine | ⛔ **Not started — blocked on real 1-minute data.** Status `TFEX2_NOT_STARTED` |
| TFEX-3 | Analysis: pivots, structure, BOS, CHoCH, liquidity map, sweeps, FVG, order blocks, regime | ⬜ Not started |
| TFEX-4 | Strategies A and B, scoring, sizing, margin/expiry/session gates, kill switch | ⬜ Not started |
| TFEX-5 | Paper execution: broker, order state machine, costs, next-bar fills, P&L, EOD flatten | ⬜ Not started |
| TFEX-6 | Visual dashboard | ⬜ Not started |
| TFEX-7 | Read-only real-time adapter | ⬜ Not started |

## Checks (last run 2026-08-24)

| Command | Result |
| --- | --- |
| `uv run pytest tests/tfex` | **365 passed, 9 skipped** |
| `uv run pytest -m anti_repaint` | **13 passed, 2 skipped** |
| `uv run pytest -m real_market_data` | **9 skipped** — the blocker, visible in the suite |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 93 files already formatted |
| `uv run mypy .` | Success — 91 source files |
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
| 1-minute market data | **none** | `REAL_1M_DATA_BLOCKED` |

Raw captures with SHA-256 provenance live under `backend/data/tfex/official/`.

## Blocked — operator action required

1. **Acquire a real 1-minute SET50 futures dataset.** *(blocks TFEX-2)*
   Path and exact commands: `docs/tfex_data_readiness_gate.md` → "Exactly what the operator
   must provide". Summary: Settrade Open API credentials, run the capability probe, download
   two contracts; or purchase SET/SETSMART intraday data.
2. **Configure Git identity** so the verified baseline becomes a real commit. It is currently
   preserved only as tree `4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc`
   (`docs/baseline_manifest.md`).
3. **Import the 2027 holiday calendar** when TFEX publishes it. The endpoint serves only the
   current display year; 2025 and 2027 return HTTP 401 today. Until 2027 lands, S50H27 and
   S50M27 have no cross-checked expiry and anything reaching into 2027 fails closed.
4. **Verify the actual exchange fee and broker commission** against a statement or agreement.

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
- Repaint risks R1–R9, R11, R12 from the audit remain open where they belong to later
  milestones. R10 (roll rewriting history) is structurally addressed.

## Definition of done (section 34) — progress

**Met:** official contract metadata represented and versioned · calendar and holiday logic,
now on real data · expiry and last-trading-day logic, cross-checked against the exchange ·
raw contract symbols preserved · contract roll deterministic and audited · backend tests,
lint and type checks pass · no real broker order route enabled.

**Not met:** candle alignment and the midday-break bar rule (the *predicate* exists and is
enforced by the validator; the aggregation does not) · VWAP · opening ranges · gap engine ·
non-repainting liquidity levels · strategy signals · position sizing · margin gate · paper
execution semantics · EOD and expiry-day flattening · the full anti-repaint suite · frontend ·
Playwright end-to-end tests.
