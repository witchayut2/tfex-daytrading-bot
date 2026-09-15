# TFEX-4 Research Readiness

Status: **`R1_DATA_PLAN_LOCKED` / `TFEX4_NOT_STARTED`**

This document is the canonical research-readiness plan for TFEX-4. It governs when
deterministic Strategy A/B implementation, parameter research, walk-forward evaluation,
and final-holdout access may begin. It does not implement a strategy, select a parameter,
claim profitability, acquire data, or authorize execution.

The deterministic mechanics remain controlled by `docs/tfex4_definition_lock.md`. The
evidence lifecycle and anti-overfitting rules remain controlled by
`docs/tfex_strategy_research_validation_protocol.md`. This plan separates their pre-code
governance requirements from evidence that can exist only after deterministic code exists.

```text
TFEX-2 = TFEX2_COMPLETE
TFEX-3 = TFEX3_COMPLETE
TFEX-4 = TFEX4_NOT_STARTED
strategy evidence = RESEARCH_ONLY
live_orders_enabled = false
```

## 1. Pre-code and post-code governance boundary

### Pre-code governance

Deterministic Strategy A/B code may begin only after:

1. TFEX-2 and TFEX-3 correctness remain green;
2. the TFEX-4 definition lock is complete;
3. the historical-data acquisition plan is locked;
4. the multi-contract segmentation plan is locked;
5. Strategy A/B research search dimensions are declared;
6. experiment governance is declared;
7. the execution-assumption structure is declared;
8. the cost-scenario structure is declared;
9. every unknown numeric value remains explicit and fail-closed;
10. no final holdout has been inspected; and
11. the user explicitly authorizes TFEX-4 implementation.

No backtest result, profitable result, calibrated numeric configuration, or downloaded
Tier B dataset is required merely to write deterministic code. Code begins with evidence
state `RESEARCH_ONLY`.

### Post-code research

Before parameter search, threshold selection, walk-forward evaluation, final-holdout
access, or strategy promotion:

- adequate licensed history must be acquired and validated;
- actual chronological partitions must be frozen;
- finite candidate sets and a maximum trial budget must be frozen;
- numeric cost scenarios and required calibration inputs must exist;
- complete execution-research semantics must be frozen;
- trial registration and multiple-testing control must be active; and
- applicable thresholds must be calibrated only from permitted development/calibration
  evidence and frozen before later validation stages.

Implementation status and evidence status remain independent:

```text
deterministic TFEX-4 code + RESEARCH_ONLY
    -> BACKTEST_EVIDENCE
    -> WALK_FORWARD_EVIDENCE
    -> HOLDOUT_EVIDENCE
    -> later live-arriving forward/paper evidence
```

`TFEX4_COMPLETE` will mean implementation-correct, not profitable, production-calibrated,
paper-ready, live-ready, or authorized to trade.

## 2. Target historical-data tier

The current acquisition target is **Tier B - Recommended Research**:

- approximately 12-18 calendar months;
- approximately 240-360 trading days;
- at least five distinct raw S50 futures symbols;
- at least four observed expiry/roll transitions;
- both outgoing and incoming contracts around each transition; and
- preserved individual raw-contract identity throughout.

This is a planning target, not a statistical-sufficiency guarantee. Adequacy must also be
judged from qualified setup/trade counts, regime and volatility balance, contract diversity,
expiry/roll coverage, uncertainty, and robustness.

The future **Tier C - Robust Validation** target is approximately 3-5 years, 750-1,250
trading days, at least thirteen distinct raw symbols, and at least twelve observed
transitions. Tier C is not a precondition for deterministic TFEX-4 implementation.

The existing five-day S50U26 dataset remains a correctness and integration dataset only.
It does not satisfy Tier B research coverage and cannot select a production configuration.

## 3. Required phenomenon coverage

The Tier B inventory must identify, without choosing dates from strategy performance:

- normal non-expiry weeks;
- expiry weeks and observed transition periods;
- low- and high-volatility sessions;
- directional trend and range/contraction sessions;
- large-gap and small/no-gap sessions;
- high- and low-volume sessions;
- morning and afternoon behavior; and
- applicable holidays and shortened sessions.

Calendar duration alone never proves adequate research coverage.

## 4. Multi-contract policy

Each expiry contract remains individually identifiable.

- Raw files remain contract-specific.
- Normalized files remain contract-specific.
- Prices are never back-adjusted.
- Multiple contracts are never relabelled as one fake raw symbol.
- No synthetic or derived continuous contract may satisfy real acceptance.
- Causal market state resets at every contract boundary.
- VWAP, pivots, structure, zones, and strategy state reset at the boundary.
- An open research position must not silently cross a symbol boundary.
- Roll gaps remain informational only and cannot create strategy gaps, sweeps, entries,
  stops, or fills.
- Research campaigns may aggregate results across contract-local segments, but must not
  splice prices into an artificial market stream.

## 5. Future multi-contract campaign schema

The current `DataPartition` and `PartitionPlan` correctly preserve one raw symbol and must
not be bypassed. Before multi-contract parameter research, a reviewed schema must represent
ordered contract-local segments conceptually as:

```text
ResearchCampaign
  campaign_id
  ordered_segments[]

ResearchSegment
  segment_id
  raw_symbol
  dataset_id
  start
  end
  contract_month
  expiry
  last_trading_day
  source_hash
  normalized_hash
  calendar_version
  registry_version
```

Each chronological partition references ordered `ResearchSegment` records. Fold and
aggregate results retain both campaign and segment identity. No runtime schema change is
made by this document.

## 6. Acquisition-source hierarchy

### Preferred

1. Settrade production historical candlesticks where verified depth is available.
2. Official SET, SETSMART, or approved TFEX historical/tick sources.

### Acceptable with provenance

3. Broker raw-contract exports.
4. Manual exports from an official or broker system.
5. Licensed commercial vendors after raw-symbol coverage and rights are verified.

### Research only

- UAT data;
- daily or index-only context; and
- explicitly labelled derived continuous context that never supplies execution prices or
  acceptance evidence.

### Unacceptable

- TradingView scraping;
- pirated or unauthorized datasets;
- mixed-symbol unlabeled files; and
- synthetic replacement for real acceptance.

The observed Settrade boundary between an empty 2026-09-07 request and available
2026-09-08 data is not an official retention policy.

## 7. Per-contract manifest and admission contract

Every raw contract dataset must record:

- dataset ID, provider/source, and source type;
- license and storage/use/redistribution policy;
- raw symbol and contract month/year;
- expiry date, last trading day, and LTD source/version;
- source timezone, normalized timezone, interval, and timestamp semantics;
- first/last timestamp, trading dates, complete-session count, and row count;
- acquisition timestamp and source/export identity;
- every raw-capture SHA-256 and the normalized SHA-256;
- normalization-rule, calendar, contract-registry, and validator versions;
- validation result and report identity;
- missing bars, duplicate/conflicting bars, and off-tick findings;
- synthetic and continuous-contract flags; and
- lineage and parent references.

Critical checksum, license, provenance, identity, timestamp, parsing, conflicting-duplicate,
OHLCV, session, calendar, expiry, or data-gap failures reject research admission. Bars are
never silently filled, altered, or deduplicated.

## 8. Chronological partition governance

The canonical roles remain:

1. `A_DEVELOPMENT_CALIBRATION`
2. `B_VALIDATION`
3. `C_UNTOUCHED_FINAL_HOLDOUT`
4. `D_FORWARD_PAPER`

Partitions are timezone-aware, half-open, chronological, and non-overlapping. They cite
ordered contract-local segments, and their boundaries are selected from availability,
calendar, and contract facts rather than strategy performance.

A and B should contain repeated expiry/roll phenomena where the inventory permits. C should
preserve at least one untouched transition where possible. Exact dates remain unselected
until the historical inventory exists.

C is permanently burned if it influences tuning, strategy narrative, implementation,
parameter decisions, or diagnostic interpretation. A burned C can never be presented as a
final holdout again. D is future, live-arriving data and cannot be replaced by historical
recomputation.

## 9. Walk-forward governance

Both `ANCHORED` and `ROLLING` remain valid candidates. Neither is selected now.

Before comparison, declare the calibration-window rule, validation-window rule, step size,
minimum session/contract coverage, candidate set, cost model, execution model, contract
reset rule, parameter-freeze deadline, recalibration timing, and comparison rule.

Numeric window lengths remain `SEARCH_RANGE_NOT_LOCKED`. Each fold selects parameters using
only its calibration window, freezes them before validation, and resets state at raw-symbol
boundaries.

## 10. Strategy A research dimensions

The structural dimensions are:

- `trigger_mode`: `RETEST_REJECTION`, `CONFIRMED_MICRO_BREAK`;
- `zone_kind`: `FVG`, `ORDER_BLOCK`;
- `zone_timeframe`: `1m`, `5m`; and
- `exit_family`: `OPPOSING_LIQUIDITY`, `STRUCTURAL_TARGET`, `VWAP_TARGET`, `FIXED_R`,
  `PARTIAL_RUNNER`, `STRUCTURE_TRAIL`, `ATR_TRAIL`, `TIME_STOP`.

Optional predeclared filter families may include VWAP proximity, relative volume, ATR
penetration, time/session filters, and failed-morning/afternoon-continuation context.

Numeric domains and candidate values remain `SEARCH_RANGE_NOT_LOCKED`. The current research
enum has no explicit `OPPOSING_LIQUIDITY` member; it must not be silently aliased to
`STRUCTURE_TARGET`.

## 11. Strategy B research dimensions

The structural dimensions are:

- `vwap_mode`: `FULL_DAY`, `MORNING`, `AFTERNOON`;
- `zone_kind`: `FVG`, `ORDER_BLOCK`;
- `zone_timeframe`: `1m`, `5m`; and
- `extension_mode`: `TICKS`, `ATR_NORMALIZED`.

The following remain mechanical, not search choices: required 15-minute directional
structure, earliest same-direction 5-minute BOS, freshness before first touch, earliest
post-touch same-direction 1-minute BOS or CHoCH, and the nearest confirmed active unswept
opposing-liquidity target.

VWAP slope lookback, maximum mitigation, maximum extension, minimum cost-adjusted RRR, and
optional-filter thresholds remain unconfigured with `SEARCH_RANGE_NOT_LOCKED` candidate
sets.

## 12. Parameter-explosion governance

Strategy A already has approximately 64 structural cells before optional filters or numeric
values. Strategy B already has approximately 24. These counts are warnings, not trial
authorization.

Before parameter search, every search requires:

- finite candidate sets and a maximum trial budget;
- an immutable `search_id`, hypothesis, and declaration timestamp;
- code/rule version, partition hashes, and dataset hashes;
- `cost_model_id` and `execution_model_id`;
- registration before results exist;
- retained failed, rejected, and zero-trade trials;
- parameter-neighborhood tests;
- declared multiple-testing disclosure/control; and
- no post-hoc expansion under the same search ID.

Uncontrolled combinatorial brute force is prohibited.

## 13. Cost-scenario contract

The required future scenario IDs are:

- `OPTIMISTIC_RESEARCH`
- `BASE_RESEARCH`
- `CONSERVATIVE_RESEARCH`

Each scenario explicitly records exchange fee, broker commission, VAT/tax treatment,
spread treatment, slippage per side, embedded-cost flags, and provenance/status.

Current facts:

- THB 200 per point per contract is verified;
- 0.1 point equals THB 20 per contract and is verified;
- THB 7 per contract per side is verified only as a maximum/cap;
- actual exchange charge and broker commission are unknown;
- VAT/tax treatment is unknown;
- spread is unknown without a bid/ask source; and
- slippage remains a research assumption until evidenced.

No numeric scenario value is selected here. At least two complete numeric scenarios are
required before meaningful parameter research.

## 14. Execution-research semantics

Locked now:

- the trigger close is a reference, not a fill;
- fill eligibility begins at a later valid executable event;
- same-bar OHLC fills are prohibited; and
- same-bar fills require explicit post-confirmation trade-tick sequence evidence.

Before trusted backtests, a later definition lock must specify market fills, limit
touch/cross/queue behavior, stop triggering/fills, stop-versus-target same-bar precedence,
gap-through behavior, partial fills, spread/slippage application, missing-event behavior,
and session/expiry cancellation.

These are research backtest semantics. TFEX-5 continues to own runtime execution.

## 15. Risk and margin research boundary

Initial quantity-free Strategy A/B signal research does not require live margin, account
free equity, or production risk sizing.

- Signal research may remain quantity-free.
- Portfolio/risk research requires explicitly labelled hypothetical or calibrated risk
  assumptions.
- RiskEngine approval fails closed while required configuration is incomplete.
- Paper/live readiness requires verified as-of margin, free equity, fees, limits, and
  operational health.

Legacy `2.0` is never substituted. Historical account free equity is never fabricated.
Unavailable evidence remains explicit and cannot prove an approvable historical account
state.

## 16. Metrics and robustness contract

Every future evidence package reports:

- total, winning, losing, and breakeven trades;
- win rate and average win/loss;
- expectancy in THB and R;
- profit factor;
- gross P&L, explicit costs, and net P&L;
- average and median R;
- maximum drawdown and duration;
- MAE and MFE;
- consecutive losses and chronological daily distribution;
- trades per day, exposure, rejected setups, and setup frequency;
- session, regime, volatility, and relative-volume breakdowns;
- per-contract and expiry-week results;
- cost/slippage and parameter-neighborhood sensitivity;
- best-trade removal/tail dependence;
- long/short and morning/afternoon balance; and
- multiple-testing disclosure.

No single metric may promote a strategy. No numeric pass threshold is selected here.

## 17. Strategy evaluation order

Research proceeds in this order:

1. Strategy A independently;
2. Strategy B independently;
3. combined A+B only after independent evidence;
4. all-qualified versus best-setup-only comparison; and
5. portfolio arbitration only after a separate causal policy is locked.

Strategy C/ORB remains disabled. No A-versus-B priority weight is defined.

## 18. Research-readiness states

These are governance states, not runtime enums. Data and research-plan work may advance on
separate branches; R5 does not require downloaded Tier B data, while R6 does.

| State | Entry criteria |
| --- | --- |
| `R0_FOUNDATION_ONLY` | TFEX-2/3 and TFEX-4 definitions are complete; only correctness-smoke history exists. |
| `R1_DATA_PLAN_LOCKED` | Tier, source hierarchy, multi-contract handling, campaign/manifest shape, admission rules, and partition governance are locked. |
| `R2_DATA_ACQUIRED` | Planned immutable per-contract raw captures and checksums exist under verified rights. |
| `R3_DATA_VALIDATED` | Contract-local normalization, calendars/LTDs, manifests, validator/replay checks, and coverage inventory pass. |
| `R4_RESEARCH_PLAN_LOCKED` | Finite candidate-generation rules, experiment budget, multiplicity method, execution semantics, metric/robustness procedures, and threshold-calibration method are frozen. Exact performance winners are not required. |
| `R5_READY_FOR_TFEX4_IMPLEMENTATION` | R1 and R4 governance are satisfied, the holdout is untouched, correctness remains green, and the user explicitly authorizes deterministic `RESEARCH_ONLY` implementation. |
| `R6_READY_FOR_PARAMETER_SEARCH` | R2/R3 data and R5 implementation are complete; actual partitions, finite candidate sets, numeric cost scenarios, and calibration inputs are frozen. |
| `R7_READY_FOR_WALK_FORWARD` | Permitted calibration/validation work is complete and the predeclared walk-forward plan is ready without holdout access. |
| `R8_READY_FOR_HOLDOUT` | Required walk-forward and robustness evidence passes predeclared reviewed thresholds, and C remains untouched. |

## 19. Current decision and next gates

This plan establishes `R1_DATA_PLAN_LOCKED`. It does not establish R2, R3, R4, or R5.

To reach R4, the repository still needs finite candidate-generation rules, an experiment
budget, a multiplicity-control method, complete research fill semantics, and frozen
metric/robustness and threshold-calibration procedures. The cost-scenario structure is
locked here; its numeric values remain a later R6 prerequisite.

To reach R5, R4 must be accepted, the holdout must remain untouched, the governance and
correctness checks must pass, and the user must explicitly authorize TFEX-4 implementation.
Adequate downloaded research history and calibrated numeric parameters are not required to
write deterministic `RESEARCH_ONLY` code, but are required before parameter search and
evidence promotion.

No strategy implementation, data acquisition, parameter search, Settrade call, order
action, or live-trading activation is authorized by this document.
