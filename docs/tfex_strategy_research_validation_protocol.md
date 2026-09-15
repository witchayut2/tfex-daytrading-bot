# TFEX Strategy Research and Validation Protocol

Status: **LOCKED PROTOCOL / DETERMINISTIC TEST SCAFFOLDING ONLY**

This is the canonical contract for future TFEX strategy research, backtests,
walk-forward evaluation, final holdout evaluation, forward tests, paper trading, and
strategy acceptance. It does not start TFEX-2, implement a strategy, select production
parameters, calibrate an acceptance threshold, or authorize an order.

Read this with `CLAUDE.md`, `CLAUDE_TFEX.md`, `docs/tfex_architecture.md`,
`docs/tfex_data_readiness_gate.md`, and
`docs/tfex_risk_order_position_contract.md`. The finite R4 procedure is canonical in
`docs/tfex4_research_plan.md`. The current real S50U26 1-minute dataset
contains five complete trading days and satisfies the data-readiness gate. Current decision:
`READY_FOR_TFEX2`. TFEX-2 and TFEX-3 neutral market analysis are complete, but no strategy
analysis or parameter research has started.

## 1. What is locked, and what is not implemented

The repository now has immutable schemas and pure validation operations for:

- chronological research partitions and their dataset provenance;
- single-use final holdouts;
- anchored and rolling walk-forward fold records;
- causal feature, confirmation, and decision-time boundaries;
- immutable signal history;
- explicit research cost and cost-sensitivity assumptions;
- complete metrics and deterministic subgroup-reporting shapes;
- declared parameter searches and append-only trial/result history;
- independent Strategy A, B, and C reports;
- predeclared all-qualified versus best-setup-only comparisons;
- execution eligibility after an `ApprovedTradePlan`;
- historical, forward, paper, and operational evidence distinctions; and
- fail-closed strategy-acceptance states.

This protocol itself contains no replay or indicator engine. Elsewhere, TFEX-2 replay and
TFEX-3 neutral analysis exist; there is still no strategy logic, optimizer, parameter
selection, total ranking score, fill simulator, broker adapter, execution
transport, or runtime activation. Numerical performance and risk thresholds remain
`UNCALIBRATED`.

## 2. Evidence lifecycle

Evidence must move in one direction:

```text
research hypothesis and declared search space
    -> development/calibration backtests
    -> chronological validation
    -> walk-forward evidence
    -> one untouched final holdout evaluation
    -> live-arriving forward test
    -> live-arriving paper trading
    -> operational proving
    -> LIVE_CANDIDATE consideration
```

A later stage cannot repair a missing earlier stage. Good aggregate P&L does not override
bad provenance, leakage, omitted costs, a narrow parameter optimum, a risk-engine bypass,
or a failed subgroup. `LIVE_CANDIDATE` is an evidence label, not permission to trade live;
`live_orders_enabled` remains false.

## 3. Chronological data partitions

Every research plan declares four half-open, timezone-aware partitions before evaluation:

| Partition | Purpose | Permitted use |
| --- | --- | --- |
| A - development/calibration | Develop logic and select parameters | Iteration is allowed and every trial is logged |
| B - validation | Evaluate choices made in A | No tuning on B results without redefining the experiment and burning the old validation claim |
| C - untouched final holdout | One final unbiased evaluation | One access only; tuning or diagnostic inspection burns it |
| D - forward/paper | Observe live-arriving data | No historical reconstruction or hindsight recomputation |

Rules:

1. Splits are chronological only. Random shuffles and stratified random splits are not
   representable by the contract.
2. Boundaries must be persisted with partition ID, dataset ID, normalized-file SHA-256,
   source, raw symbol, interval, source timezone, normalized timezone, and synthetic flag.
3. Partitions cannot overlap and must appear in A, B, C, D order.
4. One plan preserves one raw contract identity. It cannot splice S50U26 and S50Z26.
5. A continuous contract is prohibited for acceptance evidence. A future derived continuous
   series may be used only for clearly labelled research with explicit roll metadata.
6. Synthetic fixtures may test code and faults, but cannot satisfy real-market acceptance.
7. No calendar dates or split ratios are selected here. They must be justified after enough
   licensed real history exists and declared before trials run.

### Holdout burning

The final holdout starts `UNTOUCHED`. A single declared final evaluation changes it to
`CONSUMED_FINAL_EVALUATION`. Any tuning or diagnostic inspection changes it to
`BURNED_FOR_TUNING`. Neither state can be accessed again. If results from C influence a
feature, filter, parameter, stop, exit, cost choice, or strategy narrative, C is burned and
a new untouched future period is required.

## 4. Walk-forward protocol

Both common deterministic forms are supported, but this protocol does not choose one for
production:

- **Anchored:** the calibration start remains fixed while its end advances.
- **Rolling:** calibration start and end both advance, using a declared fixed or otherwise
  predeclared window policy.

For every fold, persist:

- fold ID and method;
- calibration start/end and validation start/end;
- parameter-selection timestamp;
- selected parameter-set ID;
- trade count;
- gross P&L, costs, and net P&L;
- expectancy in R;
- maximum drawdown; and
- all rejection reasons.

Calibration must end no later than validation starts. Parameters must be selected inside
the calibration window. Validation windows cannot overlap. Folds are evaluated in time
order. A method comparison is itself a declared experiment; choosing anchored or rolling
because it won on the final holdout is prohibited.

## 5. Lookahead, repaint, and leakage controls

At decision time `T`, a strategy may consume only artifacts whose `confirmed_at <= T`.
Each signal or derived level retains both:

- `event_time`: when the underlying market event occurred; and
- `confirmed_at`: the first time the system could legitimately know the result.

The following are prohibited:

- negative/future shifts such as `shift(-n)`;
- centered rolling windows;
- future-confirmed pivots exposed at pivot event time;
- whole-frame normalization or scaling fitted using validation/holdout/future rows;
- parameters or filters tuned on the final holdout;
- a session high/low used before that value was confirmed;
- a completed signal or level revised after later data arrives;
- future extrema used to label a past trading decision; and
- any replay result that changes when only future input is mutated.

Allowed normalization scopes are expanding past-only or calibration-window-only. Confirmed
history is append-only by artifact ID and content checksum. TFEX-2/TFEX-3 code must prove
prefix stability, replay-versus-incremental equivalence, and no future-index access; these
contracts do not substitute for behavioral anti-repaint tests.

## 6. Execution model contract

All conceptual trade paths are:

```text
TradeProposal -> RiskEngine -> ApprovedTradePlan -> research/paper execution eligibility
```

A strategy does not select quantity and cannot send an order-shaped object around the risk
engine. Research execution admits only a fully revalidated `ApprovedTradePlan`.

Default timing is `NEXT_VALID_EXECUTABLE_EVENT`. A signal is confirmed, then becomes
eligible, then may execute only at a strictly later valid executable event. A same-bar OHLC
fill is rejected because a completed bar does not prove the intra-bar sequence. A future
model may permit same-bar treatment only with specific post-confirmation tick/quote ordering
evidence declared in advance; it may not infer ordering from OHLC.

Market, limit, and stop intents have distinct shapes and fill rule IDs. Partial fills have
their own rule ID. `docs/tfex4_research_plan.md` locks the conservative initial OHLC
behavior for touches, gaps, queue assumptions, trigger ordering, partial fills,
cancellations, and session transitions. No fill simulator exists in this scaffolding.

Every replayed path, including rejections, must retain proposal, risk-decision, approved-plan
or rejection, eligibility, order, partial-fill/fill, protection, management, and exit events.
The locked risk/position contract remains authoritative for stop sizing, RRR or expectancy,
partial protection, break-even, trailing rules, EOD flattening, kill switches, and rejected
trades.

## 7. Costs and slippage

Every research result must include:

- exchange fee assumption;
- broker commission assumption;
- round-trip application (entry and exit);
- adverse slippage per side;
- contract multiplier in THB per point;
- tick size; and
- provenance and immutable cost-model ID.

Unknown numeric components fail closed. Research assumptions are labelled
`RESEARCH_ASSUMPTION`; they are not actual charges. The verified THB 7 exchange figure is a
cap, not the actual broker-account fee. It may be used deliberately in a conservative stress
scenario, but cannot be presented as production accounting. Until actual broker fees are
verified, report baseline and sensitivity scenarios and never label results as real P&L.

Gross P&L, total costs, and net P&L are always separate, with
`net = gross - costs`. A result with costs omitted cannot advance an evidence state.

## 8. Required metrics

Each completed aggregate, fold, strategy, selection-mode, and required subgroup report must
retain, as applicable:

- total trades; wins, losses, and breakevens; win rate;
- average win and average loss;
- expectancy per trade in THB and in R;
- profit factor;
- gross P&L, cost total, and net P&L;
- average and median R;
- maximum drawdown and drawdown duration;
- MAE and MFE;
- maximum consecutive losses;
- chronological daily P&L distribution;
- trades per day and exposure;
- rejected setup count; and
- results under at least two slippage/cost scenarios.

Confidence intervals or uncertainty estimates are recorded only when the method and sample
support them. A small sample is reported as a limitation, not padded with a misleading
interval.

## 9. RRR, exit, and management research

The declared comparison space may include:

- fixed-R targets;
- structure targets;
- VWAP targets;
- partial exit plus runner;
- structure trailing;
- ATR trailing; and
- time-based exits.

Each variant must pass through the same cost, risk, execution, and reporting contracts.
Selection cannot maximize net P&L alone. Compare expectancy, drawdown, stability across
folds and strata, trade count, cost/slippage sensitivity, and nearby parameter behavior.
Management semantics remain those in the risk/position contract: protection cannot be
widened, partial fills remain protected, and deterministic break-even/trailing/EOD/kill
actions are auditable.

## 10. Robustness and parameter neighborhoods

For each important numeric choice, declare distinct lower, center, and upper parameter-set
IDs and evaluate their neighborhood. A broad stable plateau is evidence. A center point that
wins while nearby values collapse is `FRAGILE_NARROW_OPTIMUM` and is rejected from strategy
acceptance, even if its isolated P&L is highest.

No plateau width, P&L, expectancy, drawdown, trade-count, or robustness threshold is set in
this document. Those values remain `UNCALIBRATED` until justified by sufficient real data
and independent review.

## 11. Multiple testing and experiment registry

Before running trials, declare the full searched set of:

- strategy family;
- parameter-set IDs;
- filter variants;
- exit variants; and
- stop variants.

Every trial receives an immutable ID and cites its search, partition plan, parameter set,
filter, exit, stop, cost model, and execution policy. Definitions and terminal results are
append-only. Successful, failed, and rejected trials are retained with reasons. Reusing a
trial ID, overwriting a losing result, or introducing an undeclared winning parameter is an
error.

Reports must disclose the number of strategies, parameter sets, filters, exits, stops, and
selection rules examined. `docs/tfex4_research_plan.md` locks the initial multiplicity
policy as predeclared families, full trial disclosure, and validation confirmation. It
claims no formal p-value correction; any future formal method requires a new preregistered
protocol version before the final holdout.

## 12. Strategy A, B, and C evaluation

Strategies A, B, and C are separate identities and receive independent reports. Do not
combine them merely because combined P&L looks smoother. For each strategy report:

- setup frequency;
- accepted and rejected setup counts;
- expectancy and drawdown;
- morning and afternoon behavior;
- regime and volatility behavior;
- relative-volume behavior; and
- cost/slippage sensitivity.

Portfolio interactions, capital allocation, correlated drawdowns, simultaneous proposals,
and combined risk budgets are later research questions after each strategy establishes its
own evidence.

## 13. Deterministic stratification

Reports include at least these independently visible strata:

- session: `MORNING`, `AFTERNOON`;
- market regime: `TREND`, `RANGE`;
- volatility: `HIGH`, `LOW`; and
- relative volume: `HIGH`, `LOW`.

Every label cites a deterministic, versioned rule known at decision time. Regime thresholds
are calibrated only on permitted past/calibration data. An aggregate result cannot conceal
a persistently losing subgroup; the subgroup remains visible with its sample size and costs.

## 14. All-qualified versus best-setup-only

The repository does not yet implement a daily ranking score. Future research may compare:

1. taking every setup that independently qualifies; and
2. taking only the highest-ranked qualifying setup for the day.

The ranking rule, its input names, and comparison must be declared before evaluation.
Ranking inputs must be available at the decision instant and cannot include later P&L,
MFE/MAE, final session extrema, or holdout outcomes. The two runs use the same partition,
parameters, costs, and execution assumptions and have distinct immutable trial IDs. If no
setup qualifies, the correct result is no trade.

## 15. Forward test and paper trading

Backtests, walk-forward folds, and final holdout evaluation use historical replay.
Forward-test and paper-trading evidence uses data as it arrives, with no hindsight
recomputation. They are distinct modes and records must preserve:

- signal event and confirmation timestamps;
- risk-decision and approved-plan/rejection IDs;
- order creation and fill timestamps when applicable;
- estimated and realized slippage evidence;
- subsequent adverse/favorable movement (MAE/MFE);
- management action IDs; and
- all risk/session/kill-switch rejection reasons.

Forward tests exercise signal behavior without claiming simulated fills are broker fills.
Paper trading exercises the declared paper execution and lifecycle. Operational proving then
tests reconnect, reconciliation, stale data, rejects, partial fills, kill switches, EOD,
expiry, restart, and audit recovery. None of these stages authorizes live trading.

## 16. Fail-closed acceptance states

The only strategy-evidence states are:

| State | Minimum kind of evidence |
| --- | --- |
| `RESEARCH_ONLY` | Hypothesis/scaffolding; no promotion claim |
| `BACKTEST_EVIDENCE` | Validated real raw-contract backtests with registry, costs, risk route, metrics, and robustness |
| `WALK_FORWARD_EVIDENCE` | Prior state plus causal walk-forward folds |
| `HOLDOUT_EVIDENCE` | Prior state plus one untouched final holdout evaluation |
| `PAPER_FORWARD_EVIDENCE` | Prior state plus live-arriving forward and paper evidence |
| `LIVE_CANDIDATE` | Prior state plus operational proving and independently reviewed thresholds |

All prior stages are required. At every stage, real raw-contract data, validator/provenance
checks, risk routing, complete costs, declared searches, retained failed trials, and plateau
evidence are mandatory. Holdout evidence must show a one-time final evaluation, not a burned
holdout. Forward and paper evidence must prove live arrival. Synthetic evidence cannot
promote a real-market state.

The shipped threshold status is `UNCALIBRATED`, so the evaluator returns
`RESEARCH_ONLY`. `LIVE_CANDIDATE` additionally requires independently reviewed thresholds
and operational controls. Even a valid `LIVE_CANDIDATE` object carries
`live_orders_enabled = false`; activation would be a separate future authorization and
milestone.

## 17. Deterministic scaffold map

| File | Responsibility |
| --- | --- |
| `backend/app/tfex/research/models.py` | Immutable partitions, folds, causal artifacts, costs, metrics, registries, execution, paper, and acceptance evidence |
| `backend/app/tfex/research/protocol.py` | Pure holdout, history, registry, execution-eligibility, and fail-closed acceptance operations |
| `backend/tests/tfex/test_research_validation_protocol.py` | Chronology, leakage, holdout, costs, registry, synthetic evidence, and stage tests |
| `backend/tests/tfex/test_research_execution_protocol.py` | Approved-plan boundary, next-event timing, same-bar rejection, and no-order-surface tests |

These files are architecture/test scaffolding. They do not read real data, call Settrade,
write licensed data, or begin any TFEX implementation milestone.

## 18. Pre-code governance and post-code research gates

`docs/tfex4_research_readiness.md` defines the readiness ladder, and
`docs/tfex4_research_plan.md` is the canonical R4 procedure. Deterministic strategy code is
necessary to generate research evidence, so calibrated results are not a pre-code
requirement. The current research-readiness state is `R4_RESEARCH_PLAN_LOCKED`; R5 is not
granted.

Before deterministic Strategy A/B code begins:

1. the existing five-complete-trading-day correctness gate and TFEX-2/3 must remain green;
2. the TFEX-4 definition lock must be complete;
3. data-acquisition and multi-contract segmentation plans must be locked;
4. search dimensions, experiment governance, execution-assumption structure, and
   cost-scenario structure must be declared;
5. unknown numeric values must remain explicit and fail-closed;
6. the final holdout must remain uninspected; and
7. the user must explicitly authorize TFEX-4 implementation.

Code begins with evidence state `RESEARCH_ONLY`. Before parameter search, threshold
selection, walk-forward, holdout access, or promotion, adequate licensed history must be
acquired and validated; actual chronological partitions, finite candidate sets, numeric
cost scenarios, calibration inputs, and complete research-execution rules must be frozen.
Thresholds may then be calibrated only from permitted development/calibration evidence and
must be frozen before later validation stages.

Until those later gates are satisfied, this protocol is `IMPLEMENTED` and `TESTED` as a
contract only. Deterministic implementation does not itself constitute backtest,
walk-forward, holdout, paper, or live-readiness evidence.
