# TFEX Platform Architecture

Status: **Milestone TFEX-1 complete, plus the data-readiness gate.** Configuration,
provenance, calendar, contracts, sessions, cost provenance and market-data validation are
implemented. Four complete S50U26 1-minute days are real-data validated; TFEX-2 remains
blocked on the unchanged five-day minimum (`docs/tfex_data_readiness_gate.md`). Dormant risk,
order, and position-management contracts and the research-validation protocol are locked for
future milestones, but no strategy, replay, optimizer, or execution runtime has started.
Licensed historical data and operator-specific capability evidence stay local and ignored;
their universal SDK/API conclusions are captured in tests and canonical readiness docs.

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
uv run pytest -m anti_repaint          # the anti-repaint subset
uv run pytest -m real_market_data      # skips without a real dataset

uv run ruff check .
uv run ruff format --check .
uv run mypy .

# metadata import and verification
uv run python scripts/import_tfex_holidays.py --year 2026
uv run python scripts/import_tfex_contracts.py
uv run python scripts/validate_calendar_data.py --year 2026
uv run python scripts/update_source_verification.py --corroborate-spec

# market data
uv run python scripts/data_sources/settrade_history.py --probe --symbol S50Z26
uv run python scripts/validate_tfex_market_data.py \
    --file <path> --symbol S50Z26 --interval 1m --timezone Asia/Bangkok
```

## 2. Layering

Dependencies point one way. Nothing below imports anything above it.

```text
errors.py ......... typed failure hierarchy
provenance.py ..... where every piece of exchange metadata came from
costs/models.py ... fee provenance: a published cap is not an actual charge
      │
config.py ......... exchange facts + research defaults, validated on load
      │
calendar/ ......... imported holiday data -> trading days -> expiry
      │
contracts/ ........ symbols -> resolved contracts -> registry -> roll policy
      │
sessions/ ......... phases for a date -> session state -> entry/exit gates
      │
marketdata/ ....... bars -> dataset provenance -> validation -> acceptance gate
      │
risk/ contracts ... dormant proposal -> risk -> protected-position specifications
      │
(TFEX-2+) candles, structure, strategies, broker runtime, dashboard
```

`config.py` imports `costs/models.py` for its two provenance enums, so `costs/__init__.py`
re-exports **only** that leaf module; the builder functions live in `costs/exchange_fees.py`
and `costs/commissions.py` and are imported directly. Re-exporting them from the package
would close an import cycle.

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
| `costs/models.py` | `FeeProvenanceStatus`, `FeeComponent`, `RoundTripCostEstimate`. A published cap physically refuses to be charged as a production cost. |
| `costs/exchange_fees.py` | The THB 7 cap (never chargeable) and the actual fee (`UNKNOWN` until verified). |
| `costs/commissions.py` | Broker commission — negotiable, so `UNKNOWN` with no default. |
| `marketdata/models.py` | `Bar`, `DatasetManifest`, and the granular report types. |
| `marketdata/csv_loader.py` | Reads a vendor CSV. A naive timestamp requires a declared source timezone. |
| `marketdata/validation.py` | Eleven independent data-quality checks (section 28). |
| `marketdata/manifest.py` | Dataset provenance and checksum enforcement. |
| `marketdata/acceptance.py` | The guard that stops fixtures promoting a milestone. |

The risk package now also contains **dormant architecture/test scaffolding**, not a started
TFEX-4/TFEX-5 runtime:

| Module | Locked future contract (no runtime activation) |
| --- | --- |
| `risk/models.py` | Quantity-free proposals, strategy rules, cost/risk calculations, approved plans, kill decisions, and audit events. |
| `risk/engine.py` | Pure fail-closed sizing and kill-switch evaluation. No broker dependency. |
| `risk/position.py` | Immutable lifecycle, fill/protection reducers, stop rules, EOD/emergency/recovery state. |
| `risk/audit.py` | Reconstructable aggregate audit schema. No storage adapter. |
| `risk/boundary.py` | Strategies emit proposals; future execution admits approved plans only. |

The research package is likewise a dormant contract layer, not a backtester or a started
strategy milestone. `docs/tfex_strategy_research_validation_protocol.md` is canonical:

| Module | Locked future research contract (no replay or strategy runtime) |
| --- | --- |
| `research/models.py` | Chronological partitions, one-use holdout, walk-forward folds, causal information, costs, metrics, trial registry, execution evidence, and acceptance states. |
| `research/protocol.py` | Pure append-only and fail-closed validation operations. |

All other future-milestone modules remain documented placeholders. No candle, strategy,
broker, or order-transport implementation was introduced.

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
| D11 | Does a replay of mid-September 2026 need the 2025 and 2027 calendars? | `required_years_for` pads a neighbouring year only when the range comes within 31 days of the boundary. | TFEX publishes next year's calendar only late in the current year, so unconditional padding is a false blocker. This is precision, not relaxation: `HolidayStore.year()` still raises the moment anything actually reaches into an unimported year. |
| D12 | Is THB 7 per contract per side a cost? | No — it is a **cap**, modelled as `VERIFIED_EXCHANGE_CAP` with `production_charge=False`. The actual fee is `UNKNOWN`. | Deducting a cap as an actual charge overstates expenses, rejects viable strategies, and will not reconcile against a broker statement. |
| D13 | What counts as a verified source? | A ladder: `NOT_VERIFIED` → `RETRIEVED` → `PARSED` → `CROSS_CHECKED` → `VERIFIED_OFFICIAL`, plus `STALE` / `CONFLICT` / `UNAVAILABLE`. Only the top two count as verified. | "We fetched it" must never be mistaken for "we confirmed it". Verification is per source *and* per fact. |
| D14 | A synthetic dataset that validates cleanly. | Can never satisfy TFEX-2 acceptance; `mark_tfex2_complete` raises. | Fixtures prove the code matches its author's expectations, not that it survives real quiet minutes, feed gaps and off-tick prints. |
| D15 | Who chooses contract quantity? | Only `RiskEngine`, by flooring remaining THB risk capacity divided by per-contract stop-and-cost risk. Strategies are quantity-free. | Lot-first sizing can silently exceed the stop-defined risk budget. |
| D16 | Can a stop be widened after entry? | No. Unchanged or deterministic risk-reducing moves are allowed; every widening request is rejected. No exception exists. | Maximum loss may never grow through a management shortcut. |
| D17 | Is every strategy forced to 1:2? | No. Fixed targets use cost-adjusted RRR; deterministic non-target exits use versioned, strategy-specific expectancy evidence. | Different deterministic exits have different payoff distributions; inventing a target would misstate them. |
| D18 | What happens to a partial fill? | Every filled contract immediately carries matching planned/pending/active protection; partial exits reduce protective quantity atomically. | Local state may never represent unprotected filled exposure. |
| D19 | What does a kill switch do to open positions? | It always blocks new entries, preserves existing protection, and separately requests flattening when executable. | Disabling entries must not cancel the only protection on existing risk. |
| D20 | What risk values ship by default? | All numerical thresholds are `null` and `UNCALIBRATED`; a complete set may be labelled `RESEARCH_ONLY`, never production-ready. | No arbitrary number should acquire authority merely by being a code default. |

## 6. What the platform refuses to ship

- **Invented holiday dates.** Real 2026 data is now imported from the exchange with SHA-256
  provenance; 2025 and 2027 are **not** available from the source and remain unimported, so
  the calendar raises for them. A wrong holiday moves the last business day of a month, which
  moves the last trading day, which moves the expiry gate.
- **Fabricated market data.** No synthetic candle is ever labelled as real, and
  `mark_tfex2_complete` refuses to promote a milestone on fixtures alone.
- **An exchange fee cap presented as an actual cost.** See D12.
- **Margin numbers.** Section 22 forbids embedding a current margin in code. TFEX-4 adds a
  versioned provider that takes the stricter of official, broker-reported and configured
  safety margin. (The series endpoint does publish an initial margin; it was deliberately not
  imported, because margin is dynamic and belongs to the versioned provider.)
- **A live order route.** `TradingConfig` raises `LiveTradingDisabledError` if anything sets
  `live_orders_enabled: true`, including via YAML. Section 32's gates are not met and this
  build has no broker connectivity.
- **An uncalibrated risk approval.** Missing/null thresholds activate a kill trigger and
  reject every new entry. The unit scaffold can approve only an explicitly complete,
  `RESEARCH_ONLY` configuration.
- **Overstated verification.** The register seeds every source as `NOT_VERIFIED`, and
  statuses are written from stored captures by `scripts/update_source_verification.py`, not
  by hand. Six of ten sources are still `NOT_VERIFIED` today, including both margin pages.

## 7. Testing

490 tests under `backend/tests/tfex/` (489 passed, 1 optional installed-SDK signature check
skipped). Two markers:

- `anti_repaint` — encodes a non-repainting invariant, so the suite section 31 requires can
  be run on its own.
- `real_market_data` — runs against the validated non-synthetic four-day dataset. Ten tests
  pass, while minimum-history sufficiency remains separately false.

Calendar fixtures use **invented** holiday dates, chosen to exercise the awkward cases: a
holiday on the last calendar day of a month (June), a holiday sitting between the last two
business days (September), and a closure spanning a year boundary (Dec 2025 → Jan 2026).
They are labelled as fixtures in `conftest.py` so they can never be mistaken for TFEX data,
and they are kept separate from the real imported data under `backend/data/tfex/official/`,
which the `real_market_data` tests use instead.

## 8. Locked future risk contract

`docs/tfex_risk_order_position_contract.md` is canonical for every future strategy and
execution path. Its deterministic unit scaffolding is intentionally not wired into runtime
trading and does not advance the TFEX-2/TFEX-4/TFEX-5 milestones.

## 9. Next: Milestone TFEX-2

Raw contract CSV import, 1m/5m/15m aggregation aligned to TFEX sessions, midday-break
handling, morning/afternoon snapshots, full-day and session VWAP, opening ranges, and the gap
engine — plus `docs/tfex_candle_alignment.md`, which section 10 requires.

**Blocked.** `docs/tfex_data_readiness_gate.md` records
`BLOCKED_MINIMUM_REAL_HISTORY`: four complete S50U26 1-minute days are validated, but the
unchanged gate requires at least five. The validated parent dataset remains intact; TFEX-2
does not begin until a fifth complete day passes the existing validator, real-market tests,
and provenance/checksum checks.
