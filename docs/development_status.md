# Development Status

Last updated: **2026-08-23**
Current status label: **TFEX metadata and calendar foundation — not yet a trading system**

> Not ready for real money. `CLAUDE_TFEX.md` section 32 lists sixteen gates before real
> orders may even be considered; none are met, and no broker order route exists in this build.

---

## Milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| **TFEX-0** | Audit | ✅ Complete — `docs/tfex_repository_audit.md` |
| **TFEX-1** | Configuration, official-source registry, symbol parser, contract registry, trading calendar, holiday import, last-trading-day model, session state engine, tests | ✅ Complete (code); ⚠️ **blocked on holiday data import** for use against real dates |
| TFEX-2 | TFEX-aligned replay: CSV import, 1m/5m/15m aggregation, midday break, session snapshots, VWAP, opening ranges, gap engine | ⬜ Not started |
| TFEX-3 | Analysis: pivots, structure, BOS, CHoCH, liquidity map, sweeps, FVG, order blocks, regime | ⬜ Not started |
| TFEX-4 | Strategies A and B, scoring, sizing, margin/expiry/session gates, kill switch | ⬜ Not started |
| TFEX-5 | Paper execution: broker, order state machine, costs, next-bar fills, P&L, EOD flatten | ⬜ Not started |
| TFEX-6 | Visual dashboard | ⬜ Not started |
| TFEX-7 | Read-only real-time adapter | ⬜ Not started |

## Checks (last run 2026-08-23)

| Command | Result |
| --- | --- |
| `uv run pytest tests/tfex` | **277 passed** |
| `uv run ruff check .` | **All checks passed** |
| `uv run ruff format --check .` | **72 files already formatted** |
| `uv run mypy .` | **Success — no issues in 71 source files** |
| Frontend | Not applicable — no frontend exists until TFEX-6 |
| Docker | Not applicable — no compose file yet |

## What TFEX-1 delivered

**Configuration** — `backend/config/tfex.yaml`, validated on load. Exchange facts and
research defaults are labelled separately. Cross-field checks catch the errors that would
otherwise be invisible: tick arithmetic (`0.1 × 200 = 20`), session phases chaining without
gaps, the intentional midday/pre-open overlap being present, the last-trading-day cutoff
preceding cessation.

**Provenance** — the section 2 register, seeded with all ten official URLs, every one marked
`NOT_VERIFIED` because nothing has been checked yet. `docs/tfex_official_sources.md` is
generated from it, so the document cannot drift from the register the code consults.

**Calendar** — versioned per-year holiday import with provenance, trading-day arithmetic,
approval-gated administrative overrides, and last-trading-day resolution that records
whether the date came from the exchange, from the derived rule, or from an override.

**Contracts** — strict symbol parsing (all twelve month codes; two-digit years resolved
against an explicit reference date), status resolution against the calendar, a registry that
is the only component allowed to select a tradable contract, and a liquidity-based roll
policy with confirmation, forced rolls and a position-splice guard.

**Sessions** — the eight-state model, the overlapping-phase treatment section 9 asks for, the
midday-break predicates the TFEX-2 aggregation will enforce, and fail-closed entry/exit/
flatten gates that produce a reasoned decision rather than a bare boolean.

## Blocked — operator action required

1. **Import official TFEX holiday data.** *(blocks TFEX-2 validation against real dates)*
   The platform ships no holiday dates on purpose: a wrong holiday moves the last business
   day of a contract month, which moves the last trading day, which moves the expiry gate.
   Procedure and schema: `backend/data/tfex/holidays/README.md`.
   Verify with `uv run python scripts/validate_calendar_data.py`.
2. **Import exchange-published last-trading-day tables** from the SET50 product calendar.
   The derived rule is a documented fallback, not an authority.
3. **`git init`.** The repository is still not under version control. Roll decisions,
   calendar versions and audit history need durable, reviewable history.
4. **Provide market data.** No CSV or tick data exists; TFEX-2 cannot be validated without
   it. Section 31 asks for multiple regimes, expiry weeks, roll periods, high-volatility
   days, low-volume days, gap days, and morning/afternoon reversals.

## Known gaps and risks

- **`symbol.minimum_contract_year: 2006` is a research default**, used to reject implausibly
  old symbols. Verify the actual SET50 futures listing history before relying on it.
- **`contract.max_exchange_fee_thb_per_contract_per_side: 7`** comes from the contract
  summary and must be re-verified against the current fee schedule before any cost modelling
  in TFEX-5.
- **Every roll threshold is a research default**, not an exchange rule, and none has been
  calibrated against data. Section 7 says so explicitly.
- **The freshness window (180 days) is arbitrary** until refresh jobs exist. It is a
  configuration value, not a finding.
- **No source has been verified.** `metadata.require_verified_sources` is `false` so replay
  work can proceed; order-capable modes must set it `true`.
- Repaint risks R1–R12 from the audit remain open where they belong to later milestones.
  R10 (roll rewriting history) is structurally addressed: the registry never caches
  time-dependent state and never splices positions.

## Definition of done (section 34) — progress

Met: contract metadata represented and versioned · calendar and holiday logic · expiry and
last-trading-day logic · raw contract symbols preserved · contract roll deterministic and
audited · backend tests, lint and type checks pass · no real broker order route enabled.

Not met: candle alignment and the midday-break bar rule · VWAP · opening ranges · gap engine ·
non-repainting liquidity levels · strategy signals · position sizing · margin gate · paper
execution semantics · EOD and expiry-day flattening · the full anti-repaint suite · frontend ·
Playwright end-to-end tests.
