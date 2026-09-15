# TFEX Platform Architecture

Status: **Milestone TFEX-2 complete.** Configuration, provenance, calendar, contracts,
sessions, validation, and deterministic raw-contract replay/market state are implemented.
Five complete S50U26 1-minute days are real-data validated and replayed with checksum and
parent-lineage evidence; the data gate remains `READY_FOR_TFEX2`. Dormant risk, order, and
position-management contracts and the research-validation protocol remain locked for future
milestones. TFEX-3 deterministic neutral analysis is `TFEX3_COMPLETE`: pivots, structure,
BOS/CHoCH, Order Blocks, liquidity/sweeps/importance features, FVGs, and layered regime
infrastructure are implemented. Numeric calibration and total ranking remain future
research. Strategies, optimization, execution, and live trading have not started.
TFEX-4 research governance is `R4_RESEARCH_PLAN_LOCKED`; this status does not start TFEX-4.
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
marketdata/ ....... bars -> validation -> replay -> causal 5m/15m/VWAP market state
      │
analysis/ +
liquidity/ ........ confirmed bars -> pivots -> structure -> neutral levels/events
      │
risk/ contracts ... dormant proposal -> risk -> protected-position specifications
      │
(TFEX-4+) strategies, broker runtime, dashboard
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
| `sessions/midday_break.py` | Canonical no-crossing predicates enforced by aggregation. |
| `sessions/engine.py` | Session state and the entry/exit/flatten gates. |
| `sessions/opening_range.py` | Causal 5/15/30-minute morning and afternoon opening ranges. |
| `sessions/snapshots.py` | Running and finalized morning/afternoon/day profiles and reference levels. |
| `sessions/gaps.py` | Timestamped overnight, midday, and informational raw-contract roll gaps. |
| `costs/models.py` | `FeeProvenanceStatus`, `FeeComponent`, `RoundTripCostEstimate`. A published cap physically refuses to be charged as a production cost. |
| `costs/exchange_fees.py` | The THB 7 cap (never chargeable) and the actual fee (`UNKNOWN` until verified). |
| `costs/commissions.py` | Broker commission — negotiable, so `UNKNOWN` with no default. |
| `marketdata/models.py` | `Bar`, `DatasetManifest`, and the granular report types. |
| `marketdata/csv_loader.py` | Reads a vendor CSV. A naive timestamp requires a declared source timezone. |
| `marketdata/validation.py` | Eleven independent data-quality checks (section 28). |
| `marketdata/manifest.py` | Dataset provenance and checksum enforcement. |
| `marketdata/acceptance.py` | Completion guard requiring minimum-history real data plus a matching replay. |
| `marketdata/aggregation.py` | Session-anchored 5m/15m OHLCV aggregation with explicit forming/confirmed state. |
| `marketdata/vwap.py` | Causal HLC3 full-day, morning, and afternoon VWAP modes. |
| `marketdata/replay.py` | One-event cursor, deterministic restart/seek, derived-state orchestration, and replay digest. |
| `feeds/base.py` | Immutable closed-bar market event and replay status types. |
| `feeds/csv_feed.py` | Manifest/checksum-aware one-minute CSV replay input. |
| `analysis/models.py` | Closed causal 1m/5m/15m input with raw symbol and explicit event/confirmation times. |
| `analysis/pivots.py` | Explicit-strength strict-extrema pivots with delayed confirmation. |
| `analysis/structure.py` | HH/HL/LH/LL/equality labels, neutral bias, and close-confirmed BOS/CHoCH. |
| `analysis/fvg.py` | Contiguous three-closed-candle FVG formation and immutable lifecycle revisions. |
| `analysis/order_blocks.py` | One-or-zero BOS-anchored last-opposite-candle zones and causal lifecycle revisions. |
| `analysis/regime.py` | Closed-15m structure mapping plus provenance-bearing, fail-closed volatility classification. |
| `analysis/engine.py` | Incremental TFEX-3 orchestration, restart, real-data identity, and stable digest. |
| `liquidity/levels.py` | Confirmed raw-symbol pivot/equality/session/opening-range liquidity levels. |
| `liquidity/session_levels.py` | Converts only finalized TFEX-2 profiles/ranges into liquidity sources. |
| `liquidity/sweep.py` | Neutral touch/exceed/reclaim/invalidation semantics. |
| `liquidity/engine.py` | Immutable level revisions plus append-only interaction and sweep histories. |
| `liquidity/importance.py` | Causal feature vectors, exact/configured confluence, and non-magic partial ordering. |

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
strategy milestone. `docs/tfex_strategy_research_validation_protocol.md` defines the
evidence contract, while `docs/tfex4_research_plan.md` defines the canonical finite R4
procedure:

| Module | Locked future research contract (no replay or strategy runtime) |
| --- | --- |
| `research/models.py` | Chronological partitions, one-use holdout, walk-forward folds, causal information, costs, metrics, trial registry, execution evidence, and acceptance states. |
| `research/protocol.py` | Pure append-only and fail-closed validation operations. |

TFEX-3 is complete as neutral market analysis under `docs/tfex3_definition_lock.md` and its
acceptance matrix. Numeric volatility calibration and total liquidity-ranking policy remain
future declared research, not hidden defaults or missing neutral infrastructure. Neither
TFEX-2 nor TFEX-3 introduces a strategy, broker, risk-runtime, or order transport.

The future TFEX-4 implementation boundary is locked in `docs/tfex4_definition_lock.md`.
That document defines causal Strategy A/B mechanics, scoring, proposal, gate, margin, and
completion semantics without adding runtime strategy code or advancing
`TFEX4_NOT_STARTED`. Its research and authorization prerequisites remain controlling.

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
| D21 | When does a swing pivot exist? | The caller supplies a versioned left/right strength. A wick must be a strict extremum against every configured neighbour, and the pivot confirms only when the final right bar closes. The acceptance run explicitly uses 2x2; the public engine has no hidden default. | Delayed confirmation makes mathematical lookahead observable without leaking it backward. |
| D22 | What breaks structure? | A closed bar strictly beyond the latest already-confirmed same-timeframe pivot. Wicks do not create BOS/CHoCH. A break against established bullish/bearish structure is CHoCH; other confirmed breaks are BOS. | The rule is objective, reproducible, and exposes both event and knowledge time. |
| D23 | What is an equal high/low? | Exact price equality between consecutive confirmed same-type pivots. No undocumented tolerance exists. | Any tolerance would be a research parameter and cannot be guessed. |
| D24 | How are the final TFEX-3 ambiguities resolved? | `docs/tfex3_definition_lock.md`: BOS-anchored last-opposite-candle Order Blocks; closed-15m structure x externally calibrated volatility; liquidity feature vectors and a partial order; exact confluence by default. | Deterministic neutral infrastructure is lockable without inventing numeric thresholds, source weights, or trading alpha. |

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

571 tests under `backend/tests/tfex/` (570 passed, 1 optional installed-SDK signature check
skipped). Two markers:

- `anti_repaint` — encodes a non-repainting invariant, so the suite section 31 requires can
  be run on its own.
- `real_market_data` — runs validation and TFEX-2 replay acceptance against both the
  non-synthetic four-day parent and five-day extended dataset, plus causal TFEX-3 structure
  checks. Thirty-eight tests pass; only the child can satisfy the minimum-history completion
  guard. The anti-repaint subset contains 56 passing tests.

Calendar fixtures use **invented** holiday dates, chosen to exercise the awkward cases: a
holiday on the last calendar day of a month (June), a holiday sitting between the last two
business days (September), and a closure spanning a year boundary (Dec 2025 → Jan 2026).
They are labelled as fixtures in `conftest.py` so they can never be mistaken for TFEX data,
and they are kept separate from official exchange metadata under `backend/data/tfex/official/`
and ignored licensed market data under `backend/data/tfex/historical/normalized/`, which the
`real_market_data` tests use.

## 8. Locked future risk contract

`docs/tfex_risk_order_position_contract.md` is canonical for every future strategy and
execution path. Its deterministic unit scaffolding is intentionally not wired into runtime
trading and does not advance the TFEX-2/TFEX-4/TFEX-5 milestones.

## 9. Milestone TFEX-2 — complete

Raw contract CSV import, one-event replay, 1m/5m/15m aggregation aligned to independent TFEX
sessions, midday-break handling, morning/afternoon snapshots, full-day and session VWAP,
opening ranges, and the causal gap engine are implemented and tested. Alignment policy lives
in `docs/tfex_candle_alignment.md`; requirement evidence is in `docs/tfex2_acceptance.md`.

**`TFEX2_COMPLETE`.** The five-day S50U26 run emitted 1,775 causal source frames, 355
confirmed 5m bars, and 120 confirmed 15m bars with deterministic replay digest
`413e6430720ed94ad4e2ae7c283d60fd6eb32f555cb75b2b181d7ddb9aa121e6`.
The data gate remains `READY_FOR_TFEX2`; the four-day parent and licensed data remain
untouched and ignored. TFEX-3 later began under separate authorization; its status is
recorded independently below.

## 10. Milestone TFEX-3 — complete

The analysis consumes only immutable TFEX-2 frames and confirmed 5m/15m bars. It provides
delayed strict-extrema pivots, swing classifications, close-confirmed BOS/CHoCH,
BOS-anchored deterministic Order Blocks, confirmed liquidity and reclaimed sweeps, causal
FVGs, closed-15m structure regimes, fail-closed volatility states, and unweighted liquidity
importance features. Batch/incremental processing, prefixes, restart, future mutation, and
the five-day real S50U26 run are deterministic.

**`TFEX3_COMPLETE`.** The real run emitted 70 Order Blocks and deterministic analysis digest
`cb6bb31d9a4a812f57b8b97c7eab20d8c7f25f46473144fd71444a3e5f74ee8b`.
All volatility frames correctly remain `UNCALIBRATED` because no research threshold was
supplied. No strategy or trade direction is emitted; TFEX-4 remains not started.
