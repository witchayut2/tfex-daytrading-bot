# CODEX HANDOFF — TFEX Project

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
