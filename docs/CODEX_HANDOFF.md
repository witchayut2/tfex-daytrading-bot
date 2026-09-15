# CODEX HANDOFF — TFEX Project

## Current-state note — 2026-09-15

The sections below are the original migration handoff and are retained as provenance. The
repository has advanced: S50U26 one-minute data for five complete days (1,775 rows) is
`REAL_DATA_VALIDATED`, with validator, manifest, checksum, and parent-lineage evidence
passing. The current gate remains `READY_FOR_TFEX2`; TFEX-2 is now `TFEX2_COMPLETE` after
deterministic real-data replay and market-state acceptance. TFEX-3 is now
`TFEX3_COMPLETE`; `docs/tfex3_definition_lock.md` and `docs/tfex3_acceptance.md` record its
deterministic neutral-analysis definitions and evidence. Numeric calibration and total
liquidity ranking remain future research. `docs/tfex4_definition_lock.md` now records the
deterministic initial Strategy A/B, scoring, proposal, gate, margin, and completion
definitions, but TFEX-4 remains `TFEX4_NOT_STARTED` and no strategy implementation or
research run has begun. `docs/tfex4_research_readiness.md` now records the canonical
pre-code/post-code boundary and the Tier B multi-contract acquisition plan.
`docs/tfex4_research_plan.md` locks the finite candidate, trial-budget, registry,
multiplicity, execution, cost, partition, calibration, robustness, threshold, and promotion
procedures. Research readiness is `R4_RESEARCH_PLAN_LOCKED`; explicit user authorization
remains outstanding before deterministic `RESEARCH_ONLY` code may begin.

The future risk/order/position contract is now locked in
`docs/tfex_risk_order_position_contract.md` with dormant deterministic unit scaffolding.
The future research protocol is likewise locked in
`docs/tfex_strategy_research_validation_protocol.md`. Neither starts TFEX-2/4/5, configures
numerical thresholds, calibrates a strategy, or adds a broker order route. The safe
five-day extension workflow has completed successfully. Licensed captures and the
sanitized operator/application-specific capability result remain local and ignored by Git.
Current QA and next operator action live in `docs/development_status.md`; those current
repository facts supersede the historical figures below.

## Purpose
This file transfers the existing project from Claude Code to OpenAI Codex in VS Code without restarting the project.

## Known Git checkpoints
- `0a5daae` — baseline: verified TFEX-0 and TFEX-1 foundation
- `00e54b8` — feat: add TFEX data readiness validation and official market metadata

Codex must verify actual HEAD/current branch before work.

## Last known QA
- TFEX: 365 passed, 9 skipped
- anti-repaint: 13 passed, 2 skipped
- Ruff: pass
- format: pass
- mypy strict: pass, 91 source files

## Data readiness
Official 2026 TFEX holiday and 2026 SET50 contract-calendar work was completed under provenance rules.

Last gate:
`BLOCKED_REAL_MARKET_DATA`

## Broker/API
InnovestX TFEX is active.

Settrade app:
- Broker ID: 023
- TFEX app code: ALGO
- App ID/Secret: user-held secret, never store here

## Immediate next objective
Perform a safe read-only Settrade probe and determine whether InnovestX/Settrade permits:

- raw SET50 Futures contract symbol
- historical candlesticks for derivatives
- 1-minute interval
- sufficient lookback

If supported:
- acquire a small raw-contract real dataset
- validate it
- run real-market acceptance tests
- re-evaluate the gate

## Allowed probe decisions
- SETTRADE_REAL_DATA_READY
- SETTRADE_AUTH_REQUIRED
- SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING
- SETTRADE_1M_HISTORY_NOT_SUPPORTED
- SETTRADE_RAW_CONTRACT_NOT_SUPPORTED
- SETTRADE_PROBE_FAILED

Do not hide blockers with synthetic fixtures.
