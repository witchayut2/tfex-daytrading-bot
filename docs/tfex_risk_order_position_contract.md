# TFEX Risk, Order, and Position-Management Contract

Status: **ARCHITECTURE LOCKED / DETERMINISTIC UNIT SCAFFOLD TESTED**

This document is the canonical safety contract for future strategy, risk, paper-broker,
and execution work. It does **not** start TFEX-2, TFEX-4, or TFEX-5; it creates no broker
connection and has no order-submission method. The data gate is `READY_FOR_TFEX2`, while
TFEX-2 is complete. This contract remains dormant; TFEX-4 and TFEX-5 are not started.

Read this with `CLAUDE.md`, `CLAUDE_TFEX.md`, `docs/tfex_architecture.md`, and
`docs/tfex_data_readiness_gate.md`. If a future implementation conflicts with this
contract, the implementation must fail closed until the conflict is reviewed.

## 1. Mandatory boundary

```text
closed-bar strategy logic
        |
        v
TradeProposal (quantity-free; never an order)
        |
        v
RiskEngine + session/health/cost evidence
        |
        +----> RiskDecision.REJECTED -> audit only
        |
        v
RiskDecision.APPROVED -> ApprovedTradePlan
        |
        v
future paper/execution adapter (not implemented here)
```

A strategy may only return `TradeProposal | None`. It must not select quantity, call a
broker, construct an order, or bypass `RiskEngine`. A future execution adapter may admit
only an `ApprovedTradePlan`. `ExecutionAdmission` rejects every other shape, including a
`TradeProposal`.

The following future strategies all use the same boundary:

- Liquidity Sweep Reversal
- Trend Continuation Pullback
- Opening Range Breakout (ORB), if later approved

No strategy-specific shortcut is permitted.

## 2. Canonical immutable models

| Model | Required meaning |
| --- | --- |
| `TradeProposal` | Proposal/setup/strategy IDs, raw contract symbol, side, `event_time`, `confirmed_at`, planned entry, initial stop, target or deterministic exit rules, expectancy where applicable, closed-bar rationale inputs, and source signal IDs. It contains no quantity and cannot request a live order. |
| `StrategyRiskRule` | Versioned research rule with that strategy's minimum reward/risk and/or minimum expectancy. It is not a universal hard-coded 1:2 rule. |
| `CostAssumptions` | One-contract round-trip fee/commission estimate, total adverse slippage allowance, extra risk buffer, scenario, and provenance. |
| `RiskContext` | Evaluation time/date, session-entry decision and reasons, daily realized/unrealized P&L, consecutive losses, execution-error count, feed/broker/reconciliation/manual health, and existing-position risk snapshot. Missing session approval denies entry; omitted operational-health evidence defaults unhealthy. |
| `RiskCalculation` | Entry, stop, point distance, THB 200 multiplier, gross price risk, fees, slippage, buffer, allowed risk, calculated quantity, existing and resulting total risk, and reward/RRR or expectancy. |
| `RiskDecision` | Either explicit rejection codes or exactly one calculation plus one `ApprovedTradePlan`; never both. Includes kill-switch state. |
| `ApprovedTradePlan` | The original proposal, calculation, quantity, full-position protective exit, deterministic management rules, and IDs for risk decision, cost assumptions, and strategy rule. |
| `ManagedPosition` | Immutable reducer state, approved plan, planned/filled/exited/open quantities, average entry, current stop, matching protective quantity/status, fills, stop changes, and pending exit reason. |
| `RecoveryExposure` | Unexpected broker exposure. It is never promoted to a normal managed position; all observed quantity is assigned emergency protection and flatten-when-executable state. |
| `TradeAuditRecord` | Proposal, decision, cost assumptions, kill-switch history, contiguous lifecycle events, and resulting position state as one reconstructable JSON-compatible contract. |

Models are frozen and reject unknown fields. Prices and money use `Decimal`; all decision,
fill, and audit timestamps are timezone-aware.

## 3. Non-negotiable entry and protection invariants

1. An entry without an initial stop is rejected.
2. A zero-distance stop is rejected.
3. A long stop must be below entry; a short stop must be above entry.
4. An entry without a target or deterministic exit logic is rejected.
5. An entry without affirmative session-gate evidence is rejected.
6. Quantity is derived from risk; a strategy never proposes lots first.
7. Any filled quantity immediately has the same protective quantity in a named risk state:
   `PENDING_ACK`, `ACTIVE`, `REPLACE_PENDING`, or
   `EMERGENCY_FLATTEN_REQUIRED`.
8. A filled position with a missing stop or mismatched protective quantity is an invalid
   model and cannot be persisted.
9. The resulting protective plan covers the entire resulting position, including any
   permitted pyramid.
10. Overnight is false and EOD flatten is true in both proposed and approved exit plans.
11. No discretionary or LLM decision may occur in the order or position-management path.

There is no exceptional stop-widening policy. Any future exception would require a separate
documented policy, a new explicit configuration type, risk-budget recalculation, audit
fields, and tests. The current/default result is always reject.

## 4. Risk and sizing equations

All values below are evaluated before entry. For SET50 Futures, the multiplier comes from
verified repository configuration:

```text
M = THB 200 / index point / contract
D = abs(entry_price - stop_price)                         # points
P = D * M                                                 # price risk/contract, THB
F = round-trip fees + commissions per contract            # THB, explicit provenance
S = adverse_slippage_allowance_points * M                 # THB/contract
B = additional configured cost/risk buffer                # THB/contract
R_contract = P + F + S + B                                # total estimated risk/contract
```

Loss capacity is fail-closed against all applicable configured limits:

```text
realized_loss = max(0, -daily_realized_pnl)
total_loss = max(0, -(daily_realized_pnl + daily_unrealized_pnl))

allowed_risk = min(
    max_risk_per_trade,
    max_daily_realized_loss - realized_loss,
    max_daily_total_loss - total_loss,
)

available_risk = allowed_risk - existing_position_risk
available_contracts = max_contracts - existing_contracts

contracts = min(
    floor(available_risk / R_contract),
    available_contracts,
)

resulting_total_position_risk = existing_position_risk + contracts * R_contract
```

Every remaining capacity is floored at zero. If one contract cannot fit, the trade is
rejected; quantity is never rounded up. Daily realized-loss, total-loss, and operational
kill thresholds can reject before sizing.

The repository ships these numerical values as `null` with status `UNCALIBRATED`:

- maximum risk per trade
- maximum daily realized loss
- maximum daily total loss
- maximum consecutive losses
- maximum contracts
- minimum acceptable reward/risk
- maximum allowed slippage
- maximum repeated execution errors

All must be deliberately supplied together as `RESEARCH_ONLY` before even the isolated
risk engine can approve a paper/research proposal. No production calibration status or
production default exists.

### Margin/free-equity portfolio constraint

`docs/tfex4_definition_lock.md` closes the margin-basis ambiguity. After the existing risk
equations produce candidate quantity `q_risk`, the final approved quantity `q` must satisfy:

```text
total_post_trade_margin_requirement(q) =
    existing_open_exposure_margin + proposed_trade_margin(q)

free_equity_before_trade - total_post_trade_margin_requirement(q)
    >= required_free_equity_buffer
```

All exposure uses the applicable versioned as-of and stricter-of margin records. The engine
may retain `q_risk`, deterministically choose the greatest passing whole-contract quantity
below it when that reduction is implemented in the same engine, or reject. It may never
increase `q_risk` or use margin as a separate strategy sizing algorithm. Incremental margin
alone is insufficient. The numeric `required_free_equity_buffer` remains `UNCALIBRATED`;
the legacy `2.0` research default is not production evidence. Unknown, stale, conflicting,
or unavailable production account/margin evidence fails closed, and historical research
may use only explicitly labelled predeclared assumptions rather than fabricated live
account equity.

## 5. Reward/risk and expectancy

For a fixed target:

```text
reward_points = abs(target_price - entry_price)
gross_reward_per_contract = reward_points * M
net_reward_per_contract = gross_reward_per_contract - F - S - B
net_reward = contracts * net_reward_per_contract
initial_RRR = net_reward / (contracts * R_contract)
```

The target must be above a long entry or below a short entry. The initial RRR must satisfy
both the global research floor and that strategy's configured minimum. The cost-adjusted
calculation is used; gross reward is preserved separately for audit.

A deterministic non-target exit (for example, time/session logic or a trail) has no honest
fixed reward price. In that case, fixed reward fields remain null and the proposal must
carry predeclared expectancy evidence meeting a strategy-specific minimum expectancy.
Nothing invents a target to manufacture an RRR.

## 6. Stop and exit-management rules

All management decisions identify a rule and serialize its inputs. Permitted deterministic
behaviour is:

| Action | Contract |
| --- | --- |
| Full stop loss | Exit reason `STOP_LOSS`; protection quantity covers all open contracts. |
| Take profit | Fixed target or deterministic strategy rule. |
| Partial take profit | Filled exit reduces open and protective quantities atomically; the remaining stop is `REPLACE_PENDING` until acknowledged. |
| Unchanged stop | New price must equal the current stop. |
| Tightened stop | Long stop may increase; short stop may decrease. |
| Break-even | New stop must equal the actual filled average entry. |
| Lock profit | Stop must cross the filled average entry in the profitable direction. |
| Structure trail | Must include serialized structure inputs and a versioned rule ID. |
| Optional ATR trail | Must be enabled by the future strategy rule and include serialized ATR inputs/rule ID. |
| Time stop | Predeclared deterministic exit rule; no discretionary extension. |
| Session exit | Driven by verified session state. |
| EOD flatten | Mandatory by default and cannot trigger early without the session engine's flatten decision. |

For a long, any requested stop below the current stop widens risk and is rejected. For a
short, any requested stop above the current stop is rejected. A label such as `TIGHTEN` or
`BREAK_EVEN` cannot override the price comparison.

## 7. Partial fills

The reducer rejects duplicate fill IDs and out-of-order recorded times. Future broker work
must add transport-level idempotency and reconciliation around it.

### Partial entry

1. Add the fill to `filled_entry_quantity` and recompute the weighted average entry.
2. Leave the unfilled amount as `planned_entry_quantity - filled_entry_quantity`.
3. Set `protective_quantity` equal to total filled exposure in the same state transition.
4. Mark protection `PENDING_ACK` and lifecycle `PARTIALLY_FILLED`.
5. If protection acknowledgement fails, retain the full protective-risk quantity, disable
   normal management, and enter `EMERGENCY_EXIT_PENDING`.
6. The remainder may only fill under the original approved entry order. If cancelled, its
   quantity remains in history, `entry_order_open` becomes false, and no late fill is
   accepted. Requesting any exit closes the entry remainder first.

### Partial exit

1. Reject an exit fill larger than open exposure.
2. Increase exited quantity and reduce open quantity.
3. Reduce protective quantity to exactly the new open quantity in the same transition.
4. A completed partial-take-profit returns to `MANAGED` with protection
   `REPLACE_PENDING`; a partially filled full-exit order stays `EXIT_PENDING`.
5. Zero remaining quantity becomes `CLOSED` and protection `EXECUTED`.

No fill transition may produce filled exposure with `PLANNED` or `EXECUTED` protection.

## 8. Pyramiding, averaging, and martingale

- Averaging down: prohibited by type/configuration and runtime rejection.
- Martingale: prohibited by type/configuration.
- Adding to a flat or losing position: rejected.
- Pyramiding: disabled by default.

If a research configuration later enables pyramiding, it is only eligible for the same raw
contract and side, only while the existing position is profitable, and only if the new stop
does not widen existing risk. The engine aggregates the existing risk snapshot plus all new
per-contract risk, reapplies the total max-contract and loss-capacity limits, and creates a
protective plan for the entire resulting position. This is a fresh total-position decision,
not an incremental-lot shortcut.

## 9. Kill switch

Triggers are evaluated in a stable order and accumulated so the audit shows every active
cause:

- maximum daily realized loss
- maximum daily realized plus unrealized loss
- maximum consecutive losses
- repeated execution errors
- stale market data
- feed disconnect
- broker/API health failure
- account/position reconciliation mismatch
- emergency manual disable
- uncalibrated/incomplete risk policy

Any active trigger sets `new_entries_allowed = false`. Existing positions are handled
separately:

| Existing exposure | Deterministic action |
| --- | --- |
| None | Block new entries; no position action. |
| Healthy and no trigger | Continue the already approved exit plan. |
| Any kill trigger | Keep all existing protection; request flatten at the next executable opportunity. Never fabricate a fill while closed. |

A kill switch does not cancel protection merely because new entries are disabled.

## 10. Lifecycle and recovery

Normal lifecycle:

```text
SIGNAL_CANDIDATE
  -> RISK_EVALUATION
      -> REJECTED (terminal), or
      -> APPROVED
          -> ENTRY_PENDING
              -> PARTIALLY_FILLED / FILLED
                  -> PROTECTED
                      -> MANAGED
                          -> EXIT_PENDING
                              -> CLOSED
```

Valid self/transitional loops cover additional entry fills, stop replacements, partial exit
fills, and continued exit attempts. `FILLED -> MANAGED` is forbidden: protection must be
acknowledged first.

Recovery states:

- `EMERGENCY_EXIT_PENDING`: protection submission/replacement or a normal exit failed;
  protection covers current exposure while flattening is retried only when executable.
- `RECONCILIATION_BLOCKED`: broker/account state differs from local state; new action is
  blocked until reconciliation, except a conservative emergency flatten path.
- `RecoveryExposure`: restart/reconnection discovers an unexpected position. It requires a
  full emergency protective quantity and flatten-when-executable instruction and can never
  become an ordinary strategy-managed position by assumption.

Near the close, verified `SessionEngine.should_flatten()` evidence triggers `EOD_FLATTEN`.
If the exit fails or connectivity is lost, the existing stop is retained, new entries are
disabled, emergency state is audited, and flattening resumes when the session is executable.
The system never marks an overnight position as acceptable merely because an exit failed.

## 11. Cost provenance

The official THB 7 per contract per side figure remains a verified **exchange fee cap**,
not an actual charge. It may be used only in a labelled conservative stress scenario. A
production cost estimate rejects the cap, assumptions, estimates, and unknown values as
actual charges. Broker commission and actual exchange charge remain `UNKNOWN` until
account-specific evidence is recorded.

Risk calculations retain cost scenario, each component, status, source, and assumptions ID.
Tests use clearly labelled `USER_ASSUMPTION` values in `BACKTEST`; they do not install fake
production fees.

## 12. Audit contract and non-repaint semantics

The future append-only store must persist, without lossy summaries:

- strategy, setup, proposal, plan, position, and raw contract IDs
- source signal IDs and all named rationale inputs
- `event_time`, `confirmed_at`, risk `evaluated_at`, fill event/recorded times
- entry, initial/current stop, target or every deterministic exit rule
- risk points/THB, reward points/gross/net THB, RRR or expectancy
- quantity derivation and existing/resulting total-position risk
- full cost/slippage assumptions and provenance
- every rejection and kill-switch trigger/reason/state change
- every entry/exit fill, including broker IDs when future adapters supply them
- every stop request, its serialized inputs, accepted/rejected result, and reason
- every partial exit, final exit reason, emergency transition, and reconciliation event
- contiguous per-trade event sequence numbers

`event_time` remains when market information occurred; `confirmed_at` remains when a closed
bar made it knowable. Neither may be overwritten with processing time. Future mutation may
not change an earlier confirmed proposal, decision, or audit event.

## 13. Current implementation boundary

Implemented and unit-tested here:

- immutable contracts and validation
- isolated risk equations and fail-closed decisions
- kill-switch decisions
- lifecycle transition graph
- pure position/fill/stop/exit reducers
- recovery and audit schemas
- strategy-to-risk-to-execution type boundary

The three focused test modules contain 49 deterministic tests and require no real market
data.

Intentionally not implemented:

- any strategy signal
- runtime wiring or orchestration
- broker/PaperBroker adapter, order transport, idempotency, or reconciliation transport
- real/live order submission, modification, or cancellation
- calibrated numerical policy

TFEX-2 replay/aggregation now exists elsewhere in the repository; this dormant risk
contract remains intentionally unwired to it.

Before activation in future milestones, paper execution must add idempotent broker order
IDs, duplicate prevention, cancel/replace acknowledgements, restart persistence, and
broker/account reconciliation tests around these locked reducers. Live trading remains
disabled and is outside this contract.
