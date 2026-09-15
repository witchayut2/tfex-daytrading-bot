# AGENTS.md — TFEX SET50 Futures Bot / Codex

## 1. Mission
Build a deterministic, non-repainting, paper-trading-first TFEX SET50 Index Futures platform.

Codex is now the active coding agent for this repository.

Legacy files `CLAUDE.md` and `CLAUDE_TFEX.md` remain project specifications and provenance. Read them before major work. Do not delete or rewrite them simply because the project moved from Claude Code to Codex.

## 2. First action in every new Codex session
Before editing anything:

1. Read this `AGENTS.md`.
2. Read `CLAUDE.md`.
3. Read `CLAUDE_TFEX.md`.
4. Read:
   - `docs/development_status.md`
   - `docs/tfex_architecture.md`
   - `docs/tfex_data_readiness_gate.md`
   - `docs/tfex_historical_data_sources.md`
   - `docs/tfex_candle_alignment.md`
   - `docs/tfex2_acceptance.md`
   - `docs/tfex3_acceptance.md` if present
   - `docs/tfex4_definition_lock.md` if present
   - `docs/tfex4_research_readiness.md` if present
   - `docs/tfex4_research_plan.md` if present
   - `docs/baseline_manifest.md`
   - `docs/CODEX_HANDOFF.md` if present
5. Run:
   - `git status --short`
   - `git log --oneline -5`
6. Identify the actual current milestone and blocker.
7. Do not modify files until the current state is understood.

The repository itself is the final source of truth if it differs from this handoff.

## 3. Current verified state (2026-09-15)

- The verified baseline commit exists: `0a5daae`.
- The current branch is `main`; Git identity is configured locally (never record its values here).
- Settrade production authentication, derivatives market-data entitlement, historical
  candlesticks, the raw `S50U26` contract, and the `1m` interval are confirmed by permitted
  read-only operator calls.
- An immutable five-day S50U26 1-minute dataset (2026-09-08 through 2026-09-14,
  1,775 rows) is `REAL_DATA_VALIDATED`, passes all validator checks, and has verified
  parent/raw/normalized checksum lineage.
- The minimum of five complete trading days is met. The current gate is
  `READY_FOR_TFEX2`.
- TFEX-2 deterministic raw-contract replay and causal market state are complete and tested
  against the five-day real S50U26 dataset.
- TFEX-3 neutral analysis is `TFEX3_COMPLETE`: causal pivots, swing structure, BOS/CHoCH,
  deterministic Order Blocks, liquidity levels/sweeps/importance features, FVGs, and
  structure/volatility regime infrastructure are implemented and tested. Volatility
  thresholds and total liquidity-ranking policy remain intentionally `UNCALIBRATED` for
  later declared research; no strategy has started.
- Future risk/order/position and strategy-research protocols are locked as dormant,
  fail-closed contracts. They do not start TFEX-2, TFEX-4, or TFEX-5.
- The deterministic TFEX-4 Strategy A/B, scoring, proposal, gate, margin, and milestone
  definitions are locked in `docs/tfex4_definition_lock.md`. TFEX-4 remains
  `TFEX4_NOT_STARTED`. Data planning remains locked by `docs/tfex4_research_readiness.md`,
  and the finite pre-code research plan is now `R4_RESEARCH_PLAN_LOCKED` in
  `docs/tfex4_research_plan.md`. Explicit authorization to implement remains outstanding.
- Licensed historical data and operator-specific capability evidence remain outside Git.

Latest verified QA:
- `uv run pytest tests/tfex` -> 570 passed, 1 skipped
- `uv run pytest -m anti_repaint` -> 56 passed, 515 deselected
- `uv run pytest -m real_market_data` -> 38 passed, 533 deselected
- `uv run ruff check .` -> PASS
- `uv run ruff format --check .` -> PASS, 125 files
- `uv run mypy .` -> PASS, 122 source files

TFEX-2 must NEVER be marked complete from synthetic fixtures alone.

## 4. Official-data state already established
Preserve existing provenance work for:

- TFEX Holiday Calendar 2026/2569
- special TFEX holidays including:
  - 2026-01-02
  - 2026-10-16
- published/derived SET50 Futures last-trading-day checks for 2026
- exchange fee semantics

Fee rule:
THB 7 per contract per side is a VERIFIED EXCHANGE FEE CAP, not automatically the broker's actual charged fee.

Do not weaken provenance or fail-closed behavior.

## 5. InnovestX / Settrade state
User has:

- InnovestX TFEX service activated
- Settrade Open API app for TFEX
- Broker ID: `023`
- App code: `ALGO`
- App ID and Secret held by the user

Current engineering boundary:
the data-readiness gate, TFEX-2, and TFEX-3 neutral analysis are complete. Numeric regime
calibration, liquidity-ranking research, strategies, execution, and live-order work have
not started. TFEX-4 research readiness is `R4_RESEARCH_PLAN_LOCKED`; R2/R3 data work and R5
implementation authorization remain outstanding. No strategy code or research data
acquisition is authorized by that status.

## 6. Secret handling — critical
Never print, log, echo, persist, commit, paste into docs, or expose:

- SETTRADE_APP_ID
- SETTRADE_APP_SECRET
- access/refresh tokens
- account numbers
- PIN
- passwords

When checking environment variables, report only `PRESENT` or `MISSING`.

Real credentials must stay outside tracked repository files.

If a secret has ever appeared in a screenshot/chat, advise regenerating it before production use.

## 7. Trading safety
Until explicitly authorized in a future milestone:

- no live order submission
- no change/cancel live orders
- no live trading endpoint
- no automatic production trading enablement
- no strategy bypassing risk gates
- no credential use for order placement
- Settrade work is read-only market-data work only

`live_orders_enabled` remains false/fail-closed.

## 8. Non-repaint contract
Confirmed outputs are immutable.

Rules include:

- closed-bar-only confirmation
- separate `event_time` from `confirmed_at`
- no future-index access
- no future-leaking negative shift
- no centered rolling confirmation
- no full-dataset normalization that leaks future state
- no future extrema for past decisions
- no early higher-timeframe candle close
- Opening Range confirms only after its window closes
- no candle spans TFEX midday break
- replay and incremental confirmed results must match
- prefix stability required
- future mutation must not change past confirmed state
- forming candles may display but cannot confirm signals

Behavioral anti-repaint tests are authoritative.

## 9. Contract identity
Preserve raw contracts such as:

- S50U26
- S50Z26

Do not silently merge raw execution/acceptance data into a continuous front-month series.

A continuous series may later exist only as a derived research dataset with explicit roll metadata.

## 10. TFEX sessions
Use verified repository session logic.

Project specification includes:

- Morning continuous: 09:45–12:30 Asia/Bangkok
- Afternoon continuous: 13:45–16:55 Asia/Bangkok
- Last Trading Day cutoff: 16:30 Asia/Bangkok

Never aggregate across the midday break.

## 11. Required task order
Proceed in this order:

1. Audit current repository state.
2. Confirm/understand Git state.
3. Confirm Settrade env vars PRESENT without printing values.
4. Run safe READ-ONLY Settrade probe.
5. Prove raw S50 contract historical 1-minute support.
6. Acquire a small real dataset if supported.
7. Run existing market-data validator.
8. Run `real_market_data` acceptance tests.
9. Re-evaluate data-readiness gate.
10. Start TFEX-2 only if the gate is `READY_FOR_TFEX2`.

## 12. Settrade probe questions
Actual API behavior or exact API/SDK evidence must answer:

1. Authentication succeeds?
2. Derivatives market-data entitlement exists?
3. Raw S50 contract recognized?
4. Historical derivatives candlestick works?
5. `1m` interval works?
6. Earliest retrievable timestamp?
7. Latest retrievable timestamp?
8. Maximum bars per request?
9. Pagination mechanism?
10. Rate limits?
11. Broker-specific entitlement restrictions?

Do not infer YES from generic SDK documentation.

## 13. Backend verification
From `backend/`:

```bash
uv run pytest tests/tfex
uv run pytest -m anti_repaint
uv run pytest -m real_market_data
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

A skipped real-market suite is visible unfinished work, not real-data validation.

## 14. Change discipline
Before changes:
- inspect Git state
- read relevant tests
- identify acceptance criteria

During changes:
- make smallest coherent change
- preserve public interfaces unless migration is necessary
- add tests for critical behavior
- never weaken assertions merely to get green tests

After changes:
- run targeted tests
- run required TFEX suite
- run anti-repaint suite
- run lint/format/type checks
- show `git diff --stat`
- report exact command outcomes
- do not commit automatically unless the user requests it

## 15. Status vocabulary
Use accurately:

- IMPLEMENTED
- TESTED
- FIXTURE_VALIDATED
- REAL_DATA_VALIDATED
- VERIFIED_OFFICIAL
- UNVERIFIED
- BLOCKED
- CONFLICT

Never call fixture validation real-market validation.

## 16. Never do these
- invent TFEX holidays or LTDs
- guess API capabilities
- silently fill missing bars
- forward-fill through lunch
- mix raw contract symbols
- treat fee cap as actual fee
- expose credentials
- enable live trading
- mark TFEX-2 complete using synthetic data
