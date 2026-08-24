# TFEX Repository Audit — Milestone TFEX-0

- **Audit date:** 2026-08-23
- **Repository root:** `c:\apps7 tfex\TFEX_ClaudeCode_Starter`
- **Auditor:** Claude Code
- **Specifications read in full:** `CLAUDE.md`, `CLAUDE_TFEX.md`
- **Scope of this audit:** state of the repository *before* any TFEX implementation work.

---

## 1. Discovery commands run

`CLAUDE_TFEX.md` §35 prescribes a start-up command set. Results, with deviations noted:

| Prescribed command | Result |
| --- | --- |
| `pwd` | `/c/apps7 tfex/TFEX_ClaudeCode_Starter` |
| `git status` | **`fatal: not a git repository`** — no VCS initialised |
| `find . -maxdepth 3 -type f` | 3 files only (see §2) |
| `find backend -maxdepth 4 -type f` | **directory does not exist** |
| `find frontend -maxdepth 4 -type f` | **directory does not exist** |
| `cd backend && python -m pytest -q` | **not runnable** — no `backend/`, and no Python on `PATH` |
| `ruff check .` / `ruff format --check .` / `mypy .` | **not runnable** — no project, no tooling config |
| `cd frontend && npm ci` | **not runnable** — no `frontend/` |
| `docker compose config` | **not runnable** — no `docker-compose.yml` |

> Per §36 ("run existing checks") the intent was to establish a green baseline before editing.
> **There is no baseline to establish: zero tests exist, so zero tests pass and zero fail.**
> This is recorded explicitly so that later claims of "tests pass" are not mistaken for regression safety.

## 2. Complete file inventory (initial state)

```text
CLAUDE.md        197 bytes
CLAUDE_TFEX.md   34,079 bytes
README.txt       340 bytes
```

Nothing else. No source, no tests, no configuration, no data, no CI, no lockfiles.

## 3. Current architecture

**There is none.** The repository is a specification-only starter kit. `README.txt` confirms the intent:
the two Markdown files are meant to be dropped into a project root and used as the standing instruction
set for an implementation that has not begun.

Consequences for the audit:

- There is no existing architecture to preserve, so §36 "preserve existing working behavior" is vacuous.
- There is no legacy code to migrate, so the TFEX module tree in §4 can be created exactly as specified
  rather than "adapted".
- Every item in the §34 definition-of-done list is currently **not met**.

## 4. Toolchain audit

| Tool | Status | Note |
| --- | --- | --- |
| `python` / `python3` | **Absent** | `C:\Users\...\WindowsApps\python.exe` is the Microsoft Store alias stub, not an interpreter. Invoking it exits 49. |
| `py` launcher | Absent | — |
| `uv` | **Present** — 0.11.14 | Manages an already-downloaded CPython **3.12.13**. |
| `node` | Present — v24.15.0 | Frontend milestone TFEX-6 is unblocked when reached. |
| `npm` | Present — 11.12.1 | — |
| `git` | Present, but repo is **not initialised** | Roll decisions, calendar versions and audit history need durable history. |
| `docker` | Not verified | Not required before TFEX-6. |

**Decision:** the backend is standardised on **uv + CPython 3.12.13**, because that is the only real
interpreter present. All backend commands in §35 are therefore run as `uv run …` from `backend/`.
This is a deviation from the literal `python -m pytest` in §35 and is documented in
`docs/tfex_architecture.md`.

## 5. Missing TFEX modules

Measured against §4, **the entire tree is missing**. Nothing exists under `backend/app/tfex/`:

| Package | Required by §4 | Present | First milestone that needs it |
| --- | --- | --- | --- |
| `tfex/config.py` | yes | no | TFEX-1 |
| `tfex/calendar/` (5 modules) | yes | no | TFEX-1 |
| `tfex/contracts/` (5 modules) | yes | no | TFEX-1 (`continuous_series` → TFEX-2) |
| `tfex/sessions/` (5 modules) | yes | no | TFEX-1 (`opening_range`, `snapshots` → TFEX-2) |
| `tfex/margins/` (4 modules) | yes | no | TFEX-4 |
| `tfex/costs/` (3 modules) | yes | no | TFEX-5 |
| `tfex/liquidity/` (3 modules) | yes | no | TFEX-3 |
| `tfex/basis/` (3 modules) | yes | no | TFEX-3 |
| `tfex/feeds/` (4 modules) | yes | no | TFEX-2 (`realtime_readonly`, `settrade_future` → TFEX-7) |
| `tfex/brokers/` (3 modules) | yes | no | TFEX-5 (`settrade_future` → interface only) |
| `tfex/risk/` (4 modules) | yes | no | TFEX-4 |

All 16 test modules listed in §4 are likewise missing.

Also missing and required by the specification text rather than the tree:

- `docs/tfex_official_sources.md` (§2)
- `docs/tfex_candle_alignment.md` (§10 — due at TFEX-2)
- `docs/development_status.md` (§35)

## 6. Repaint risks identified

No code exists, so no repaint bug exists *yet*. What follows is a **pre-registered risk list** — the
places where a naive implementation of this specification will repaint. Each is mapped to the milestone
that must close it and to the test that proves it closed.

| # | Repaint risk | Why it happens | Closed by | Proof |
| --- | --- | --- | --- | --- |
| R1 | Session high/low treated as final while the session is still open | Provisional running extremes cached as "confirmed" | TFEX-2 (§11) | `test_session_snapshots` — morning high must be unavailable before 12:30 |
| R2 | A bar spanning the 12:30–13:45 break | Naive fixed-width resampling over a continuous time axis | TFEX-2 (§10) | `test_midday_break`, `test_gap_engine` |
| R3 | 15m bar confirmed before its bucket closes | Emitting a partial bucket on the last tick | TFEX-2 (§10) | `test_next_bar_execution` |
| R4 | Opening range read before its window ends | OR computed from the running window | TFEX-2 (§13) | `test_opening_range` |
| R5 | Previous-day levels leaking into the same day | Level `event_time` used instead of `confirmed_at` | TFEX-3 (§15) | `test_liquidity_levels` |
| R6 | Afternoon data influencing morning decisions on replay | Whole-day dataframe loaded then indexed backwards | TFEX-2/3 (§27) | anti-repaint suite |
| R7 | Continuous-series adjustment altering execution prices | Back-adjusted prices reused for fills | TFEX-2 (§7) | `test_roll_logic` + backtest guard |
| R8 | Fill at the same close that produced the signal | Same-bar execution | TFEX-5 (§24) | `test_next_bar_execution` |
| R9 | Current margin applied retroactively to historical trades | Single mutable margin constant | TFEX-4 (§22) | `test_margin_gate` |
| R10 | Contract roll rewriting raw history | Splicing series in place | TFEX-1/2 (§7) | `test_roll_logic` |
| R11 | Best-VWAP-in-hindsight selection | VWAP mode chosen per trade instead of per configuration | TFEX-2 (§12) | `test_session_vwap`, `test_full_day_vwap` |
| R12 | Pre-open indicative prices treated as executable trades | Feed does not distinguish trade types | TFEX-2 (§10) | feed-semantics tests |

**Structural mitigation adopted at TFEX-1:** every level/snapshot model carries both `event_time`
(when the market printed it) and `confirmed_at` (when the system was allowed to know it). Anything
without a `confirmed_at` in the past is not readable by a strategy. This is enforced from the very
first module so it does not have to be retrofitted.

## 7. Contract and session assumptions found in the specification

These are assumptions the specification itself carries. They are recorded here because several are
**dynamic facts that must be verified from official sources**, not constants.

### 7.1 Safe to encode as configuration (static contract terms, §3)

- Point value THB 200/point, tick 0.1 point, tick value THB 20/contract.
- Cash settlement; daily price limit ±30% of latest settlement.
- Regular sessions 09:15/09:45–12:30 and 13:15/13:45–16:55 Asia/Bangkok.
- Trading ceases 16:30 on the last trading day.

Internal consistency check available: `tick_size_points × point_value_thb == tick_value_thb`
(0.1 × 200 = 20). This is asserted at configuration load so a typo cannot silently mis-size positions.

### 7.2 **Must not** be hard-coded — dynamic, unverified at audit time

| Assumption | Risk if hard-coded | Handling adopted |
| --- | --- | --- |
| **Thai/TFEX holidays** | Wrong trading-day set → wrong last trading day → wrong expiry gate → real loss | Versioned per-year files with provenance; calendar **raises** when a year is not loaded. No holiday dates are invented. |
| Last trading day | "Business day before the last business day of the month" needs the holiday set to mean anything | Derived rule *and* an exchange-published override; the source of the value is recorded on the model |
| Margin rates | Sizing/rejection errors | TFEX-4, versioned provider, stricter-of rule |
| Broker commissions | Understated cost, overstated edge | TFEX-5 |
| Shortened sessions | Fabricated bars after an early close | Calendar override records, approval-gated |
| Listed contract months | Guessing an active contract | Registry is the only source of contract eligibility |

### 7.3 Ambiguities in the specification, and how TFEX-1 resolves them

1. **Midday break overlaps the afternoon pre-open** (§9: break 12:30–13:45, pre-open 13:15–13:45).
   §9 explicitly says to model states rather than assume one phase. TFEX-1 therefore reports *all*
   active phases at an instant, plus one deterministic primary state by documented precedence.
2. **`days_to_expiry` unit** (§5/§7) — calendar days or trading days is unstated. Both are computed;
   the roll cutoff uses **trading days** because it is holiday-aware and strictly more conservative.
3. **Two-digit year in a symbol is inherently ambiguous** (§5 requires historical-symbol support).
   Resolved against an explicit reference date with a documented ±50-year pivot, never against "now".
4. **`expiry_date` vs `last_trading_date`** — for a cash-settled contract these are recorded as
   separate fields even when equal, so a future exchange change does not require a data migration.
5. **Boundary instants** — intervals are half-open `[start, end)`. 12:30:00 is already midday break;
   16:55:00 is already post-close.

## 8. Compliance status against §34 definition of done

All 20 criteria are **not met** at audit time. This is expected — the audit precedes implementation.

## 9. Blocking prerequisites (operator action required)

These cannot be resolved by writing code and are called out now rather than at the end:

1. **Official TFEX holiday data must be imported** before any date-sensitive logic can be exercised on
   real dates. The loader, schema and import path are delivered in TFEX-1; the *data* is not, because
   inventing holiday dates would violate §2 ("never silently continue with stale exchange metadata").
2. **Exchange-published last-trading-day tables** should be imported for the same reason; the derived
   rule is a fallback, not an authority.
3. **`git init`** — roll decisions, calendar versions and audit history need durable, reviewable
   history. Recommended before TFEX-2.
4. **Market data** — no CSV/tick data is present. TFEX-2 cannot be validated without it.

## 10. Recommendation

Proceed to **Milestone TFEX-1** (configuration, official-source registry, symbol parser, contract
registry, trading calendar, holiday import, last-trading-day model, session state engine, tests).

Do **not** proceed past TFEX-1 until:

- the anti-repaint structural invariant (`event_time` + `confirmed_at`) is present in every model, and
- the calendar refuses to answer questions about years whose official data has not been loaded.

Live trading remains out of scope and no order route to a broker exists or is planned in this phase.
