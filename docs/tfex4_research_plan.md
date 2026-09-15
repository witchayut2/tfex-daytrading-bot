# TFEX-4 Research Plan

Status: **`R4_RESEARCH_PLAN_LOCKED` / `TFEX4_NOT_STARTED`**

This document is the canonical R4 pre-code research-plan contract for TFEX-4. It freezes
the initial Strategy A/B hypothesis families, experiment accounting, conservative research
execution semantics, and evidence-governance procedures. It does not implement a strategy,
acquire data, choose a winning parameter, run an experiment, inspect a holdout, authorize
TFEX-4, or enable paper or live execution.

Read it with `docs/tfex4_definition_lock.md`, `docs/tfex4_research_readiness.md`,
`docs/tfex_strategy_research_validation_protocol.md`, and
`docs/tfex_risk_order_position_contract.md`. Those safety, causality, risk, and evidence
contracts remain authoritative. A conflict fails closed.

```text
TFEX-2 = TFEX2_COMPLETE
TFEX-3 = TFEX3_COMPLETE
TFEX-4 = TFEX4_NOT_STARTED
research readiness = R4_RESEARCH_PLAN_LOCKED
strategy evidence = RESEARCH_ONLY
live_orders_enabled = false
```

## 1. R4 boundary and vocabulary

R4 locks procedures and governance caps, not alpha values. Every numeric strategy range
remains `SEARCH_RANGE_NOT_LOCKED` until a validated Tier B inventory supports a defensible
finite declaration. No continuous optimizer, profitable result, or calibrated threshold is
required for R4.

The following terms are distinct:

- **Structural candidate:** one predeclared tuple of mechanical strategy choices.
- **Numeric configuration:** one immutable finite `ParameterSet` inside one structural
  candidate.
- **Optional-filter hypothesis:** one named filter family compared with the no-filter
  baseline under a new search ID.
- **Robustness trial:** a declared adjacent-parameter or stress evaluation of an existing
  hypothesis, not a hidden new hypothesis.
- **Cost-sensitivity trial:** the same frozen candidate under a different declared cost
  model, not another alpha candidate.
- **Experiment:** one immutable registered evaluation tuple. The current code calls its
  identity `TrialDefinition.trial_id`; this plan uses `experiment_id` as the canonical
  governance term.
- **Execution model:** the immutable semantics currently referenced by
  `ResearchExecutionPolicy.policy_id` and `TrialDefinition.execution_policy_id`. Future
  schemas must expose that value consistently as `execution_model_id`; no parallel identity
  may be invented.

Known scaffold gaps are explicit. Before R6, the existing models must be extended without
weakening their current invariants: `ExitPolicyKind` needs a real
`OPPOSING_LIQUIDITY` member; multi-contract research needs campaign/segment identity;
registry records need the complete section 7 audit fields and terminal outcomes; metrics
need all section 15 strata; and cost models need separate spread, tax, other-charge, and
embedded-component fields. `OPPOSING_LIQUIDITY` must never be aliased to
`STRUCTURE_TARGET`.

## 2. Strategy A finite V1 structural campaign

All four Core V1 candidates use the locked `LIQUIDITY_SWEEP_REVERSAL_V1` state machine,
one-minute closed sweep/reclaim, mandatory later one-minute CHoCH, exact sweep-extreme stop,
one-minute zones, no optional filter, and the research exit rule
`A_NEAREST_OPPOSING_LIQUIDITY_V1`.

That exit rule selects at proposal time the nearest same-symbol, confirmed, active,
unswept opposing liquidity strictly beyond entry, minimizes absolute price distance, and
breaks equal-price/identity ties by ascending immutable level ID. If no such level exists,
no proposal exists. It is a causal fixed-price research rule, not a profitability claim.

### Core V1

| Candidate ID | Trigger | Zone | Hypothesis and mechanism | Dependencies | Numeric calibration | Why V1 |
| --- | --- | --- | --- | --- | --- | --- |
| `A_CORE_RETEST_FVG_1M_OPP_LIQ_V1` | `RETEST_REJECTION` | `FVG`, `1m` | A closed rejection after a swept level, CHoCH, and selected imbalance retest is a distinct reversal mechanism. | TFEX-2 closed 1m state; TFEX-3 liquidity, sweep, CHoCH, FVG, and opposing-level identity; locked nearest-zone rule. | Minimum cost-adjusted RRR only; `SEARCH_RANGE_NOT_LOCKED`. | Establishes the simplest rejection/FVG baseline. |
| `A_CORE_RETEST_OB_1M_OPP_LIQ_V1` | `RETEST_REJECTION` | `ORDER_BLOCK`, `1m` | The same rejection mechanism is evaluated with the locked BOS-anchored origin zone instead of an imbalance. | Same causal inputs, with Order Block lifecycle and BOS identity. | Minimum cost-adjusted RRR only; `SEARCH_RANGE_NOT_LOCKED`. | Isolates zone kind while holding trigger, timeframe, stop, and exit constant. |
| `A_CORE_MICROBREAK_FVG_1M_OPP_LIQ_V1` | `CONFIRMED_MICRO_BREAK` | `FVG`, `1m` | A later confirmed same-direction micro structure break is a distinct post-sweep confirmation mechanism. | Same causal inputs plus confirmed 1m BOS/CHoCH after zone selection. | Minimum cost-adjusted RRR only; `SEARCH_RANGE_NOT_LOCKED`. | Isolates trigger mode against the FVG baseline. |
| `A_CORE_MICROBREAK_OB_1M_OPP_LIQ_V1` | `CONFIRMED_MICRO_BREAK` | `ORDER_BLOCK`, `1m` | The confirmed micro-break mechanism is evaluated with the BOS-anchored origin zone. | Same causal inputs plus Order Block lifecycle and confirmed micro structure. | Minimum cost-adjusted RRR only; `SEARCH_RANGE_NOT_LOCKED`. | Completes the finite two-trigger by two-zone comparison without adding another dimension. |

Candidate choice is based on orthogonal mechanism coverage, not expected performance.

### Experimental later

The following require a new versioned search family and may change only one declared
structural factor relative to a retained Core V1 candidate:

- `5m` zone-timeframe replicas;
- `FIXED_R`, `STRUCTURAL_TARGET`, or `VWAP_TARGET` exit-family comparisons; and
- a separately defined alternative opposing-liquidity rule.

### Not active in the initial search

- `PARTIAL_RUNNER`, `STRUCTURE_TRAIL`, `ATR_TRAIL`, and `TIME_STOP`;
- cross-products of zone timeframe and exit family;
- best-setup-only ranking; and
- every optional filter in section 4.

Those variants add path-dependent management or extra hypotheses and cannot enter the Core
V1 search by configuration convenience.

## 3. Strategy B finite V1 structural campaign

Both Core V1 candidates use the locked `TREND_CONTINUATION_PULLBACK_V1` state machine,
closed 15-minute directional structure, earliest same-direction 5-minute BOS, `FULL_DAY`
VWAP, 5-minute zones linked to that BOS impulse, `TICKS` extension representation, earliest
post-touch one-minute BOS/CHoCH, exact zone-far-boundary stop, no optional filter, and the
locked nearest confirmed active unswept opposing-liquidity target.

### Core V1

| Candidate ID | VWAP | Zone | Extension | Hypothesis and mechanism | Dependencies | Numeric calibration | Why V1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `B_CORE_FULLDAY_FVG_5M_TICKS_V1` | `FULL_DAY` | `FVG`, `5m` | `TICKS` | Continuation after a 5m BOS can pull back to a same-impulse 5m imbalance before a causal 1m continuation trigger. | TFEX-2 full-day VWAP and verified tick size; TFEX-3 15m structure, 5m BOS/FVG, 1m structure, and opposing liquidity. | VWAP-slope lookback, maximum mitigation, maximum extension ticks, and minimum cost-adjusted RRR; all `SEARCH_RANGE_NOT_LOCKED`. | Uses one VWAP and exact tick units, aligns the zone timeframe with the initiating BOS, and supplies the smallest FVG baseline. |
| `B_CORE_FULLDAY_OB_5M_TICKS_V1` | `FULL_DAY` | `ORDER_BLOCK`, `5m` | `TICKS` | The same continuation sequence can pull back to the exact BOS-anchored 5m origin candle. | Same causal inputs, with Order Block BOS identity and lifecycle. | The same four numeric parameter IDs; all `SEARCH_RANGE_NOT_LOCKED`. | Isolates zone kind while holding every other structural choice fixed. |

Candidate choice is based on dependency simplicity and controlled comparison, not expected
performance. `FULL_DAY` is used because one causal definition applies across both continuous
sessions. `TICKS` uses verified instrument granularity and avoids adding ATR-calibration
dependency to the first structural campaign.

### Experimental later

Each requires a new search family and a one-factor-at-a-time comparison against a retained
Core V1 candidate:

- matching-session `MORNING` or `AFTERNOON` VWAP;
- `ATR_NORMALIZED` extension; and
- a reviewed `1m` zone-to-5m-BOS linkage rule.

### Not active in the initial search

- the full 24-cell VWAP/zone/timeframe/extension cross-product;
- mixed VWAP modes selected retrospectively by trade or session;
- combined changes to zone timeframe and extension mode;
- alternate targets; and
- every optional filter in section 4.

## 4. Optional-filter governance

The locked policy is **`BASELINE_FIRST_V1`**:

1. Core structural candidates run first with `FILTER_NONE`.
2. An optional-filter experiment may add exactly one predeclared family to one frozen
   structural/numeric baseline.
3. The eligible family list is closed: VWAP proximity, relative volume, ATR penetration,
   time/session, failed-morning/afternoon-continuation context, or roll/expiry context.
4. Each filter requires its own hypothesis ID, search ID, causal definition, input
   availability rule, finite numeric declaration where applicable, and no-filter control.
5. At most two single-filter hypotheses per strategy may be opened under V1 governance.
6. A filter combination is never an extension of an existing trial. It requires a new
   hypothesis family, new search ID, new budget declaration, and review before results.
7. No filter may be stacked, removed, or redefined because an observed result looked poor.

The initial Core V1 campaign authorizes zero optional-filter trials. Section 6 reserves a
bounded later allowance; using it requires preregistration before that filter's result is
observed.

## 5. Numeric candidate-generation procedure

Every numeric parameter declaration must contain:

```text
parameter_id
unit
causal_definition
lower_bound_rationale
upper_bound_rationale
finite_candidate_values
declared_at
source_or_rationale
dependencies
search_id
```

Rules:

1. Values must be decimal/integer values in the declared unit and exactly serializable.
2. Bounds derive from verified contract granularity, causal feature behavior, Tier B
   inventory coverage, or an explicit operational constraint—not strategy performance.
3. Candidate values are finite and frozen before the first trial in the search family.
4. An ordinal/numeric parameter should have at least three distinct ordered values when the
   admissible domain permits lower/center/upper neighborhood evidence.
5. A full Cartesian product is not automatic. It must fit the section 6 cap; otherwise the
   declaration must reduce dimensions on non-performance grounds before any result.
6. No continuous, Bayesian, random, evolutionary, adaptive, or result-directed optimizer is
   allowed in initial V1.
7. No interpolation between declared values creates an undeclared candidate.
8. A new or changed value creates a new search declaration and never rewrites an old one.

The initial method is `FINITE_PREDECLARED_GRID_OR_CANDIDATE_SET`. Until Tier B inventory
exists, every numeric domain and value remains `SEARCH_RANGE_NOT_LOCKED`. R4 locks this
procedure; it does not manufacture candidate values.

## 6. Trial-budget governance

The following caps are `GOVERNANCE_CAP_NOT_ALPHA_PARAMETER`. They limit researcher degrees
of freedom and were selected before results, not from expected profitability.

| Trial class | V1 cap | Accounting rule |
| --- | ---: | --- |
| Strategy A structural hypotheses | 4 | Exactly the four Core V1 IDs in section 2; no replacement or expansion in the same family. |
| Strategy B structural hypotheses | 2 | Exactly the two Core V1 IDs in section 3. |
| Structural hypotheses retained for numeric calibration | 2 per strategy | More than two qualifying candidates produces `SELECTION_UNRESOLVED`; net profit cannot break the tie. |
| Numeric configurations | 24 per retained structural hypothesis | Includes its reference configuration and every declared numeric alternative. At most 23 additional numeric trials follow the reference run. |
| Optional-filter hypotheses | 2 per strategy | One filter family at a time, each under a new search ID; zero are active in Core V1. |
| Neighborhood robustness | At most 2 adjacent configurations per tuned parameter per provisional candidate | Use the nearest lower and upper declared candidates where available. Existing trial results are referenced rather than rerun under a second ID. |
| Cost sensitivity | 1 additional mandatory rerun per provisional candidate | The primary run uses `BASE_RESEARCH`; the paired rerun uses `CONSERVATIVE_RESEARCH`. |

The caps follow the minimum questions being asked. Four A candidates are exactly the
two-trigger by two-zone comparison; two B candidates isolate zone kind while every other
structural choice stays fixed. Retaining at most two avoids multiplying later numeric work
without forcing a net-profit tie-break. Twenty-four configurations permit a small finite
declared set but prohibit the obvious 81-cell four-parameter grid of three values each. Two
single-filter hypotheses test whether a filter family adds robust information without
authorizing free stacking. Two adjacent points are the minimum lower/upper neighborhood,
and one conservative cost rerun supplies the mandatory two-scenario comparison. None of
these counts is a strategy threshold.

Every experiment has exactly one primary `trial_class`. Robustness and cost-sensitivity
records cite the originating experiment and do not masquerade as new hypotheses. Subgroup
reports, best-trade removal, and recomputation of metrics from the same immutable trade
ledger are artifacts of the original trial, not extra unregistered trials.

Budget exhaustion stops the family. Any increase requires a new version and search ID,
records the non-performance rationale and all evidence already observed, preserves every
old failure, and is declared before any new candidate result is inspected. A budget cannot
be increased merely because no candidate won.

A new search family is also mandatory when a declaration changes its structural candidates,
numeric domain/values, filter, exit/stop rule, selection rule, partition, execution model,
cost model used for selection, metric/threshold method, or trial cap. The new declaration
records why it exists and which prior results were already visible. It cannot erase or
rebrand the earlier family's evidence.

## 7. Immutable experiment registry

Before execution, every experiment definition must be appended with at least:

```text
experiment_id
search_id
hypothesis_id
strategy_id
strategy_version
code_commit
declared_at
executed_at
dataset_ids
partition_plan_id
candidate_parameter_set
cost_model_id
execution_model_id
metric_schema_version
result_status
failure_reason
result_artifact_hash
```

`declared_at` precedes execution. `executed_at`, `result_status`, `failure_reason`, and
`result_artifact_hash` are appended as the terminal record; the definition is never edited.
`code_commit` identifies immutable code. Dataset, partition, parameter, cost, execution,
and metric identities are content-addressed or versioned and cannot be replaced in place.

Terminal accounting retains successful, failed, rejected, invalid, zero-trade,
unprofitable, and aborted attempts. An unprofitable but mechanically valid run retains full
metrics; it is not relabelled as an infrastructure failure. An aborted/invalid run retains
the exact reason and a hash of its available sanitized artifact. Corrections append a
superseding record while preserving the original. There are no deletions, reused IDs,
overwritten results, or hidden exploratory trials.

The current `TrialRegistry` already enforces predeclared searches, immutable IDs, and one
terminal result. Before R6 its schemas must add the missing audit fields and explicit
outcome accounting above without weakening existing validation.

## 8. Multiple-testing control

The V1 policy is:

```text
PREDECLARED_FAMILY
+ FULL_TRIAL_DISCLOSURE
+ VALIDATION_CONFIRMATION
```

Each search ID is one family-wise group. Reports disclose the complete structural, numeric,
filter, exit, stop, selection-rule, cost-sensitivity, and robustness counts, including all
failed and non-profitable attempts. A calibration choice uses A only; its frozen
confirmation uses B. C never selects a candidate, parameter, execution model, cost model,
metric, threshold, or narrative.

No Bonferroni, Holm, Benjamini-Hochberg, Deflated Sharpe, or other formal correction is
claimed in V1. The current metrics do not define valid null hypotheses, p-values, dependence
assumptions, or a canonical Sharpe statistic, so applying those methods would create false
precision. This simpler policy does not prove that family-wise false-selection risk is
numerically controlled. Marginal improvements are therefore treated as inconclusive;
retention requires predeclared multi-metric validation and neighborhood robustness.

A formal correction may be added only under a new protocol version that declares a
compatible statistic and its assumptions before evaluation.

## 9. Research execution model

The initial model is:

```text
execution_model_id = TFEX_RESEARCH_OHLC_1M_CONSERVATIVE_V1
evidence = complete raw-contract 1m OHLCV bars
timing = NEXT_VALID_EXECUTABLE_EVENT
same_bar_policy = PROHIBITED
partial_fill_policy = ALL_OR_NONE_OHLC_RESEARCH_V1
```

It applies only to historical research. It is not broker behavior, paper execution, or a
claim about queue position. Quantity/P&L execution evidence still requires the canonical
`TradeProposal -> RiskEngine -> ApprovedTradePlan` path. Quantity-free signal studies do
not create fill or promotion evidence.

### Common timing

- A source bar labelled `t` covers `[t, t + 1 minute)` and is knowable only at its close.
- The signal/trigger bar is a reference and can never fill its own intent.
- The first eligible event is the immediately next complete, contiguous one-minute bar in
  the same continuous session and raw contract.
- A forming bar, pre-open observation, midday break, missing bar, other raw symbol, or later
  skipped-to bar is not a valid substitute.
- Fill decisions based on one-minute high/low are recorded no earlier than that bar's close;
  no intra-bar timestamp is fabricated.

Spread and slippage are not embedded in V1 raw fill references. Their embedded flags are
`false`, and the selected cost model deducts them exactly once from net results. Gross and
net results retain separate values.

### Market intent

`MARKET_NEXT_OPEN_V1` fills the full intended quantity at the open of the immediately next
valid bar. Buy and sell use the same observable open; adverse spread/slippage is applied
separately by the declared cost model. If that next bar is unavailable, the simulation is
invalid rather than moved to a more convenient bar.

### Limit intent

`LIMIT_STRICT_CROSS_AON_V1` uses a conservative queue proxy:

- a buy limit fills only when a later eligible bar has `low < limit_price`;
- a sell limit fills only when it has `high > limit_price`;
- equality/touch alone does not fill because OHLCV cannot prove queue priority;
- a qualifying fill is all-or-none at the limit price;
- a favorable opening gap through the limit still fills at the limit, with no invented
  price improvement; and
- an adverse opening gap does not fill unless that eligible bar later strictly crosses the
  limit.

The model ignores queue position by requiring strict cross, not by claiming priority.

### Stop intent

`STOP_TOUCH_ADVERSE_GAP_AON_V1` treats a stop as already active before the eligible bar:

- a buy stop triggers when `open >= stop_price` or `high >= stop_price`;
- a sell stop triggers when `open <= stop_price` or `low <= stop_price`;
- equality triggers;
- a buy fills at `max(stop_price, open)` and a sell at `min(stop_price, open)`; and
- declared adverse spread/slippage is deducted separately exactly once.

Thus an adverse gap through a stop uses the worse opening price. An intrabar trigger uses
the stop price. No better price is inferred from the bar range.

### Stop and target in the same bar

`STOP_FIRST_WHEN_OHLC_SEQUENCE_UNKNOWN_V1` is the primary conservative rule. If the bar
open already breaches one boundary, that opening event resolves first. Otherwise, when the
same later bar can reach both protective stop and target and no ordered ticks exist, the
stop executes first for both long and short positions. A favorable target-first ordering is
never selected from OHLC. Any future ordered-tick or sensitivity model requires a different
execution-model ID and separate evidence.

### Gap-through summary

- Market intent: next valid open is the raw fill reference.
- Limit/target: favorable gap receives no improvement beyond the limit/target; adverse gap
  does not fill a resting limit without a later strict cross.
- Stop: adverse gap fills from the worse open rather than the stop price.
- A gap never allows an intent to cross lunch, session expiry, LTD cutoff, or symbol change.

### Partial fills

One-minute OHLCV cannot prove queue position or executable quantity. V1 therefore uses an
explicit all-or-none research simplification. It never prorates fills from bar volume and
never fabricates a partial fill. Partial fills remain required future TFEX-5/paper behavior
and need ordered order-book/broker evidence under another model.

### Session, expiry, and symbol cancellation

Pending entry intents cancel at the earliest of:

- the end of the continuous morning/afternoon session that created the setup;
- the configured entry/mandatory-flatten boundary;
- the contract-specific LTD cessation or stricter safety cutoff;
- raw-symbol transition; or
- critical data/sequence invalidation.

Pending profit-taking intents are superseded at mandatory EOD/LTD flatten. Existing
protective stops are never canceled merely because entries or targets are canceled; they
remain until exposure is deterministically flattened. No intent or position silently moves
to another contract.

### Missing events

A missing expected one-minute event, non-contiguous sequence, or unknown session boundary
produces `INVALID_EXECUTION_DATA`. The affected simulation cannot interpolate, forward-fill,
skip to a later bar, or count as valid execution evidence. The experiment and failure remain
in the registry; a critical dataset defect rejects the affected partition under the data
admission contract.

## 10. Execution-model versioning

Every result cites exactly one immutable `execution_model_id`. A change to any fill
reference, timing, touch/cross rule, stop trigger, same-bar precedence, gap behavior,
partial-fill rule, spread/slippage embedding, cancellation, or missing-event treatment
requires a new ID and new registered trials. Old results are never silently recomputed under
new semantics.

The current `ResearchExecutionPolicy` rule-ID fields must be populated with the named V1
rules in section 9 when implementation is authorized. This document changes no runtime
schema or behavior.

## 11. Cost-model completion rule

The structural scenario IDs remain:

- `BASE_RESEARCH`—mandatory for primary results;
- `CONSERVATIVE_RESEARCH`—mandatory paired sensitivity; and
- `OPTIMISTIC_RESEARCH`—optional diagnostic only and inactive in initial V1.

Before R6, at least complete numeric `BASE_RESEARCH` and `CONSERVATIVE_RESEARCH` models must
exist. Each immutable model separately records:

```text
cost_model_id
exchange_charge
broker_commission
VAT_or_tax
spread_assumption
slippage_per_side
other_charges
embedded_component_flags
value/unit/status/source/effective_as_of for every component
```

`UNKNOWN` never becomes zero. The THB 7 figure remains a verified maximum/cap and may appear
only in a clearly labelled conservative stress component, never as the actual account
charge. Actual broker commission and tax treatment remain unknown until evidenced. Spread
and slippage are assumptions until supported by suitable quote/fill data. Embedded flags
must prove that no component is charged both through fill price and cost deduction.

Any numeric change creates a new `cost_model_id`. Results always report gross P&L, every
component, total costs, and net P&L separately.

### Risk and margin boundary

Signal-only structural correctness may remain quantity-free and produces no fill, P&L, or
promotion evidence. Any quantity or P&L claim must use the canonical `RiskEngine`, complete
versioned research risk/cost inputs, and the total-post-trade-margin rule:

```text
free_equity_before_trade - total_post_trade_margin_requirement(q)
    >= required_free_equity_buffer
```

Historical research may use only an explicitly predeclared hypothetical account/margin
scenario. It never fabricates broker health or live free equity, and it cannot establish a
production margin rate. Unknown, stale, conflicting, or unavailable required evidence fails
closed. The numeric `required_free_equity_buffer` remains `UNCALIBRATED`.

## 12. Chronological partition procedure

Exact boundaries remain unselected until Tier B history exists. Once the inventory is
available, the operator must:

1. enumerate validated complete raw-contract segments with dataset/manifest/checksum,
   symbol, listing/LTD, calendar, source, and license identity;
2. classify calendar, normal/expiry/roll, regime, volatility, session, gap, and volume
   coverage without reading strategy results;
3. order all admitted contract-local segments chronologically without back-adjustment or
   artificial price splicing;
4. choose half-open A/B/C boundaries chronologically from availability and coverage facts;
5. record the boundary rationale before any parameter search;
6. create and hash an immutable multi-contract campaign and partition plan; and
7. initialize C as `UNTOUCHED` and refuse any later boundary change based on performance.

The roles remain `A_DEVELOPMENT_CALIBRATION`, `B_VALIDATION`,
`C_UNTOUCHED_FINAL_HOLDOUT`, and `D_FORWARD_PAPER`. D is live-arriving future data. There is
no random split, and chronology takes precedence over forcing each contract into every
partition. Each result retains its raw contract and segment ID, with state reset at every
symbol boundary.

The current `PartitionPlan` intentionally accepts one raw symbol. Before R6, a reviewed
`ResearchCampaign`/`ResearchSegment` extension must reference multiple ordered single-
contract plans without weakening that no-splice invariant.

## 13. Calibration and candidate-retention sequence

The locked sequence is:

1. **Mechanical correctness:** prove strategy state machines, causal inputs, rejection
   codes, batch/incremental equivalence, prefix/future-mutation stability, and execution
   model invariants. No performance promotion occurs.
2. **Strategy A structural screening on A:** evaluate only the four Core V1 candidates under
   the frozen reference configuration, `FILTER_NONE`, `BASE_RESEARCH`, and the V1 execution
   model.
3. **Strategy A finite numeric calibration on A:** evaluate at most the section 6 budget for
   no more than two retained structural hypotheses.
4. **Strategy A frozen validation on B:** freeze candidate, parameters, costs, execution,
   metrics, and thresholds before B. B cannot tune them.
5. **Strategy B structural screening on A:** evaluate only its two Core V1 candidates under
   the same governance.
6. **Strategy B finite numeric calibration on A:** evaluate at most the section 6 budget for
   no more than two retained structural hypotheses.
7. **Strategy B frozen validation on B:** freeze everything before B. B cannot tune it.

Strategies A and B remain independent through step 7. Combined A+B, all-qualified versus
best-only, capital allocation, and arbitration require later separately registered research.
C is not accessed in this sequence.

A candidate can become `PROVISIONAL_RESEARCH_CANDIDATE` only when:

- the run is mechanically valid, complete, costed, and fully registered;
- no causal, data, risk-route, or execution-model invariant failed;
- setup/trade-count adequacy is not `INSUFFICIENT` under a later predeclared threshold;
- its declared parameter neighborhood is not `FRAGILE_NARROW_OPTIMUM`;
- required chronological, contract, expiry, session, direction, regime, volume, cost, and
  best-trade-removal evidence is complete; and
- it meets the frozen multi-metric research thresholds calibrated from permitted A data.

No threshold value is invented here, so no candidate is currently retained. Highest net
profit alone is never a rule. All candidates passing the later frozen gate remain visible;
dominated and failed candidates remain recorded. At most two per strategy may advance to
numeric calibration or B. If a non-dominated passing set exceeds that cap, status is
`SELECTION_UNRESOLVED`; net profit, hindsight, or C cannot break the tie.

If B fails, the frozen validation result stands. Changing a candidate or threshold creates
a new version/search and requires a new valid validation claim; B is not repeatedly mined
under the old declaration.

## 14. Walk-forward comparison procedure

`ANCHORED` and `ROLLING` remain the only initial methods; neither is selected at R4. Before
running either, create a paired method-comparison experiment over pre-C history with:

- identical chronological validation windows;
- predeclared calibration-window, validation-window, and step rules;
- identical eligible candidate sets, cost and execution models, metrics, contract resets,
  and freeze/recalibration instants; and
- separate immutable plan, fold, trial, and result IDs.

Each fold selects parameters only from its calibration prefix, freezes them before its
validation window, and resets all state at contract boundaries. Validation windows do not
overlap. Both method plans execute in chronological order. Exact window lengths remain
`SEARCH_RANGE_NOT_LOCKED` until Tier B coverage is known.

Method choice uses the same frozen multi-metric/robustness procedure, never C and never one
best fold or aggregate net profit. Conflicting or indistinguishable evidence returns
`WALK_FORWARD_METHOD_UNRESOLVED`; it does not trigger retrospective window changes. The
selected method and rationale are frozen before any final-holdout request.

## 15. Metric schema and required reports

Every aggregate, fold, strategy, candidate, cost sensitivity, and required subgroup report
uses an immutable `metric_schema_version` and includes:

- total/winning/losing/breakeven trades, win rate, average win/loss;
- expectancy per trade in THB and R, profit factor, gross P&L, explicit costs, and net P&L;
- average/median R, maximum drawdown and duration, MAE/MFE, and consecutive losses;
- chronological daily P&L, trades/day, exposure, setup count, rejected setups, and
  setup/trade frequency; and
- trial-family count disclosure and uncertainty/sample limitations.

Independently visible deterministic strata are:

- chronological fold;
- raw contract;
- expiry/transition versus non-expiry;
- volatility regime;
- structure regime;
- morning/afternoon session;
- long/short direction; and
- relative-volume context.

Every stratum label cites a causal versioned rule. Missing or uncalibrated regime/volume
labels remain explicit and cannot be converted to a favorable bucket. The existing
`PerformanceMetrics` and `StratumDimension` are a tested base; their missing contract,
expiry, fold, direction, and regime-detail dimensions must be extended before R6.

## 16. Robustness procedure

For every provisionally selected numeric candidate:

1. evaluate the nearest lower and upper declared value for each tuned numeric parameter
   where available, holding other parameters fixed;
2. record a boundary limitation when only one adjacent candidate exists—never invent one;
3. report every section 15 stratum with sample size and costs;
4. rerun under `CONSERVATIVE_RESEARCH` and the declared slippage sensitivity;
5. recompute results after removing the single best net-P&L trade, retaining both reports;
6. report drawdown magnitude/duration and chronological concentration; and
7. evaluate setup/trade-count adequacy under the later frozen threshold record.

A center whose adjacent declared candidates collapse is
`FRAGILE_NARROW_OPTIMUM` and cannot advance. No numeric plateau width, permissible
degradation, drawdown, setup count, or trade-count threshold is selected at R4. Section 17
locks how those values may later be calibrated.

## 17. Threshold-calibration governance

Every future acceptance threshold is an immutable record containing:

```text
threshold_id
metric
value
unit
calibration_dataset
method
declared_at
reviewed_at
reviewer_id
review_status
applicable_strategy_version
```

Thresholds are derived only from permitted A development/calibration evidence using a
predeclared method. They are frozen before B validation and never selected or moved because
B or C looked poor. C is never a calibration source. A missing review, method, provenance,
unit, or applicable version leaves the threshold `UNCALIBRATED` and fails closed.

A change creates a new strategy/research/threshold version, preserves the old threshold and
failed validation, and requires a fresh validation claim. Production thresholds, risk
limits, cost values, and `required_free_equity_buffer` remain uncalibrated in this plan.

## 18. Promotion-state semantics

Promotion is monotonic and requires all prior states:

| State | Exact evidence boundary |
| --- | --- |
| `RESEARCH_ONLY` | Definitions, deterministic code, fixtures, smoke runs, or incomplete/uncalibrated research. This is the default and may coexist with `TFEX4_COMPLETE`. |
| `BACKTEST_EVIDENCE` | Real validated raw-contract A research plus one frozen B confirmation, complete registry, risk route where quantity/P&L is claimed, two mandatory cost models, V1 execution model, required metrics/strata, robustness, and frozen research thresholds. |
| `WALK_FORWARD_EVIDENCE` | Prior state plus the predeclared causal walk-forward program and method comparison, with fold-level robustness and no C access. |
| `HOLDOUT_EVIDENCE` | Prior state plus exactly one registered final evaluation of an untouched C; the ledger becomes `CONSUMED_FINAL_EVALUATION` and C can never tune anything. |
| `PAPER_FORWARD_EVIDENCE` | Prior state plus distinct live-arriving D forward-test and paper-trading evidence under the frozen strategy, risk, cost, and execution contracts. |
| `LIVE_CANDIDATE` | Prior state plus operational proving, independently reviewed thresholds and controls, and all real-money gates. It remains an evidence label with live orders disabled. |

Synthetic fixtures, a five-day smoke dataset, omitted costs, an incomplete registry, a
burned holdout, a fragile optimum, historical reconstruction labelled forward, or milestone
completion cannot promote evidence. Promotion failure returns `RESEARCH_ONLY` with reasons;
it never grants the nearest lower state implicitly.

## 19. R4 decision and later gates

The R4 checklist is complete:

- finite structural-candidate governance—sections 2 and 3;
- numeric candidate-generation procedure—section 5;
- trial-budget governance—section 6;
- immutable experiment registry—section 7;
- multiplicity-control policy—section 8;
- execution/fill semantics and versioning—sections 9 and 10;
- cost-model completion rule—section 11;
- chronological partition and walk-forward procedures—sections 12 and 14;
- calibration sequence and retention rule—section 13;
- metric and robustness procedures—sections 15 and 16;
- threshold-calibration procedure—section 17; and
- promotion-state semantics—section 18.

Therefore the current research-readiness state is `R4_RESEARCH_PLAN_LOCKED`. R1 remains
satisfied. R2/R3 Tier B acquisition/validation have not occurred, R5 is not granted,
TFEX-4 is not started, and strategy evidence remains `RESEARCH_ONLY`.

Before R5, TFEX-2/3 QA must remain green, this R4 plan and the definition lock must remain
valid, C must remain untouched, every unknown must remain explicit, and the user must
explicitly authorize deterministic TFEX-4 implementation.

Before R6, R2/R3 Tier B data must be acquired and validated under verified rights; the
multi-contract campaign schema must exist; actual A/B/C partitions and walk-forward windows
must be frozen; deterministic TFEX-4 implementation must be complete; finite numeric
candidate values, complete `BASE_RESEARCH`/`CONSERVATIVE_RESEARCH` cost models, execution
model records, registry extensions, metric-schema extensions, and calibration inputs must
all be frozen. No parameter search may begin earlier.

No data acquisition, strategy implementation, optimizer, backtest, holdout access,
Settrade call, credential access, order action, commit, push, or live-trading activation is
authorized by this document.
