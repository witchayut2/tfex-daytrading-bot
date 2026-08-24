# TFEX Platform Architecture

Status: **Milestone TFEX-1 complete.** Configuration, provenance, calendar, contracts and
sessions are implemented. Everything downstream of them is not.

Read with `CLAUDE.md` and `CLAUDE_TFEX.md`. Where this document and the specification
disagree, the specification wins; where this document records a *decision* the specification
left open, it is marked as such.

---

## 1. Toolchain

| Concern | Choice | Why |
| --- | --- | --- |
| Python | CPython **3.12.13** via **uv** | The only real interpreter on the machine; the `python.exe` on `PATH` is the Microsoft Store alias stub. |
| Runner | `uv run …` from `backend/` | Deviation from the literal `python -m pytest` in section 35. Same commands, uv-managed environment. |
| Models | pydantic v2, `frozen=True`, `extra="forbid"` | Immutability by default, and a misspelt config or data key is an error instead of a silently ignored field. |
| Lint / format | ruff (line length 100) | — |
| Types | mypy `strict = true` with the pydantic plugin | — |
| Money / prices | `decimal.Decimal` everywhere | YAML `0.1` must not become `0.1000000000000000055`; tick arithmetic decides position size. |
| Time | `datetime` + `zoneinfo`, always tz-aware | Naive timestamps are rejected at every boundary, never localised by assumption. |

Commands (from `backend/`):

```bash
uv sync
uv run pytest tests/tfex
uv run pytest -m anti_repaint     # the anti-repaint subset
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run python scripts/validate_calendar_data.py
uv run python scripts/render_official_sources.py
```

## 2. Layering

Dependencies point one way. Nothing below imports anything above it.

```text
config.py ......... exchange facts + research defaults, validated on load
errors.py ......... typed failure hierarchy
provenance.py ..... where every piece of exchange metadata came from
      │
calendar/ ......... imported holiday data -> trading days -> expiry
      │
contracts/ ........ symbols -> resolved contracts -> registry -> roll policy
      │
sessions/ ......... phases for a date -> session state -> entry/exit gates
      │
(TFEX-2+) feeds, candles, structure, strategies, risk, brokers, dashboard
```

`sessions/boundaries.py` is deliberately **pure**: it takes facts (is this a trading day? is
it the last trading day? was an early close announced?) and returns intervals. The calendar
supplies those facts; `sessions/engine.py` joins the two. That keeps the session layer
testable without holiday data and stops a dependency cycle forming.

## 3. The two invariants everything else is built on

### 3.1 Fail closed on missing data

A question the platform cannot answer from imported official data raises, rather than
returning a plausible default:

- an unimported calendar year → `CalendarDataUnavailableError`
- metadata past its freshness window → `StaleMetadataError`
- a contract whose expiry cannot be resolved → status `UNKNOWN`, which is never tradable
- no eligible contract → `NoEligibleContractError`, not "the least bad one"

`SessionEngine.new_position_decision` turns each of these into a *denial with reasons*
rather than an exception, so the audit log records why no trade happened.

### 3.2 Time-dependent answers are computed, never cached

`ContractRegistry` stores what does not change (which contract it is, when it was listed,
what the feed last reported) and resolves status, days-to-expiry and eligibility **for a
given instant** on every read. A cached `ACTIVE` would let a replay see a contract as
tradable on a day it was not — repaint risk R10 in the audit.

The same rule will govern every level and snapshot from TFEX-2 onwards: each carries
`event_time` (when the market printed it) and `confirmed_at` (when the system was allowed to
know it), and a strategy may only read values whose `confirmed_at` has passed.

## 4. Module map (implemented)

| Module | Responsibility |
| --- | --- |
| `config.py` | Loads and validates `config/tfex.yaml`. Cross-field checks: tick arithmetic (`0.1 × 200 = 20`), session phases chain without gaps, the midday/pre-open overlap is present, the last-trading-day cutoff precedes cessation, timezones agree. Refuses to enable live orders. |
| `provenance.py` | `SourceRecord` + `OfficialSourceRegistry` (the section 2 register, persisted to `data/tfex/official_sources.json`, rendered to `docs/tfex_official_sources.md`); `Provenance`, the freshness/verification stamp embedded in imported data. |
| `calendar/models.py` | Holidays, shortened sessions, approval-gated administrative overrides, published contract dates, resolved `ContractExpiry`. |
| `calendar/holiday_loader.py` | Reads `data/tfex/holidays/<year>.json`. Caches per process. Raises for unimported years. |
| `calendar/trading_day.py` | Classification and walks. Weekends are a *necessary* condition, never sufficient. |
| `calendar/expiry.py` | Last-trading-day resolution with recorded provenance. |
| `calendar/service.py` | `TradingCalendar` facade; freshness policy applied in one place. |
| `contracts/symbol_parser.py` | Pure syntax + two-digit-year resolution against an explicit reference date. |
| `contracts/metadata.py` | `TfexContractSymbol`, `ContractStatus`, and the resolver that joins a parsed symbol to the calendar. |
| `contracts/registry.py` | The single source of truth for contract eligibility and selection. |
| `contracts/roll.py` | Liquidity-based roll policy, confirmation state machine, position-splice guard. |
| `sessions/boundaries.py` | `SessionState`, phase layout for a date, precedence rules. |
| `sessions/midday_break.py` | The predicates the TFEX-2 candle aggregation will enforce. |
| `sessions/engine.py` | Session state and the entry/exit/flatten gates. |

Everything else under `app/tfex/` exists as a documented placeholder naming its milestone and
the invariant it must hold. They contain no logic — a half-implemented opening range is
exactly how repaint risk R4 gets in.

## 5. Decisions the specification left open

| # | Question | Decision | Rationale |
| --- | --- | --- | --- |
| D1 | The midday break (12:30–13:45) and afternoon pre-open (13:15–13:45) overlap. What state is 13:20? | `phases_at()` returns **both**; `state_at()` returns one primary state by documented precedence (closing window > afternoon pre-open > morning pre-open > morning open > afternoon open > midday break > post-close > closed). | Section 9 says model the overlap explicitly. Dashboards still need one label. |
| D2 | Is `days_to_expiry` calendar days or trading days? | Both are computed and stored. **Gates use trading days.** | Holiday-aware and never more optimistic than the calendar-day count. |
| D3 | How is a two-digit year resolved? | Against an explicit `reference_date`, with a ±50-year pivot. Never against "now". | A 2019 symbol must parse as 2019 when replayed in 2031, or every historical backtest silently changes meaning. |
| D4 | `expiry_date` vs `last_trading_date` for a cash-settled contract. | Separate fields even though currently equal. | A future exchange change becomes a data change rather than a schema migration. |
| D5 | Boundary instants. | Half-open `[start, end)`. 12:30:00 is the break; 16:55:00 is post-close. | One instant never belongs to two sequential phases. |
| D6 | Derived vs published last trading day. | Published wins; the source is recorded on the model; `expiry.require_published_last_trading_day` can make the derived fallback an error. | The rule is our reading of the specification; the published table is the exchange's answer. |
| D7 | Roll confirmation vs an ineligible contract. | Voluntary rolls need `confirmation_sessions`; a **forced** roll (current contract past the cutoff) is immediate. | Waiting for confirmation would leave the platform on a series it may not trade. |
| D8 | A roll criterion whose input is missing. | Recorded as *skipped*, never as passing. Session volume is mandatory — a comparison with every criterion skipped does not vacuously dominate. | Volume is the evidence a roll is founded on. |
| D9 | Trading a contract without expiry context. | `SessionEngine.new_position_decision` denies when no `ContractExpiry` is supplied. | Section 6: the contract must come from the registry before any trading decision. |
| D10 | An early close on a day with an early *morning* close. | The midday break starts at the actual morning close and runs to 13:45. | Otherwise a hard-coded 12:30 would let a bar cover 11:45–12:00 on such a day. |

## 6. What the platform refuses to ship

- **Holiday dates.** None. `backend/data/tfex/holidays/` contains a schema and an import
  procedure, and the calendar raises for any year not imported. A wrong holiday moves the
  last business day of a month, which moves the last trading day, which moves the expiry
  gate.
- **Margin numbers.** Section 22 forbids embedding a current margin in code. TFEX-4 adds a
  versioned provider that takes the stricter of official, broker-reported and configured
  safety margin.
- **A live order route.** `TradingConfig` raises `LiveTradingDisabledError` if anything sets
  `live_orders_enabled: true`, including via YAML. Section 32's gates are not met and this
  build has no broker connectivity.
- **Verified source claims.** The official-source register seeds every entry as
  `NOT_VERIFIED` with no retrieval date, because nothing has been checked yet.

## 7. Testing

277 tests under `backend/tests/tfex/`. Tests that encode a non-repainting invariant carry
the `anti_repaint` marker so the suite required by section 31 can be run on its own.

Calendar fixtures use **invented** holiday dates, chosen to exercise the awkward cases: a
holiday on the last calendar day of a month (June), a holiday sitting between the last two
business days (September), and a closure spanning a year boundary (Dec 2025 → Jan 2026).
They are labelled as fixtures in `conftest.py` so they can never be mistaken for TFEX data.

## 8. Next: Milestone TFEX-2

Raw contract CSV import, 1m/5m/15m aggregation aligned to TFEX sessions, midday-break
handling, morning/afternoon snapshots, full-day and session VWAP, opening ranges, and the gap
engine — plus `docs/tfex_candle_alignment.md`, which section 10 requires.

Blocked on operator action: official holiday data must be imported before any of it can be
validated against real dates. See `docs/development_status.md`.
