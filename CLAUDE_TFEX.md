# CLAUDE_TFEX.md

## 0. Authority and scope

This file is the authoritative specialization specification for building a **non-repainting, real-time visual, paper-trading and future automated-trading platform for TFEX SET50 Index Futures**.

Read this file together with the root `CLAUDE.md`.

Conflict resolution:

1. Safety, data integrity, non-repainting, and risk rules in `CLAUDE.md` always remain in force.
2. This file overrides generic market assumptions with TFEX SET50 Futures-specific rules.
3. Current TFEX specifications, trading calendars, margin rates, broker rules, and API schemas must be verified from official sources before implementation or live use.
4. No real-money order submission may be enabled until all paper-trading, reconciliation, anti-repaint, and operational-readiness gates pass.

Target status:

> TFEX SET50 Futures research and paper-trading platform ready for extended forward testing.

Do not claim profitability, investment suitability, regulatory approval, or readiness for real-money trading.

---

# 1. Product being built

Build a browser-based platform that:

- receives or replays SET50 Index Futures market data
- builds 1-minute, 5-minute, and 15-minute candles
- displays an interactive TradingView-style chart
- calculates deterministic non-repainting intraday structure
- identifies day-trading setups
- scores each setup transparently
- applies position sizing and risk controls
- simulates orders and fills
- records full audit history
- supports future broker and Settrade Open API adapters
- remains in paper-trading mode by default

Primary strategies:

1. Liquidity Sweep Reversal
2. Trend Continuation Pullback
3. Opening Range Breakout, enabled only after the first two strategies are validated

Primary analysis:

- confirmed swing highs and lows
- BOS
- CHoCH
- previous-day levels
- morning-session levels
- afternoon-session levels
- opening range
- session VWAP
- full-day VWAP
- ATR
- relative volume
- liquidity sweep
- FVG
- deterministic order block
- trendline as a secondary filter
- contract basis and roll context when spot/index data is available

Do not use Elliott Wave, chart screenshots, an LLM, or discretionary natural-language reasoning as an execution trigger.

---

# 2. Official reference links

These links are references for implementation. Do not scrape them on every market event. Build scheduled metadata refresh jobs and cache validated results.

## TFEX SET50 Index Futures

- Contract specification:
  https://www.tfex.co.th/en/products/equity/set50-index-futures/contract-specification
- Product trading calendar:
  https://www.tfex.co.th/en/products/equity/set50-index-futures/trading-calendar
- TFEX annual trading calendar:
  https://www.tfex.co.th/en/about/trading-calendar
- TFEX holidays:
  https://www.tfex.co.th/en/about/holiday
- Current margin announcements:
  https://www.tfex.co.th/en/market-data/news-and-notice/margin
- SET50 Futures margin page:
  https://www.tfex.co.th/en/products/equity/set50-index-futures/margin
- Settrade Open API:
  https://developer.settrade.com/open-api/
- Settrade Open API broker list:
  https://developer.settrade.com/open-api/document/broker-list
- Settrade derivatives use cases:
  https://developer.settrade.com/open-api/use-case
- SET50 Index overview:
  https://www.set.or.th/en/market/index/set50/overview

Add an internal document:

`docs/tfex_official_sources.md`

For each source record:

- source name
- URL
- retrieval date
- effective date where available
- fields consumed
- checksum or content fingerprint
- last verification result
- fallback behavior if unavailable

Never silently continue with stale exchange metadata when expiry, session, or margin calculations depend on it.

---

# 3. Current contract facts and dynamic-data rule

The current official contract specification states:

- underlying: SET50 Index
- ticker root: `S50`
- multiplier: THB 200 per index point
- minimum price fluctuation: 0.1 index point
- tick value: THB 20 per contract
- listed contract months: three nearest consecutive months plus the next three quarterly months
- daily price limit: ±30% of the latest settlement price
- morning pre-open: 09:15–09:45 Asia/Bangkok
- morning continuous session: 09:45–12:30
- afternoon pre-open: 13:15–13:45
- afternoon continuous session: 13:45–16:55
- last trading day: business day immediately before the last business day of the contract month
- trading ceases at 16:30 on the last trading day
- settlement: cash settlement
- final settlement methodology: exchange-defined SET50 averaging methodology
- maximum exchange fee in the current summary: THB 7 per contract per side
- brokerage commission: negotiable

These values must be represented as configuration and metadata, not scattered constants.

Create:

```yaml
market:
  exchange: TFEX
  timezone: Asia/Bangkok
  instrument_family: SET50_INDEX_FUTURES
  symbol_root: S50
  currency: THB

contract:
  point_value_thb: 200
  tick_size_points: 0.1
  tick_value_thb: 20
  settlement_type: CASH
  price_limit_reference: LATEST_SETTLEMENT
  price_limit_percent: 30
```

Important:

- Margin rates are dynamic.
- Brokerage commissions vary by broker and client.
- Trading holidays change annually.
- Last trading dates vary by contract and calendar.
- API features vary by participating broker.
- All dynamic values must be fetched, imported, or entered from verified sources.
- Do not infer an expired or active contract from symbol text alone.

---

# 4. Repository additions

Add or adapt this TFEX structure:

```text
backend/app/tfex/
├── __init__.py
├── config.py
├── calendar/
│   ├── models.py
│   ├── service.py
│   ├── holiday_loader.py
│   ├── trading_day.py
│   └── expiry.py
├── contracts/
│   ├── symbol_parser.py
│   ├── metadata.py
│   ├── registry.py
│   ├── roll.py
│   └── continuous_series.py
├── sessions/
│   ├── engine.py
│   ├── boundaries.py
│   ├── opening_range.py
│   ├── midday_break.py
│   └── snapshots.py
├── margins/
│   ├── models.py
│   ├── provider.py
│   ├── validation.py
│   └── history.py
├── costs/
│   ├── commissions.py
│   ├── exchange_fees.py
│   └── slippage.py
├── liquidity/
│   ├── levels.py
│   ├── sweep.py
│   └── session_levels.py
├── basis/
│   ├── models.py
│   ├── calculator.py
│   └── filters.py
├── feeds/
│   ├── base.py
│   ├── csv_feed.py
│   ├── realtime_readonly.py
│   └── settrade_future.py
├── brokers/
│   ├── base.py
│   ├── paper.py
│   └── settrade_future.py
└── risk/
    ├── point_value.py
    ├── margin_gate.py
    ├── expiry_gate.py
    └── session_gate.py
```

Add tests:

```text
backend/tests/tfex/
├── test_symbol_parser.py
├── test_contract_registry.py
├── test_expiry_calendar.py
├── test_session_boundaries.py
├── test_midday_break.py
├── test_last_trading_day.py
├── test_roll_logic.py
├── test_point_value.py
├── test_margin_gate.py
├── test_opening_range.py
├── test_liquidity_levels.py
├── test_gap_engine.py
├── test_session_vwap.py
├── test_full_day_vwap.py
├── test_next_bar_execution.py
└── test_end_of_day_flatten.py
```

---

# 5. Contract symbol model

Create a strict `TfexContractSymbol` model.

Fields:

- raw symbol
- root
- month code
- two-digit year
- contract year
- contract month
- expiry date
- last trading timestamp
- status
- is_near_month
- days_to_expiry
- metadata_version

Support month-code validation according to actual TFEX symbols.

Do not assume only quarterly symbols exist because SET50 Futures lists nearest consecutive months plus additional quarterly months.

The parser must:

- reject malformed symbols
- reject impossible month/year combinations
- support historical symbols
- use exchange metadata to resolve expiry
- never guess the active contract without registry data

Contract statuses:

- `PRE_LISTED`
- `ACTIVE`
- `ROLL_CANDIDATE`
- `LAST_TRADING_DAY`
- `EXPIRED`
- `UNKNOWN`

---

# 6. Contract registry

Build a contract registry that stores:

- listed contracts
- listing date
- last trading date
- last trading time
- expiry status
- daily volume
- open interest
- latest settlement price
- margin metadata
- data freshness
- source version

The registry is the single source of truth for:

- current near-month selection
- expiry safety checks
- continuous-series construction
- roll recommendations
- order symbol validation

No strategy may select a contract directly.

It must request an eligible contract from the registry.

---

# 7. Near-month and roll logic

Day-trading should normally use the most liquid eligible series, not blindly the nearest calendar contract.

Implement configurable roll selection.

Default roll policy:

1. Exclude expired contracts.
2. Exclude contracts after the configured expiry cutoff.
3. Compare near and next contracts using:
   - current session volume
   - rolling volume
   - open interest
   - bid-ask spread where available
   - time to expiry
4. Switch the trading contract only after confirmation criteria pass.
5. Persist the exact roll decision.
6. Do not splice positions across contracts.

Suggested default confirmation:

```yaml
roll:
  enabled: true
  minimum_days_before_expiry: 2
  volume_ratio_threshold: 1.20
  confirmation_sessions: 1
  prevent_new_positions_on_last_trading_day_after: "15:45"
  force_flatten_before_last_trade_stop_minutes: 15
```

These values are research defaults, not exchange rules.

Implement two datasets:

- raw contract series, never adjusted
- research continuous series, explicitly labeled and constructed

Backtesting execution must use raw contract prices.

Continuous adjusted prices may be used only for long-window context and must not generate impossible fills.

---

# 8. TFEX trading calendar

Create a calendar service for Asia/Bangkok.

The calendar must know:

- trading days
- TFEX holidays
- special holidays
- shortened sessions if announced
- contract last trading days
- contract-specific early cessation
- current session state

Session state enum:

- `CLOSED`
- `MORNING_PREOPEN`
- `MORNING_OPEN`
- `MIDDAY_BREAK`
- `AFTERNOON_PREOPEN`
- `AFTERNOON_OPEN`
- `LAST_TRADING_DAY_CLOSING_WINDOW`
- `POST_CLOSE`

Do not derive trading days only from weekdays.

Load official calendar data into versioned storage.

Provide manual administrative override with:

- operator
- reason
- source
- created_at
- effective date
- approval status

---

# 9. Session engine

Default regular-day boundaries:

```yaml
sessions:
  timezone: Asia/Bangkok

  morning_preopen:
    start: "09:15"
    end: "09:45"

  morning:
    start: "09:45"
    end: "12:30"

  midday_break:
    start: "12:30"
    end: "13:45"

  afternoon_preopen:
    start: "13:15"
    end: "13:45"

  afternoon:
    start: "13:45"
    end: "16:55"
```

The overlap between midday break and afternoon pre-open is intentional. Model market states explicitly rather than assuming one continuous phase.

The strategy engine must not open new positions:

- during pre-open
- during midday break
- after the configured entry cutoff
- after 16:30 on the last trading day
- while the calendar is unknown or stale

Allow configurable exits during periods where the broker/exchange permits them, but do not fabricate execution during closed periods.

---

# 10. Candle construction

Primary input granularity:

- ticks or one-minute candles when available

Required timeframes:

- 1 minute
- 5 minutes
- 15 minutes

Rules:

- Align bars to TFEX session boundaries.
- Never create a bar spanning the midday break.
- Do not forward-fill price bars through the break.
- Do not treat pre-open indicative values as continuous-session trades unless the feed semantics explicitly identify executable trades.
- A five-minute or fifteen-minute candle closes only after its time bucket completes.
- Morning and afternoon aggregations are independent.
- Missing source bars must be flagged.
- Strategy operation is suspended when required bar integrity is unknown.

Example:

- A 15-minute afternoon bar starts at 13:45, not at 13:30.
- The morning final 15-minute bucket may need a documented short-bucket policy depending on aggregation alignment.
- Do not silently invent a full-length bar beyond the session close.

Document the exact bucket policy in `docs/tfex_candle_alignment.md`.

---

# 11. Session profiles

For every trading day, calculate immutable confirmed snapshots.

Full-day:

- previous day high
- previous day low
- previous day open
- previous day close
- previous day midpoint
- previous day range
- previous settlement price where available

Morning:

- morning open
- morning high
- morning low
- morning close
- morning midpoint
- morning range
- morning VWAP
- morning opening-range high and low

Afternoon:

- afternoon open
- afternoon high
- afternoon low
- afternoon close
- afternoon midpoint
- afternoon range
- afternoon VWAP
- afternoon opening-range high and low

Live session highs and lows are provisional until the session closes.

Historical values become confirmed after session close and may not repaint.

Strategies may use current session running high or low only under explicitly provisional rules that do not backdate confirmation.

---

# 12. VWAP modes

Implement three modes.

1. Full-day VWAP
   - starts at 09:45
   - pauses during midday break
   - continues at 13:45
   - does not reset in the afternoon

2. Morning VWAP
   - starts at 09:45
   - ends at 12:30

3. Afternoon VWAP
   - starts at 13:45
   - ends at 16:55

Do not choose the best VWAP retrospectively for each trade.

A strategy configuration must select its VWAP mode before replay.

Backtest all modes separately and report sensitivity.

---

# 13. Opening ranges

Implement:

- morning 5-minute opening range
- morning 15-minute opening range
- morning 30-minute opening range
- afternoon 5-minute opening range
- afternoon 15-minute opening range
- afternoon 30-minute opening range

Default strategy values:

- morning OR: 15 minutes
- afternoon OR: 15 minutes

Opening range becomes confirmed only after its window ends.

Breakout requires a closed candle outside the range.

Track:

- breakout direction
- penetration in points
- penetration in ATR
- relative volume
- retest
- false break
- time to retest
- target levels

---

# 14. Gap engine

Implement at least:

1. Overnight gap
   - current morning open versus previous day close
   - current morning open versus previous settlement

2. Midday gap
   - afternoon open versus morning close

3. Contract roll gap
   - informational only
   - must never be mixed with a tradable same-contract gap

Gap model:

- gap ID
- gap type
- contract
- source close
- destination open
- size points
- size THB per contract
- size in ATR
- direction
- created_at
- fill percentage
- first fill time
- full fill time
- status

Statuses:

- `OPEN`
- `PARTIALLY_FILLED`
- `FILLED`
- `INVALID_DATA`

Do not calculate a gap using different contracts unless explicitly labeled as roll analysis.

---

# 15. Liquidity map

Create liquidity levels from:

- previous day high
- previous day low
- previous settlement
- morning high
- morning low
- afternoon high
- afternoon low
- opening-range high
- opening-range low
- confirmed swing high
- confirmed swing low
- equal highs
- equal lows
- session VWAP
- optionally spot SET50 reference levels

Rank levels by:

- source importance
- age
- touch count
- prior sweep status
- distance from current price
- alignment across timeframes
- volume response
- whether the level is from the same contract

Liquidity levels must carry:

- event_time
- confirmed_at
- availability status
- contract symbol
- source session
- source object IDs

---

# 16. TFEX day-trading regime engine

Classify each session and full day.

Session regimes:

- `TREND_UP`
- `TREND_DOWN`
- `BALANCED_RANGE`
- `OPENING_EXPANSION`
- `FAILED_BREAKOUT`
- `REVERSAL`
- `LOW_LIQUIDITY`
- `HIGH_VOLATILITY`
- `UNDEFINED`

Inputs:

- opening-range width in ATR
- VWAP slope
- VWAP cross count
- price distance from VWAP
- confirmed structure sequence
- morning-to-afternoon gap
- session range expansion
- relative volume
- breadth or SET50 spot context if available
- basis behavior if available

No LLM and no opaque model in version 1.

All thresholds must be configurable and tested with sensitivity analysis.

---

# 17. Strategy A — Liquidity Sweep Reversal

## Long

Hard conditions:

1. A downside liquidity level was confirmed before the sweep.
2. Price trades below that level.
3. A closed 1-minute or 5-minute candle returns above it.
4. A bullish CHoCH is confirmed after the sweep.
5. A valid bullish FVG or deterministic bullish order block exists.
6. Entry occurs on a retest or confirmed micro-break.
7. Minimum reward-to-risk passes.
8. Risk engine approves.
9. Contract is eligible.
10. Market session is eligible.
11. Market data is current and sequence-complete.

Preferred confluences:

- previous day low
- morning low
- afternoon opening-range low
- full-day or session VWAP proximity
- elevated relative volume
- sweep penetration between configurable ATR bounds
- afternoon reversal following a failed morning continuation

Short uses inverse rules.

Do not enter solely because a wick crossed a level.

---

# 18. Strategy B — Trend Continuation Pullback

## Long

Hard conditions:

1. 15-minute confirmed structure is bullish.
2. Price is above selected VWAP.
3. VWAP slope is positive.
4. Five-minute bullish BOS is confirmed.
5. Pullback reaches a fresh FVG or deterministic order block.
6. Zone mitigation remains below threshold.
7. One-minute bullish CHoCH or BOS is confirmed.
8. Trigger candle closes above micro structure.
9. Price is not excessively extended from VWAP.
10. Opposing liquidity allows minimum reward-to-risk.
11. Risk engine approves.

Avoid:

- repeated VWAP crossing
- low-volume midday drift
- entry immediately before session close
- entry near expiry cutoff
- stale or widened spread
- contract migration period without clear liquidity dominance

Short uses inverse rules.

---

# 19. Strategy C — Opening Range Breakout

Keep disabled until Strategies A and B pass validation.

Rules:

1. Opening range is confirmed.
2. Breakout candle closes outside the range.
3. Relative volume passes threshold.
4. Breakout penetration is not excessive.
5. Entry occurs on retest by default.
6. Bias and VWAP support the direction.
7. False-break filter passes.
8. Minimum reward-to-risk passes.
9. Session time remains eligible.

Separate morning and afternoon ORB statistics.

Never combine their performance without attribution.

---

# 20. Time-of-day analytics

Default buckets:

- 09:45–10:15
- 10:15–11:15
- 11:15–12:30
- 13:45–14:30
- 14:30–15:30
- 15:30–16:30
- 16:30–16:55 on non-expiry days only

For each bucket persist:

- setup count
- qualified signal count
- trade count
- win rate
- average R
- median R
- expectancy
- profit factor
- drawdown contribution
- average spread
- average slippage
- regime mix

Do not hardcode “good” or “bad” times based on opinion.

Use statistics only after minimum sample requirements.

Default minimum:

```yaml
time_bucket_statistics:
  minimum_trades: 50
  minimum_sessions: 30
```

Until sample size passes, mark results as insufficient.

---

# 21. Point-value and risk calculations

Use:

```text
tick size = 0.1 point
tick value = THB 20 per contract
point value = THB 200 per contract
```

Gross price risk:

```text
risk_thb =
abs(entry_points - stop_points)
× 200
× contracts
```

Net estimated risk:

```text
net_risk_thb =
gross_price_risk
+ round_trip_commission
+ exchange_fees
+ estimated_slippage
+ additional_cost_buffer
```

Position size:

```text
contracts =
floor(
  allowed_risk_thb
  /
  estimated_risk_per_contract_thb
)
```

Reject if:

- contracts < 1
- margin is insufficient
- free-equity buffer is insufficient
- hard exposure limit is exceeded
- stop is invalid
- price is outside exchange limits
- contract is ineligible

Do not size positions using margin alone.

Margin is a collateral requirement, not maximum acceptable loss.

---

# 22. Margin service

Margin values are dynamic.

Implement a versioned margin provider.

Margin model:

- contract family
- series where relevant
- outright or spread
- initial margin
- maintenance margin
- force-close margin
- effective timestamp
- source
- retrieved_at
- verified
- stale_after
- broker override

Risk engine must use the stricter of:

- official/reference margin
- broker-reported margin
- configured safety margin

Default safety buffer:

```yaml
margin:
  free_equity_buffer_multiplier: 2.0
  reject_when_stale: true
```

Do not embed a single current margin number in strategy code.

---

# 23. Cost model

Support:

- exchange fee
- broker commission
- VAT or applicable charges as configured
- bid-ask spread
- slippage
- partial fill
- latency cost

Commission and fee configuration must support:

- per contract per side
- minimum fee
- tiered rate
- VAT
- broker-specific overrides

Paper trading and backtesting must use round-trip cost estimates.

Report gross and net results separately.

---

# 24. Execution semantics

Version 1 is bar-close strategy execution.

Default:

- signal confirmed at candle close
- order becomes eligible on the next tradable event
- market order fills at next available ask/bid plus slippage
- when only OHLC is available, use a conservative next-bar model
- never fill at the same close used to confirm the signal

During midday break:

- pending orders follow explicit policy
- no fabricated fills
- stops are not simulated as executable during closed periods
- afternoon reopening gap must be handled explicitly

At session close:

- end-of-day flatten is enabled by default
- create exit sufficiently before close
- do not assume a fill at 16:55 without execution data

On last trading day:

- trading stops at the official contract-specific cessation time
- apply stricter entry cutoff
- force flatten before the configured safety cutoff

---

# 25. Paper broker

Build the paper broker to mimic future Settrade adapter semantics.

Required:

- idempotency key
- duplicate-order prevention
- order state machine
- partial fills
- cancel and replace
- position reconciliation
- account snapshots
- margin checks
- session checks
- contract checks
- expiry checks
- kill switch

The paper broker must expose the same interface as the future live broker adapter.

No strategy code may call Settrade directly.

---

# 26. Settrade adapter boundary

Create interfaces only until the broker and credentials are available.

Interfaces:

```python
class TfexMarketDataAdapter(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def subscribe_quotes(self, symbols: list[str]) -> None: ...
    async def subscribe_trades(self, symbols: list[str]) -> None: ...
    async def get_contract_metadata(self) -> list[ContractMetadata]: ...

class TfexBrokerAdapter(Protocol):
    async def authenticate(self) -> None: ...
    async def place_order(self, request: OrderRequest) -> OrderAck: ...
    async def cancel_order(self, order_id: str) -> OrderAck: ...
    async def replace_order(self, request: ReplaceOrderRequest) -> OrderAck: ...
    async def get_orders(self) -> list[BrokerOrder]: ...
    async def get_positions(self) -> list[BrokerPosition]: ...
    async def get_account(self) -> BrokerAccount: ...
    async def reconcile(self) -> ReconciliationResult: ...
```

Before implementing live connectivity:

1. Verify the user's broker is on the supported broker list.
2. Retrieve the current official SDK/API schema.
3. Confirm derivatives-market-data availability.
4. Confirm order types.
5. Confirm authentication and token lifetime.
6. Confirm rate limits.
7. Confirm conditional-order semantics.
8. Confirm sandbox or test environment availability.
9. Confirm broker-specific margin fields.
10. Confirm API terms for automated trading.

Do not automate browser clicks as a substitute for a trading API.

---

# 27. Non-repainting TFEX rules

All general anti-repaint rules remain mandatory.

TFEX-specific requirements:

- Morning levels cannot use afternoon data.
- Afternoon levels cannot be backfilled into morning decisions.
- A morning high becomes final only after 12:30.
- An afternoon high becomes final only after 16:55, except contract-specific early close.
- Previous-day levels become available at the next valid session.
- An opening range becomes available only after its window closes.
- A higher-timeframe candle becomes confirmed only at its actual TFEX-aligned close.
- No candle may span the midday break.
- Contract roll must never rewrite raw historical prices.
- Continuous-series adjustment must not alter execution prices.
- Margin changes must not be retroactively applied to historical trades unless running a clearly labeled current-margin stress test.

Add anti-repaint tests for each rule.

---

# 28. Data-quality gates

Before strategy processing, validate:

- correct contract
- correct timezone
- valid trading day
- current session
- monotonic sequence
- no duplicate candle
- no unresolved gap in required bars
- valid OHLC
- non-negative volume
- data freshness
- contract not expired
- metadata not stale

System behavior:

- visual-only mode may continue with a warning for selected noncritical issues
- paper/live order mode must stop on critical data-quality failure

---

# 29. Dashboard requirements

Top bar:

- active contract
- days to expiry
- current session
- current TFEX clock
- feed status
- paper/live mode
- bot state
- kill-switch state
- margin freshness

Chart layers:

- candlesticks
- volume
- full-day VWAP
- session VWAP
- previous-day high/low/close
- morning high/low
- afternoon high/low
- opening range
- liquidity levels
- sweeps
- pivots
- BOS
- CHoCH
- FVG
- order blocks
- entries
- stops
- targets
- orders
- fills
- positions

Side panel:

- 15m bias
- 5m setup
- 1m trigger
- regime
- setup score
- score breakdown
- contract basis if available
- current ATR
- relative volume
- allowed risk
- estimated risk per contract
- allowed contract quantity
- margin requirement
- free-equity buffer
- trade rejection reasons

Bottom panels:

- orders
- positions
- trades
- signals
- risk decisions
- audit log
- replay controls
- contract-roll history

---

# 30. Backtesting requirements

Datasets must preserve contract identity.

For each trade record:

- raw symbol
- contract month
- session
- time bucket
- days to expiry
- roll state
- strategy
- regime
- spread assumption
- slippage assumption
- commission
- exchange fee
- gross P&L
- net P&L
- R multiple

Required reports:

- by strategy
- by contract
- by month
- by session
- by time bucket
- by regime
- by direction
- by score band
- by days to expiry
- by VWAP mode
- by opening-range mode
- before and after costs

Do not report continuous-series performance without raw-contract execution validation.

---

# 31. Validation gates before real-time read-only mode

Must pass:

- candle alignment tests
- session boundary tests
- midday-break tests
- expiry calendar tests
- contract parser tests
- deterministic replay
- anti-repaint suite
- paper broker tests
- cost model tests
- risk engine tests
- end-of-day flatten tests
- frontend sequence recovery
- snapshot restore

Minimum research data:

- multiple market regimes
- expiry weeks
- roll periods
- high-volatility days
- low-volume days
- gap days
- morning-only and afternoon reversals

---

# 32. Validation gates before real-money consideration

Do not enable real orders until all are true:

1. Extended historical out-of-sample tests completed.
2. Walk-forward testing completed.
3. Replay and incremental results match.
4. Forward paper trading completed for a meaningful period.
5. At least 100 qualified paper trades, preferably more.
6. Execution costs calibrated from observable market data.
7. Risk limits tested through fault injection.
8. Kill switch tested.
9. Restart and state restoration tested.
10. Broker reconciliation tested.
11. Duplicate-order fault test passed.
12. Contract-roll live simulation passed.
13. Expiry-day safety test passed.
14. Operator understands manual emergency procedures.
15. Broker API terms and account permissions verified.
16. Independent code and risk audit completed.

Even after these gates, keep first live deployment at the smallest supported quantity and treat it as operational validation, not proof of profitability.

---

# 33. Initial implementation milestones

## Milestone TFEX-0 — Audit

- read `CLAUDE.md` and this file
- inspect repository
- run all existing tests
- identify current architecture
- create `docs/tfex_repository_audit.md`
- list missing TFEX modules
- identify repaint risks
- identify contract and session assumptions

## Milestone TFEX-1 — Metadata and calendar

Implement:

- TFEX configuration
- official-source registry
- contract symbol parser
- contract registry
- trading calendar
- holiday import
- last trading day model
- session state engine
- tests

## Milestone TFEX-2 — TFEX-aligned replay

Implement:

- raw contract CSV import
- 1m/5m/15m aggregation
- midday-break handling
- morning/afternoon session snapshots
- full-day and session VWAP
- opening ranges
- gap engine
- tests

## Milestone TFEX-3 — Analysis

Implement:

- confirmed pivots
- market structure
- BOS
- CHoCH
- liquidity map
- sweep detector
- FVG
- deterministic order blocks
- regime engine
- tests

## Milestone TFEX-4 — Strategies and risk

Implement:

- Liquidity Sweep Reversal
- Trend Continuation Pullback
- setup scoring
- point-value sizing
- margin gate
- expiry gate
- time/session gate
- kill switch
- tests

## Milestone TFEX-5 — Paper execution

Implement:

- paper broker
- order state machine
- cost model
- next-bar fills
- partial fills
- positions
- P&L
- end-of-day flatten
- reconciliation
- tests

## Milestone TFEX-6 — Visual dashboard

Implement:

- active contract display
- session state
- expiry countdown
- chart layers
- risk panel
- setup explanation
- paper orders
- audit log
- replay controls
- end-to-end tests

## Milestone TFEX-7 — Read-only realtime adapter

Only after earlier milestones pass:

- implement read-only current data adapter
- no order submission
- compare replay semantics to real-time semantics
- record feed gaps
- calibrate spread/slippage
- forward paper trade

---

# 34. Definition of done

The TFEX specialization is complete when:

- the official contract metadata is represented and versioned
- calendar and holiday logic work
- expiry and last-trading-day logic work
- raw contract symbols are preserved
- contract roll is deterministic and audited
- no candle crosses the midday break
- 1m/5m/15m candles align with TFEX sessions
- full-day and session VWAP work
- morning and afternoon opening ranges work
- gap engine works
- liquidity levels are non-repainting
- both core strategies generate auditable paper signals
- position sizing uses THB 200 per point and includes costs
- dynamic margin gate works
- paper orders use conservative execution semantics
- end-of-day and expiry-day flattening work
- anti-repaint tests pass
- backend tests, lint, and type checks pass
- frontend tests and build pass
- Playwright end-to-end tests pass
- no real broker order route is enabled

Final status label:

`TFEX SET50 Futures research and paper-trading system — forward-test candidate`

---

# 35. Commands Claude Code must run

At the start:

```bash
pwd
git status
find . -maxdepth 3 -type f | sort | sed -n '1,240p'
```

Backend discovery:

```bash
find backend -maxdepth 4 -type f | sort | sed -n '1,300p'
```

Frontend discovery:

```bash
find frontend -maxdepth 4 -type f | sort | sed -n '1,300p'
```

Run existing checks before editing.

Typical backend commands:

```bash
cd backend
python --version
python -m pytest -q
ruff check .
ruff format --check .
mypy .
```

Typical frontend commands:

```bash
cd frontend
npm ci
npm test -- --run
npm run build
npx playwright test
```

Docker verification:

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=300
```

After each milestone:

- run targeted tests
- run full backend tests
- run anti-repaint tests
- run frontend tests
- run frontend build
- update documentation
- update `docs/development_status.md`

---

# 36. Required Claude Code behavior

Before editing:

1. Read all of `CLAUDE.md`.
2. Read all of `CLAUDE_TFEX.md`.
3. Inspect relevant source files.
4. Run existing checks.
5. State assumptions.
6. Identify tests to add.

During work:

- create actual files
- use small coherent changes
- preserve existing working behavior
- add tests with every critical change
- never weaken anti-repaint rules
- never bypass the risk engine
- never add a live-order shortcut

After work:

- show commands run
- show test results
- list files changed
- identify remaining risks
- update development status
- do not state the system is ready for real money

---

# 37. First task for Claude Code

Execute this now:

1. Audit the current repository.
2. Create `docs/tfex_repository_audit.md`.
3. Create the TFEX module structure.
4. Implement TFEX contract metadata models.
5. Implement the SET50 Futures symbol parser.
6. Implement the trading calendar and regular session engine.
7. Implement last-trading-day and expiry safety models.
8. Add tests for all above.
9. Update architecture documentation.
10. Run all checks and fix actionable failures.

Do not implement Settrade order submission.

Do not implement real-money trading.

Do not move to strategy optimization before the calendar, contract, session, and anti-repaint foundations are correct.
