# TFEX-4 Definition Lock

Status: **SPECIFICATION LOCKED / TFEX-4 NOT STARTED**

This document locks the deterministic implementation contract for Milestone TFEX-4. It
does not implement a strategy, start TFEX-4, calibrate a parameter, run a research trial,
connect to Settrade, create an order, or authorize paper or live execution.

Read it with `CLAUDE.md`, `CLAUDE_TFEX.md`, `docs/tfex_architecture.md`,
`docs/tfex3_acceptance.md`, `docs/tfex_risk_order_position_contract.md`, and
`docs/tfex_strategy_research_validation_protocol.md`. The locked risk and research
contracts remain authoritative. If future code cannot satisfy every applicable rule below,
it must fail closed rather than choose a plausible default.

## 1. Milestone boundary

The canonical TFEX-4 path is:

```text
TFEX-2 closed market state
    -> TFEX-3 confirmed neutral analysis
    -> Strategy A or Strategy B
    -> quantity-free TradeProposal | None
    -> pre-trade gates and RiskEngine
    -> RiskDecision
    -> ApprovedTradePlan when approved
    -> STOP
```

Execution, order intent, fills, positions, P&L, reconciliation, and the paper broker belong
to TFEX-5. Read-only realtime ingestion belongs to TFEX-7. Opening Range Breakout remains
disabled and outside the initial TFEX-4 implementation.

Two independent status axes must never be collapsed:

1. The implementation milestone may eventually become `TFEX4_COMPLETE` when the
   deterministic code and correctness evidence in section 15 pass.
2. Each strategy remains governed by the research states `RESEARCH_ONLY`,
   `BACKTEST_EVIDENCE`, `WALK_FORWARD_EVIDENCE`, `HOLDOUT_EVIDENCE`,
   `PAPER_FORWARD_EVIDENCE`, and `LIVE_CANDIDATE`.

`TFEX4_COMPLETE` will mean implementation-complete, not profitable, calibrated,
paper-ready, live-ready, or authorized to trade.

**Decision: `LOCK_NOW`.** This interpretation follows the explicit TFEX-4/TFEX-5 milestone
split and the separate evidence lifecycle. Backtest results cannot precede the code that
produces them; the research protocol requires the plan, search space, cost scenarios,
thresholds, adequate history, and authorization to be declared before implementation, not
`BACKTEST_EVIDENCE` to exist before code.

## 2. Shared strategy causality contract

### Repository evidence

TFEX-2 releases one immutable closed 1-minute event at a time and exposes only confirmed
5-minute and 15-minute bars. TFEX-3 emits append-only pivots, structure breaks, liquidity
events, FVGs, Order Blocks, and regimes. The research protocol permits a decision at `T`
to consume only artifacts whose `confirmed_at <= T`.

### Ambiguity

The legacy strategy prose does not define a common setup clock, expiry rule, duplicate
rule, or how a historical event time differs from the instant a proposal becomes knowable.

### Locked rule

- All inputs have the same raw contract symbol. No continuous series or cross-contract
  level may enter a proposal.
- Only closed source bars and confirmed TFEX-2/3 artifacts are eligible.
- A setup is a versioned state machine whose immutable identity includes strategy, side,
  initiating signal IDs, selected zone ID/type, trigger mode, and continuous session.
- `setup_event_time` is the market event time of the closed trigger bar that completes the
  final strategy condition.
- `setup_confirmed_at` is that trigger bar's actual close/confirmation time. It must be at
  least the maximum `confirmed_at` of every input used.
- `entry_eligible_at` at the TFEX-4 boundary means eligible for pre-trade risk evaluation,
  and equals `setup_confirmed_at`. It is not permission to fill.
- A TFEX-5 execution event, if ever implemented, must be strictly later than
  `entry_eligible_at` unless ordered post-confirmation tick evidence satisfies the separately
  locked research execution contract. TFEX-4 never simulates this.
- A setup expires at the end of the continuous morning or afternoon session in which it
  began. It cannot cross the midday break, date boundary, or contract boundary.
- Each setup can emit at most one immutable proposal. A rejected or expired setup cannot be
  resurrected by later data under the same setup ID.
- Batch, incremental, restart, prefix, and future-mutation outputs must be identical.

### Rejected alternatives

- Treating the historical pivot/event timestamp as the signal confirmation time.
- Reading forming 5-minute or 15-minute candles.
- Carrying a morning candidate into the afternoon without an explicitly researched rule.
- Re-selecting an input after later price action makes another input look better.
- Filling at the trigger close.

### Causal/non-repaint implications

Confirmed proposal history is append-only. Future changes may create new setup decisions
but may not revise, delete, backdate, or re-rank an earlier proposal.

### Parameters and alpha assumptions

The common clock and lifecycle are mechanical and introduce no profitability claim.

**Decision: `LOCK_NOW`.**

## 3. Shared deterministic zone selection

### Repository evidence

`FairValueGap` records symbol, timeframe, direction, bounds, source bar IDs, formation time,
confirmation time, and `ACTIVE/PARTIALLY_FILLED/FILLED/INVALIDATED` state. `OrderBlock`
records the same core identity plus its BOS and pivot anchor and
`ACTIVE/MITIGATED/INVALIDATED` state. TFEX-3 deliberately defines no total ranking between
different source types or timeframes.

### Ambiguity

The strategy prose says “FVG or Order Block” but supplies no cross-type priority or rule for
choosing among several same-type zones.

### Locked rule

The strategy configuration must declare before replay:

- `zone_kind`: `FVG` or `ORDER_BLOCK`;
- `zone_timeframe`: `1m` or `5m`; and
- a versioned selection-rule ID.

There is no default and no retrospective switching. FVG and Order Block are separate
research variants, not competitors in one invented ranking.

At an as-of instant, a zone candidate must:

- match the proposal raw symbol, configured type/timeframe, and strategy direction;
- have `confirmed_at <= as_of` and have been confirmed before its first eligible touch;
- be `ACTIVE` when selected; and
- lie on the pullback side of the reference price or contain it.

For a long, the pullback distance is `max(reference_price - upper_bound, 0)` and a candidate
whose `lower_bound >= reference_price` is ineligible. For a short, distance is
`max(lower_bound - reference_price, 0)` and a candidate whose
`upper_bound <= reference_price` is ineligible. Choose the smallest distance. Resolve an
exact tie by ascending immutable zone ID. Record every candidate ID, distance, status, and
the selected ID in the setup evidence.

Strategy A uses its required CHoCH confirming close as the reference price. Strategy B
uses its initiating 5-minute BOS confirming close. Strategy B additionally constrains the
zone to the BOS impulse:

- an Order Block must cite that exact `bos_id`; or
- an FVG must confirm at the same confirmation instant as the BOS and include the BOS
  confirming bar among its three source bars.

### Rejected alternatives

- Arbitrary FVG-over-Order-Block or Order-Block-over-FVG priority.
- A weighted “quality” score, volume magic number, visual choice, or future reaction.
- Nearest-zone selection across different configured types/timeframes.
- Selecting a zone that was not yet confirmed or was already used/mitigated.

### Causal/non-repaint implications

The candidate set is frozen at selection time. A later zone cannot replace the selected
zone. Lifecycle changes after selection may invalidate the setup but never rewrite the
selection record.

### Parameters and alpha assumptions

Zone type and timeframe are strategy hypotheses and must be declared in the research search
space. The within-variant nearest-on-pullback selection is a deterministic routing rule, not
evidence that the nearest zone is profitable.

**Decision: `LOCK_NOW` for the mechanism; `DEFER_TO_RESEARCH` for zone type/timeframe.**

## 4. Strategy A — Liquidity Sweep Reversal

### Repository evidence

`CLAUDE_TFEX.md` section 17 requires a previously confirmed liquidity level, an exceed and
closed reclaim, a subsequent same-direction CHoCH, a valid same-direction FVG or Order
Block, a retest or confirmed micro-break, acceptable reward/risk, risk approval, eligible
contract/session, and current sequence-complete data. TFEX-3 already emits neutral
`LiquiditySweep`, `StructureBreak`, FVG, and Order Block artifacts.

### Ambiguity

The specification did not choose reclaim timeframe, define retest/micro-break, select a
zone, place the stop, select an exit family, or define invalidation and timestamps.

### Locked rule — `LIQUIDITY_SWEEP_REVERSAL_V1`

Long rules are below; short rules are their exact inverse.

1. **Eligible liquidity.** A long consumes a same-symbol confirmed low-side level from
   `CONFIRMED_SWING_LOW`, `EQUAL_LOWS`, `PREVIOUS_DAY_LOW`, `MORNING_LOW`,
   `AFTERNOON_LOW`, or `OPENING_RANGE_LOW`. A short consumes the corresponding high-side
   sources. The level must be active and confirmed before the sweep bar begins. Provisional
   running session extrema and unimplemented sources are ineligible.
2. **Sweep/reclaim.** Version 1 consumes the existing closed 1-minute `LiquiditySweep`.
   Long requires `BELOW_LOW`: the bar low is strictly below the level and its close strictly
   above it. Short requires `ABOVE_HIGH`: high strictly above and close strictly below.
   A touch, equal wick, exceed without reclaim, or wick without a closed reclaim is not a
   sweep setup.
3. **Structure confirmation.** The earliest same-symbol, 1-minute, same-direction `CHOCH`
   with `confirmed_at > sweep.confirmed_at` is required. A BOS does not substitute for this
   mandatory CHoCH.
4. **Zone.** After the CHoCH, apply section 3 using the CHoCH confirming close as reference.
   The zone may have been confirmed before or after the sweep, but it must be confirmed and
   active no later than trigger evaluation. Its direction must match the reversal.
5. **Trigger mode.** Configuration must declare exactly one mode before replay:
   - `RETEST_REJECTION`: the earliest later closed 1-minute bar intersects the selected
     zone, does not reach/cross its far boundary, and closes strictly beyond its proximal
     boundary in the trade direction. For a bullish zone this means
     `low > lower_bound`, `low <= upper_bound`, and `close > upper_bound`; bearish is
     inverted.
   - `CONFIRMED_MICRO_BREAK`: while the selected zone remains `ACTIVE`, the earliest later
     same-direction 1-minute BOS or CHoCH is the trigger. Its confirming close is already
     strictly beyond its recorded broken micro-structure price.
6. **Entry reference.** `TradeProposal.entry_price` is the trigger bar's close. It is a
   planned risk reference, not a fill assertion. TFEX-5 must revalidate any future
   executable price and costs.
7. **Initial stop.** Long stop anchor is the exact low of the sweep bar; short stop anchor
   is its exact high. No ATR or discretionary buffer is added. If this is not strictly on
   the protective side of the entry reference, no proposal exists.
8. **Exit.** A versioned exit family from section 7 must be declared and causally resolvable
   before a proposal exists. Minimum RRR or expectancy is evaluated later by `RiskEngine`
   under the supplied `StrategyRiskRule`.
9. **Invalidation before proposal.** Invalidate on an opposite 1-minute CHoCH after the
   required CHoCH; a closed bar strictly beyond the sweep extreme in the adverse direction;
   selected-zone terminal invalidation/fill before a valid trigger; loss of raw-symbol
   identity; a sequence/data-quality failure; or continuous-session expiry.
10. **Times.** Proposal `event_time` is the trigger bar event time and `confirmed_at` is its
    close. Sweep, level, CHoCH, zone, and trigger IDs and their original times remain in
    `source_signal_ids`/`rationale_inputs`.

Stable pre-proposal rejection codes must cover at least:

```text
LIQUIDITY_LEVEL_NOT_ELIGIBLE
SWEEP_NOT_CONFIRMED
REQUIRED_CHOCH_MISSING
ZONE_CONFIGURATION_MISSING
NO_ELIGIBLE_ZONE
ZONE_INVALIDATED
TRIGGER_CONFIGURATION_MISSING
TRIGGER_NOT_CONFIRMED
STOP_SIDE_INVALID
EXIT_POLICY_MISSING
DATA_QUALITY_REJECTED
SETUP_SESSION_EXPIRED
```

Gate and risk rejection codes remain separate and are added by section 10.

### Rejected alternatives

- Entry at the wick, liquidity-level price, CHoCH close, or zone boundary without the
  configured trigger.
- BOS as a replacement for the mandatory reversal CHoCH.
- A stop derived from an arbitrary ATR multiplier.
- Retrospectively choosing whichever trigger mode or zone produced the best trade.

### Causal/non-repaint implications

The sweep exists only at reclaim-bar close; CHoCH, zone, and trigger must then be known in
strict causal order. The proposal is immutable after trigger confirmation.

### Parameters and alpha assumptions

Zone type/timeframe, trigger mode, exit family, ATR penetration bounds, VWAP proximity,
relative-volume threshold, and minimum RRR/expectancy are research inputs. Preferred
confluences are explanatory score features only until separately calibrated. The strategy
sequence and sweep-extreme stop are versioned alpha hypotheses, not efficacy claims.

**Decision: `LOCK_NOW` for V1 mechanics; `DEFER_TO_RESEARCH` for every listed choice/value.**

## 5. Strategy B — Trend Continuation Pullback

### Repository evidence

`CLAUDE_TFEX.md` section 18 requires confirmed bullish/bearish 15-minute structure,
directional selected VWAP and slope, a same-direction 5-minute BOS, a fresh same-direction
FVG or Order Block, bounded mitigation, a 1-minute BOS/CHoCH trigger, bounded extension,
opposing liquidity sufficient for RRR, and risk approval. TFEX-2 supplies causal VWAP and
closed bars; TFEX-3 supplies structure, zones, and liquidity.

### Ambiguity

The specification did not select a VWAP mode or slope window, connect a zone to its impulse,
define freshness/mitigation/extension, identify the micro trigger, choose the stop, or
select among opposing liquidity levels.

### Locked rule — `TREND_CONTINUATION_PULLBACK_V1`

Long rules are below; short rules are their exact inverse.

1. **15-minute state.** The most recently confirmed 15-minute structure state at evaluation
   must be `BULLISH_STRUCTURE`; long rejects `UNRESOLVED`, contraction, expansion, bearish,
   or forming state. Short requires `BEARISH_STRUCTURE`.
2. **5-minute setup.** While that 15-minute state is active, the earliest newly confirmed
   same-direction 5-minute `BOS` starts a candidate. CHoCH does not substitute for the
   continuation BOS.
3. **VWAP mode.** Configuration must select `FULL_DAY`, `MORNING`, or `AFTERNOON` before
   replay. Morning/afternoon VWAP is eligible only in its matching continuous session.
   Missing or zero-volume VWAP is unavailable and rejects the setup.
4. **VWAP slope.** A versioned rule supplies a positive integer
   `lookback_closed_1m_events`. At time `T`, slope is
   `(VWAP[T] - VWAP[T-N]) / N`, using same-symbol, same-date, same-mode snapshots and only
   released closed events. Long requires slope strictly greater than zero; short strictly
   less; equality fails. `N`, rule ID, parameter-set ID, and calibration provenance are
   mandatory and have no shipped default.
5. **Price/VWAP alignment.** At the eventual trigger close, long close must be strictly
   above the selected VWAP and short strictly below. The slope condition must also still
   pass at that trigger.
6. **Pullback zone.** Select the zone by section 3, including its exact link to the 5-minute
   BOS impulse. It must be `ACTIVE` immediately before its first pullback touch.
7. **Mitigation.** On first and subsequent causally released touches before trigger, define
   penetration fraction for a zone `[lower, upper]`:
   - long: `(upper - minimum_low_since_first_touch) / (upper - lower)`;
   - short: `(maximum_high_since_first_touch - lower) / (upper - lower)`.
   Clamp only for representation to `[0, 1]`; a close beyond the far boundary invalidates.
   A configured `maximum_mitigation_fraction` in `[0, 1)` must exist and the observed
   fraction must be no greater. The value and provenance are research inputs; none is
   supplied here.
8. **Micro trigger.** After first zone touch, the earliest same-direction closed 1-minute
   BOS or CHoCH is the trigger. Its confirming close must be strictly beyond its recorded
   broken micro-structure price, which the existing structure event already proves. No
   second discretionary trigger candle is added.
9. **Extension.** Record directional trigger-close distance above/below VWAP in points and
   verified ticks. A configured versioned extension rule must choose either a maximum tick
   distance or a causally computed ATR-normalized distance. Missing rule/value or missing
   causal ATR rejects the setup. There is no default.
10. **Entry reference.** `TradeProposal.entry_price` is the 1-minute micro-trigger close,
    not an asserted fill.
11. **Initial stop.** Long stop anchor is the selected zone lower bound; short is its upper
    bound. No buffer is added. A stop not strictly protective relative to entry rejects.
12. **Target.** At trigger confirmation, select the nearest same-symbol opposing liquidity
    level whose `confirmed_at <= trigger.confirmed_at`, whose state is still active/unswept,
    and whose price is strictly beyond entry: high-side for long, low-side for short.
    Minimize absolute price distance and break equal-price/identity ties by ascending level
    ID. If none exists, no proposal. This price is the fixed target for V1 and is passed to
    cost-adjusted RRR.
13. **Invalidation before proposal.** Invalidate if the 15-minute regime ceases to be the
    required state, an opposite 5-minute CHoCH confirms, the zone closes beyond its far
    boundary or otherwise becomes terminal, VWAP alignment/slope fails at trigger,
    mitigation/extension fails or is uncalibrated, data identity/quality fails, or the
    continuous session ends.
14. **Times.** Proposal `event_time` and `confirmed_at` are the micro-trigger bar event and
    close. Record the 15-minute state, 5-minute BOS, VWAP snapshots/rule, zone, touch,
    mitigation, trigger, extension, target-level, and parameter IDs.

Stable pre-proposal rejection codes must cover at least:

```text
HTF_STRUCTURE_NOT_ELIGIBLE
FIVE_MINUTE_BOS_MISSING
VWAP_MODE_UNCONFIGURED
VWAP_UNAVAILABLE
VWAP_ALIGNMENT_FAILED
VWAP_SLOPE_UNCALIBRATED
VWAP_SLOPE_FAILED
NO_IMPULSE_ZONE
ZONE_NOT_FRESH
MITIGATION_UNCALIBRATED
MITIGATION_EXCEEDED
MICRO_TRIGGER_MISSING
EXTENSION_UNCALIBRATED
EXTENSION_EXCEEDED
OPPOSING_LIQUIDITY_MISSING
STOP_SIDE_INVALID
DATA_QUALITY_REJECTED
SETUP_SESSION_EXPIRED
```

### Rejected alternatives

- Reading a forming 15-minute state or forming 5-minute BOS.
- Computing slope with a hidden window or whole-session future values.
- Choosing the VWAP mode, zone type, or parameter after observing the trade.
- Calling any touched historical zone “fresh.”
- Picking the most profitable later liquidity target.
- Adding an arbitrary ATR stop buffer.

### Causal/non-repaint implications

The 15-minute state, 5-minute BOS, zone, touch, VWAP history, and 1-minute trigger must all
be known at the trigger close. Later higher-timeframe or zone changes cannot backdate the
proposal.

### Parameters and alpha assumptions

VWAP mode, slope lookback, zone type/timeframe, mitigation limit, extension representation
and limit, minimum RRR, and any volume/spread/roll filters are declared research inputs.
The continuation sequence, zone-boundary stop, and nearest opposing-liquidity target are
versioned alpha hypotheses, not validation results.

**Decision: `LOCK_NOW` for V1 mechanics; `DEFER_TO_RESEARCH` for choices and values.**

## 6. Entry confirmation and eligibility

### Repository evidence and ambiguity

The specification says bar-close signals become executable on a later event. Existing
`TradeProposal` has `event_time`, `confirmed_at`, and `entry_price` but no separate
`entry_eligible_at` field.

### Locked rule

At TFEX-4, `entry_eligible_at` is a derived semantic equal to
`TradeProposal.confirmed_at`: the first instant risk evaluation may occur. It is not stored
as a duplicate field. The entry price is the confirming trigger close and remains a planned
risk reference. TFEX-5 owns `ResearchOrderIntent.eligible_after`, order kinds, price
revalidation, and next-event execution.

### Rejected alternatives

Same-close fill, entry eligibility before every dependency confirms, or duplicating the
existing time fields with inconsistent values.

### Causality, parameters, alpha, decision

This is mechanical execution timing, has no configurable numeric value, and introduces no
alpha claim. **Decision: `LOCK_NOW`.**

## 7. Stop and exit contract

### Repository evidence

The risk contract rejects a proposal without a strictly protective initial stop and without
a fixed target or deterministic exit rule. It supports fixed-R, structure, VWAP,
partial-plus-runner, structure trail, ATR trail, time, session, and EOD behavior as declared
research variants; it does not impose universal 1:2 reward/risk.

### Locked rule

- Strategy A anchors its stop to the sweep-bar extreme.
- Strategy B anchors its stop to the selected zone's adverse/far boundary.
- Stops are exact price anchors with no implicit tick or ATR buffer.
- Every proposal identifies one versioned exit family selected before replay.
- Strategy B V1 uses nearest eligible opposing liquidity as its fixed target.
- Strategy A may use opposing liquidity, structural target, VWAP target, fixed-R,
  partial-plus-runner, structure trail, ATR trail, or time stop only as a separately
  declared research variant.
- A fixed-price family must resolve its price causally before proposal emission. A non-target
  family must serialize deterministic rules and carry predeclared expectancy evidence.
- Session exit and mandatory EOD flatten remain present in every exit plan. TFEX-4 defines
  the plan only; TFEX-5 implements execution and management.

### Rejected alternatives

Missing stop/exit, production RRR default, arbitrary ATR buffer, invented target, later
best-target selection, or widening a stop after approval.

### Causality, parameters, and alpha

Target/exit family, fixed-R value, trail inputs, expectancy, and RRR are research choices.
The anchor rules and causal resolution are locked strategy hypotheses.

**Decision: `LOCK_NOW` for anchors and exit shape; `DEFER_TO_RESEARCH` for family/value.**

## 8. Setup scoring semantics

### Repository evidence

TFEX-4 requires transparent setup scoring. TFEX-3 intentionally provides feature vectors
and a partial order without weights. The research protocol says the repository has no daily
ranking score and treats all-qualified versus best-only as a predeclared future comparison.

### Ambiguity

No score weights, source hierarchy, total scale, cutoff, or tie policy has validated
authority.

### Locked rule

The initial score is explanatory metadata only. It is an ordered immutable feature vector,
not a numeric admission gate. Each component records:

```text
component_id
status = PASS | FAIL | UNAVAILABLE | UNCALIBRATED
raw_value and units
source artifact IDs
event_time
confirmed_at
parameter/rule ID when applicable
```

Components are sorted by stable `component_id`; identical evidence produces byte-identical
representation. Hard strategy qualification is a separate conjunction of mandatory rules.
A failed hard rule cannot be repaired by confluence points.

Strategy A may expose the preferred confluences in section 17 as components. Strategy B
may expose structure, VWAP, zone, mitigation, extension, volume/spread, and roll evidence.
Unavailable or uncalibrated inputs remain explicitly visible.

A numeric total is `None` unless a versioned, provenance-bearing `RESEARCH_ONLY` weight set
was declared before replay. Even then it is research metadata and cannot affect admission
until a separately reviewed rule explicitly authorizes it. Best-setup-only selection is a
distinct research trial, never the default runtime behavior.

### Rejected alternatives

Arbitrary equal/weighted sums, enum-order ranking, hidden normalization, converting missing
features to zero, or choosing only the day's later winner.

### Causality, parameters, and alpha

Every component must be confirmed by setup time. Weights, cutoffs, bands, and ranking are
alpha assumptions and remain uncalibrated.

**Decision: `LOCK_NOW` for the explanatory vector; `DEFER_TO_RESEARCH` for totals/ranking.**

## 9. TradeProposal boundary

### Repository evidence

`risk/models.py` already defines the frozen, extra-forbidden canonical `TradeProposal`.
`StrategyProposalSource` returns `TradeProposal | None`; `RiskEngine` receives the proposal
plus a separate `StrategyRiskRule`, cost assumptions, and risk context.

### Locked rule

Strategy A/B populate the existing fields exactly:

- `proposal_id`: deterministic from setup ID and trigger confirmation;
- `strategy_id` and `setup_id`: versioned identities;
- `symbol`: normalized raw contract;
- `side`: `LONG` or `SHORT`;
- `event_time` and `confirmed_at`: section 2/6 semantics;
- `entry_price`: trigger-close reference;
- `initial_stop_price`: section 7 anchor;
- `exit_plan`: fixed target and/or versioned deterministic rules;
- `estimated_expectancy_r`: only when supplied by permitted predeclared research evidence;
- `rationale_inputs`: score components, gate-independent raw evidence, rule/parameter IDs,
  and the derived risk-eligibility instant;
- `source_signal_ids`: every level, sweep, structure, zone, VWAP/target source ID; and
- `live_order_requested`: always `false`.

The strategy-specific `research_rule_id` stays in the separate `StrategyRiskRule`; the risk
engine verifies matching `strategy_id`, and `ApprovedTradePlan` retains the rule ID. It is
not duplicated into `TradeProposal`.

The public strategy result remains `TradeProposal | None`. A separate immutable strategy
evaluation/audit record must retain ordered rejection codes and input evidence when the
result is `None`; that record is not an order or alternate proposal and cannot enter risk.

Strategies must not populate or choose quantity, allowed risk, approval, broker order type,
fill price, order/fill IDs, or any live action.

### Rejected alternatives, causality, parameters, alpha

Do not duplicate the proposal model, embed quantity, hide rejected setups, or claim the
reference price is a fill. Field mapping is mechanical; strategy evidence remains the
declared hypothesis. **Decision: `LOCK_NOW`.**

## 10. Pre-trade gate composition

### Repository evidence

The contract registry owns raw-contract eligibility. `SessionEngine` owns calendar,
expiry-context, session, cutoff, flatten-time, and data-quality entry evidence. The future
margin service is fail-closed. `RiskEngine` owns kill triggers, costs, RRR/expectancy,
loss capacity, and quantity. The approved plan is the only future execution-admissible
object.

### Locked rule

Evaluate one proposal at one aware `evaluated_at` in this stable order:

```text
1. proposal schema, identity, confirmation, and duplicate check
2. ContractRegistry eligibility
3. contract-specific expiry/LTD gate
4. SessionEngine time/session gate
5. market-data, sequence, metadata, and mode-aware health gate
6. resolve as-of margin records and free-equity evidence; reject unknown/stale/conflicting
   evidence, but do not derive quantity here
7. kill-switch evaluation
8. RiskEngine stop/cost/RRR/expectancy/loss-capacity sizing, followed atomically by the
   quantity-dependent total-post-trade-margin/free-equity capacity check
9. RiskDecision; ApprovedTradePlan only when every gate and the capacity check approve
```

Every gate emits immutable typed evidence and stable rejection codes. Reasons accumulate in
the order above rather than allowing a later gate to conceal an earlier failure. A malformed
proposal may terminate safely because later evaluation lacks trustworthy identity. Any
missing, stale, contradictory, not-applicable-in-this-mode, or uncalibrated required input
denies approval. `RiskEngine` will require a future typed composition input rather than
having callers convert rejected gates to optimistic booleans.

No strategy calls the registry, risk engine, margin service, broker, or Settrade directly.
An orchestration layer performs this composition after proposal emission.

### Rejected alternatives

Calling risk before contract/session/margin evidence exists, short-circuiting away audit
reasons, allowing strategy-specific bypasses, or constructing a plan outside `RiskEngine`.

### Causality, parameters, alpha, decision

Step 6 is the pre-sizing margin gate named by the canonical flow: it proves that applicable
margin and free-equity evidence exists and is usable. It cannot approve capacity before a
quantity exists. Step 8 first computes the risk-limited candidate quantity and then applies
the total-post-trade portfolio test in section 12 without increasing that quantity. No
`ApprovedTradePlan` exists between those operations. All lookups are as-of `evaluated_at`;
historical records cannot use later metadata or margin. The order is safety architecture,
not alpha. **Decision: `LOCK_NOW`.**

## 11. Research-mode operational health

### Repository evidence and ambiguity

Current `RiskContext` uses booleans for feed connection, broker health, and reconciliation
and defaults them unhealthy. Tests sometimes set them `true` to isolate risk arithmetic.
Historical replay has no broker or broker reconciliation, so setting those values `true`
would fabricate evidence, while leaving them false would make every historical research
proposal indistinguishable from an operational failure.

### Locked rule

Future composition must represent each health dimension with an explicit status, mode,
observation time, and source ID. Required statuses are:

```text
VERIFIED_HEALTHY
VERIFIED_UNHEALTHY
HISTORICAL_SEQUENCE_VALIDATED
NOT_APPLICABLE_RESEARCH
UNKNOWN
```

- Historical research declares `HISTORICAL_REPLAY`. Market-data health may be
  `HISTORICAL_SEQUENCE_VALIDATED` only when validator, checksum, monotonic sequence, and
  replay integrity pass. Broker API and reconciliation are `NOT_APPLICABLE_RESEARCH`, never
  `VERIFIED_HEALTHY`. No broker/account exposure may be inferred.
- Historical daily P&L, positions, execution errors, and costs must cite an explicit
  deterministic research ledger/model. Unknown required values fail the research decision.
- Forward/paper modes require observed feed, broker, account, and reconciliation evidence;
  `NOT_APPLICABLE_RESEARCH` is not admissible.
- Production remains unsupported. `UNKNOWN` or `VERIFIED_UNHEALTHY` always fails closed.
- Manual disable and uncalibrated risk-policy triggers remain applicable in every mode.

Current booleans cannot express this distinction. A future backward-compatible typed
extension to `RiskContext` is required before TFEX-4 historical orchestration may approve a
research proposal. Tests that set booleans healthy remain isolated unit fixtures and are
not evidence of operational health.

### Rejected alternatives, causality, parameters, alpha

Do not fake a nonexistent broker as healthy, disable kill checks silently, or reuse current
wall-clock freshness for historical events. These are evidence semantics, not tunable alpha.
**Decision: `LOCK_NOW`.**

## 12. Margin service contract

### Repository evidence

`CLAUDE_TFEX.md` section 22 requires a versioned provider and the stricter of official,
broker-reported, and configured safety margin. Margin changes cannot be applied
retroactively. Current margin modules are empty placeholders and both official margin
sources remain unverified.

### Ambiguity resolved

The canonical sources require sufficient margin and a free-equity reserve but did not say
whether that reserve was tested against only the new trade's incremental margin or against
the whole portfolio after the proposed trade. Incremental-only evidence could approve a
trade even when existing exposure plus the new exposure consumes the required reserve.

### Locked rule

An immutable margin record must contain at least:

```text
record_id and schema/version
contract_family and optional exact raw symbol/series
position_kind = OUTRIGHT | SPREAD
initial_margin_thb_per_contract
maintenance_margin_thb_per_contract when published
force_close_margin_thb_per_contract when published
effective_from (aware)
source_kind = OFFICIAL_REFERENCE | BROKER_REPORTED | CONFIGURED_SAFETY |
              RESEARCH_ASSUMPTION
source/provenance ID and source checksum where applicable
retrieved_at (aware)
verification/status
stale_after (aware)
broker override identity when applicable, without account secrets
research scenario/assumption ID when applicable
```

As-of lookup uses only records with `effective_from <= as_of`, chooses the latest applicable
record within each source kind, and derives the end of an older record from the next
effective record. It never edits history. Exact-symbol records take precedence over a
family record only within the same source kind; the choice and all candidates remain in the
decision evidence.

For every available margin field, the effective requirement is the maximum—the stricter
value—across applicable official/reference, broker-reported, and configured safety records.
No source is silently converted into another. Unknown, conflicting, or stale required
production/paper margin rejects. A historical research run may use a complete
`RESEARCH_ASSUMPTION` record only when its research plan and scenario were declared before
the run; the result remains research-only and cannot establish an actual margin rate.

The pre-sizing margin gate resolves an explicit `free_equity_before_trade` evidence record
and all applicable margin records. For a risk-derived candidate quantity `q`:

```text
existing_open_exposure_margin =
    sum(as_of_stricter_of_margin_requirement for every existing open exposure)

proposed_trade_margin(q) =
    as_of_stricter_of_margin_requirement_per_contract * q

total_post_trade_margin_requirement(q) =
    existing_open_exposure_margin + proposed_trade_margin(q)

free_equity_before_trade - total_post_trade_margin_requirement(q)
    >= required_free_equity_buffer
```

Every monetary term is expressed in THB with explicit observation/as-of time and
provenance. Existing exposure and proposed exposure use the canonical exact-symbol/family,
source, as-of, and stricter-of rules independently. Incremental proposed-trade margin alone
is never sufficient evidence.

Risk sizing remains authoritative. Let `q_risk` be the candidate produced by the existing
risk equations. The margin policy may never increase it or create an independent sizing
algorithm:

1. Evaluate the total-post-trade condition for `q_risk`.
2. If it passes, retain `q_risk`.
3. If it fails and quantity reduction is implemented inside the canonical `RiskEngine`,
   choose the greatest whole-contract `q` in `[1, q_risk - 1]` that passes. This is a
   deterministic constraint on the risk-sized candidate set, not margin-only sizing.
4. If no positive quantity passes, or if the current engine does not support that reduction,
   reject. Never round up.

The current dormant `RiskEngine` has no margin input or margin-reduction path, so this lock
does not claim that reduction is implemented. Future code must keep sizing and this
constraint atomic: no `RiskDecision.APPROVED` or `ApprovedTradePlan` may exist until the
final quantity passes.

`required_free_equity_buffer` remains `UNCALIBRATED`. No percentage, THB value,
maintenance-margin haircut, broker margin value, or risk threshold is supplied by this
document. The legacy `MarginConfig.free_equity_buffer_multiplier = 2.0` is already labelled
as a research default; it is not silently promoted or reinterpreted as a calibrated or
production `required_free_equity_buffer`. A future versioned calibration and explicit
mapping are required before it can participate in this gate.

Unknown, stale, conflicting, or unavailable margin/free-equity evidence fails closed in
production. Historical research never fabricates live account equity. It may use only an
explicitly predeclared, versioned `RESEARCH_ASSUMPTION` account-equity scenario, represented
under section 11's research-health semantics; that evidence cannot establish production
account health or production eligibility.

### Rejected alternatives

Incremental-margin-only approval; one mutable current number; retroactive use; stale
fallback; treating a research assumption as official/broker truth; hiding source
disagreement; deriving an independent quantity from collateral; or using the legacy `2.0`
research default as production truth.

### Causality, parameters, alpha, decision

Margin values, safety records, and buffer calibration are external dynamic/risk inputs, not
alpha. **Decision: `LOCK_NOW` for records, as-of/stricter-of/fail-closed semantics, and the
total-post-trade portfolio formula; `DEFER_TO_RESEARCH` / operational calibration for the
numeric `required_free_equity_buffer`.**

## 13. Cost and risk semantics

### Locked rule

- SET50 multiplier remains THB 200 per point per contract, with 0.1-point tick and THB 20
  tick value from verified configuration.
- Preserve the existing Decimal risk and quantity equations, round-trip costs, adverse
  slippage, buffer, daily capacities, total exposure, and floor-to-whole-contract behavior.
- THB 7 per contract per side remains a verified exchange fee cap and is never an actual
  production charge. It may appear only in a clearly labelled conservative research stress
  scenario.
- Broker commission, actual exchange charge, spread, and slippage retain provenance and
  remain unknown until evidenced.
- Research numeric costs use status `RESEARCH_ASSUMPTION` conceptually; the current cost
  model's corresponding persisted provenance status must remain explicitly non-production.
- Missing costs, risk thresholds, or strategy-specific RRR/expectancy fail closed.

### Rejected alternatives, causality, parameters, alpha

No margin-only sizing, round-up, omitted cost, fee-cap promotion, or production default.
Risk limits and research costs require calibration/provenance but do not define strategy
alpha. **Decision: `LOCK_NOW` for mechanics; `DEFER_TO_RESEARCH` for numeric values.**

## 14. Research prerequisite decision

### Repository evidence and ambiguity

The research protocol section 18 requires an adequate real-data history, declared
chronological partitions/search spaces, labelled costs, calibrated and reviewed acceptance
thresholds, and explicit authorization before strategy implementation. Its evidence ladder
then requires implemented strategy output to produce backtest and later evidence.

### Locked rule

`BACKTEST_EVIDENCE` is not required before deterministic code can exist; that would be
temporally impossible. Before code begins, however, all governance prerequisites in
protocol section 18 still apply. Code initially has research state `RESEARCH_ONLY`.

After implementation:

```text
TFEX4_COMPLETE + RESEARCH_ONLY
    -> separately generated BACKTEST_EVIDENCE
    -> WALK_FORWARD_EVIDENCE
    -> HOLDOUT_EVIDENCE
    -> later live-arriving forward/paper evidence
```

Milestone completion cannot promote the evidence state. Evidence cannot repair missing
implementation correctness. Neither authorizes execution.

### Rejected alternatives, causality, parameters, alpha

Do not require results before code, call unit tests backtests, tune on the final holdout, or
use milestone status as a profitability label. Research choices remain predeclared and
causal. **Decision: `LOCK_NOW`.**

## 15. TFEX-4 completion boundary

TFEX-4 may move to `TFEX4_COMPLETE` only when all of the following are implemented and
tested without weakening prior acceptance:

- deterministic Strategy A and Strategy B state machines;
- explanatory scoring vector and uncalibrated-weight isolation;
- canonical `TradeProposal | None` output and rejected-setup audit evidence;
- contract, expiry, session, data/health, margin, kill, and risk composition;
- point-value/cost-aware sizing through `RiskEngine`;
- versioned margin record/history/provider and fail-closed gate;
- no direct execution/broker/Settrade dependency;
- exact batch/incremental equivalence, prefix stability, future-mutation stability,
  restart stability, closed-HTF isolation, and immutable confirmed outputs;
- full TFEX, anti-repaint, lint, format, and type checks passing; and
- a five-day real S50U26 smoke run proving data-shape compatibility and causal stability.

The smoke run may legitimately yield rejections because risk, strategy, cost, margin, or
health parameters remain uncalibrated. Tests must distinguish correct fail-closed rejection
from a strategy implementation failure.

`TFEX4_COMPLETE` explicitly does not mean profitable, strategy-validated, parameter-
calibrated, paper-ready, realtime-ready, operationally proven, live-ready, or authorized to
trade. Strategy evidence may remain `RESEARCH_ONLY`.

**Decision: `LOCK_NOW`.**

## 16. Current data sufficiency

The immutable S50U26 1-minute dataset contains 1,775 real bars across five complete trading
days. It is sufficient for data-shape integration, deterministic fixture-to-real
compatibility, a preliminary real-data smoke run, and causal/non-repaint checks.

It is not sufficient for reliable calibration, multiple-regime/expiry/roll coverage,
walk-forward folds, untouched holdout evidence, profitability claims, or robust parameter
selection. Using it to develop or inspect a strategy assigns it to development/calibration;
it cannot then be presented as untouched validation or holdout data.

**Decision: `LOCK_NOW`.**

## 17. Strategy C / Opening Range Breakout

ORB is outside the initial TFEX-4 implementation and remains disabled until Strategies A
and B progress through the separately governed validation path. ORB-named fixtures in risk
tests prove generic contract behavior only and do not implement, activate, or validate the
strategy.

**Decision: `DEFER_TO_RESEARCH` and a separately authorized later milestone.**

## 18. Mandatory future test contract

### Strategy A

- liquidity level is unavailable before confirmation;
- wick/touch/exceed without closed reclaim never creates a sweep setup;
- CHoCH must confirm strictly after the sweep;
- retest and micro-break modes are predeclared and mechanically distinct;
- same-type nearest zone selection and ID tie-break are deterministic;
- cross-type selection cannot occur without a declared variant;
- stop equals the recorded sweep extreme and is strictly protective;
- no proposal exists before every required confirmation and exit rule;
- session expiry, invalidation, and rejection reasons are stable;
- batch/incremental, restart, prefix, and future-mutation results match.

### Strategy B

- only closed 15-minute bullish/bearish structure qualifies;
- only a confirmed same-direction 5-minute BOS starts the setup;
- selected VWAP and slope use only released snapshots and declared lookback;
- missing/zero-volume VWAP and uncalibrated slope reject;
- zone-to-BOS linkage, freshness, selection, and mitigation are deterministic;
- forming HTF state and future zone revisions cannot leak;
- micro trigger occurs only after pullback touch;
- extension and target selection use only causal evidence;
- stop equals the selected far boundary and is strictly protective;
- batch/incremental, restart, prefix, and future-mutation results match.

### Scoring

- identical evidence yields identical ordered representation;
- no future/unconfirmed feature appears;
- unavailable and uncalibrated differ from zero/failed;
- no uncalibrated weight or total changes qualification/admission;
- best-only selection cannot happen without a predeclared research comparison.

### Risk and gates

- unknown, conflicting, or stale margin fails closed;
- as-of margin lookup does not apply later changes retroactively;
- stricter-of source selection is preserved with provenance;
- research assumptions cannot pass as paper/production records;
- expiry, wrong session, data-quality, health, manual-disable, and kill conditions reject;
- `NOT_APPLICABLE_RESEARCH` is never fabricated as healthy;
- strategies cannot bypass `RiskEngine` or construct `ApprovedTradePlan`;
- `TradeProposal` contains no quantity/order/fill field;
- no TFEX-4 source imports a broker or Settrade order surface.

## 19. Decision register

| Item | Classification |
| --- | --- |
| Strategy A 1m closed sweep/reclaim and mandatory later 1m CHoCH | `LOCK_NOW` |
| Strategy A retest and micro-break mechanical definitions | `LOCK_NOW` |
| Strategy A choice of retest versus micro-break | `DEFER_TO_RESEARCH` |
| Strategy A entry reference at trigger close | `LOCK_NOW` |
| Strategy A stop at sweep extreme | `LOCK_NOW` |
| Strategy A exit contract shape | `LOCK_NOW` |
| Strategy A exit family/value and RRR/expectancy | `DEFER_TO_RESEARCH` |
| Same-type nearest-on-pullback zone selection with ID tie-break | `LOCK_NOW` |
| FVG versus Order Block and zone timeframe | `DEFER_TO_RESEARCH` |
| Strategy B closed 15m state and confirmed 5m BOS | `LOCK_NOW` |
| Strategy B VWAP mode interface | `LOCK_NOW` |
| Strategy B selected VWAP mode | `DEFER_TO_RESEARCH` |
| VWAP slope formula and provenance interface | `LOCK_NOW` |
| VWAP slope lookback | `DEFER_TO_RESEARCH` |
| Zone freshness and mitigation representation | `LOCK_NOW` |
| Maximum mitigation fraction | `DEFER_TO_RESEARCH` |
| Strategy B post-touch 1m BOS/CHoCH trigger | `LOCK_NOW` |
| Extension representation/interface | `LOCK_NOW` |
| Extension mode and maximum | `DEFER_TO_RESEARCH` |
| Strategy B stop at zone far boundary | `LOCK_NOW` |
| Nearest confirmed opposing-liquidity target | `LOCK_NOW` |
| Minimum cost-adjusted RRR | `DEFER_TO_RESEARCH` |
| Explanatory score vector | `LOCK_NOW` |
| Numeric weights, cutoff, score bands, and daily ranking | `DEFER_TO_RESEARCH` |
| Explicit research-mode health statuses | `LOCK_NOW` |
| Orders, fills, position runtime, and exit execution | `DEFER_TO_TFEX5` |
| Margin records, as-of lookup, stricter-of, and stale behavior | `LOCK_NOW` |
| Total-post-trade portfolio margin free-equity formula | `LOCK_NOW` |
| Numeric `required_free_equity_buffer` | `DEFER_TO_RESEARCH` / operational calibration |
| Implementation status versus research evidence status | `LOCK_NOW` |
| TFEX-4 completion meaning | `LOCK_NOW` |
| ORB implementation | `DEFER_TO_RESEARCH` / later authorization |

## 20. Preconditions to begin implementation

This definition lock alone does not authorize TFEX-4. Before runtime strategy code begins,
the research protocol still requires:

- adequate licensed history for declared development/validation/holdout partitions;
- declared Strategy A/B parameter, zone, trigger, filter, stop, and exit search spaces;
- explicit research cost scenarios or actual broker fee evidence;
- calibrated and reviewed performance, risk, and robustness acceptance thresholds;
- a versioned, reviewed numeric `required_free_equity_buffer` and explicit mapping of any
  legacy research-default field; and
- explicit user authorization to start TFEX-4.

Until then the final state is:

```text
TFEX-2 = TFEX2_COMPLETE
TFEX-3 = TFEX3_COMPLETE
TFEX-4 = TFEX4_NOT_STARTED
strategy evidence = RESEARCH_ONLY
live_orders_enabled = false
```
