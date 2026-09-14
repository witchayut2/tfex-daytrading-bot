# TFEX-3 Definition Lock

Status: **SPECIFICATION LOCKED FOR IMPLEMENTATION**

This memo resolves the three remaining neutral-analysis definitions for TFEX-3. It does
not define a strategy, direction, setup score, order, or production calibration. All
artifacts remain raw-contract, closed-bar, deterministic, and causal.

## 1. Deterministic Order Blocks

### 1. Existing repository evidence

`CLAUDE_TFEX.md` requires deterministic Order Blocks and later strategy sections refer to
fresh/mitigated zones, but it does not define source-candle selection. The current
`MarketStructureEngine` already supplies strict close-confirmed BOS/CHoCH events from
confirmed same-timeframe pivots. It never treats a wick as a break.

### 2. Ambiguity found

The repository did not say which candle forms the zone, how far backward to search, or
when the zone becomes knowable. The phrase "swing that anchors the broken leg" also needs
an exact identity when several opposite pivots are known.

### 3. Proposed deterministic rule

Recommendation: **LOCK_NOW** as `LAST_OPPOSITE_CANDLE_AFTER_ANCHOR_V1`.

- Only a `BOS` may form an Order Block; a `CHOCH` does not.
- A bullish BOS uses the latest confirmed low pivot known at the BOS close as its anchor.
  A bearish BOS uses the latest confirmed high pivot. The anchor must have an event time
  strictly before the BOS bar's event time. The break records the anchor pivot ID and
  times; no eligible anchor means an explicit `NO_ORDER_BLOCK` selection outcome.
- Search same-symbol, same-timeframe closed bars satisfying
  `anchor.event_time < source.event_time < bos.event_time`.
- Bullish selection is the last bearish candle (`close < open`) in that interval. Bearish
  selection is the last bullish candle (`close > open`). A doji is not eligible.
- Search never extends before the anchor. At most one primary Order Block exists per BOS.
- Every BOS therefore records exactly one selection outcome: `ORDER_BLOCK_CREATED` or
  `NO_ORDER_BLOCK`.
- The full source-candle `[low, high]` is the zone. `event_time` is the source candle's
  event time and `confirmed_at` is exactly the associated BOS confirmation time.
- State begins `ACTIVE`. A strictly later same-timeframe closed bar first trading anywhere
  in the inclusive zone makes it `MITIGATED`. A later closed bar closing strictly below a
  bullish zone low or strictly above a bearish zone high makes it `INVALIDATED`.
  If the first returning bar both enters and closes beyond the far boundary, invalidation
  is terminal and its `mitigated_at` and `invalidated_at` are both retained at that close.
- The BOS bar cannot mitigate or invalidate the Order Block it confirms.

This is consistent with current structure semantics. The smallest required extension is
for a `StructureBreak` to retain the latest causally known opposite-pivot anchor. The
anchor's market event, rather than its later pivot-confirmation instant, bounds the
historical leg; the zone itself remains unknowable until BOS confirmation.

### 4. Alternatives rejected

- Last opposite candle before BOS without an anchor: unbounded search can manufacture a
  zone from an unrelated leg.
- CHoCH-created zones: outside the proposed canonical definition.
- Displacement, volume, institutional-order, premium/discount, or subjective visual
  selection: no canonical rule or calibrated evidence exists.
- Candle body-only zones: the specification supplies no authority to discard wicks.

### 5. Non-repaint implications

The source candle is historical but the Order Block is absent until the BOS closes. Source,
anchor, and BOS IDs are immutable. Only later closed bars produce lifecycle revisions.
Batch, incremental, restart, prefix, and future-mutation results must match.

### 6. Parameters requiring later calibration

None for the locked selection/lifecycle rule. Optional future freshness or mitigation-depth
thresholds would be strategy research and are not part of TFEX-3.

### 7. Trading-alpha assumptions

No trade consequence, quality claim, or direction recommendation is attached. The rule is
a reproducible neutral annotation required by the milestone.

### 8. Recommendation

**LOCK_NOW.**

## 2. Regime classification

### 1. Existing repository evidence

The current engine already derives HH/HL/LH/LL from confirmed same-timeframe pivots.
`CLAUDE_TFEX.md` calls for an interpretable regime engine with configurable thresholds, and
the research protocol requires all labels to be versioned, causal, and calibrated only on
permitted past/calibration data. It explicitly leaves numerical thresholds uncalibrated.

### 2. Ambiguity found

The broad session-regime labels in the legacy specification combine structure, volatility,
VWAP, range, and volume without canonical formulas or thresholds. Implementing those labels
now would invent production parameters. The existing `STRUCTURE_RANGE` also collapses two
distinct mixed swing states.

### 3. Proposed deterministic rule

Recommendation: **LOCK_NOW** as three separate neutral layers.

1. Closed 15-minute structure only:
   - `HH + HL -> BULLISH_STRUCTURE`
   - `LH + LL -> BEARISH_STRUCTURE`
   - `LH + HL -> CONTRACTION_STRUCTURE`
   - `HH + LL -> EXPANSION_STRUCTURE`
   - incomplete, equal, or other conflicting evidence -> `UNRESOLVED`
2. Volatility classification accepts one explicitly supplied causal observation and an
   externally supplied threshold record containing `threshold_id`,
   `calibration_dataset_id`, `calibrated_at`, `feature`, `low_threshold`,
   `high_threshold`, and `method`. Values below the low boundary are `LOW`, values above
   the high boundary are `HIGH`, and inclusive boundary/interior values are `NORMAL`.
   Missing observation or thresholds returns `UNCALIBRATED`. The classifier has no fitting
   method and rejects thresholds whose calibration dataset is the evaluation dataset.
3. The composite is the immutable Cartesian product
   `StructureRegime x VolatilityRegime`, never LONG/SHORT or BUY/SELL.

The structural mapping is logically consistent with the existing swing engine and restores
information that its deliberately coarse `STRUCTURE_RANGE` label currently combines.

### 4. Alternatives rejected

- Guessing ATR percentiles, relative-volume cutoffs, or opening-range thresholds.
- Fitting percentiles on the dataset being evaluated.
- Retrospective whole-session labels or opaque/LLM classification.
- Collapsing structure and volatility directly to a trading direction.

### 5. Non-repaint implications

Only confirmed 15-minute structure updates can change structure regime. Forming 15-minute
candles are not inputs. A volatility observation carries `event_time` and `confirmed_at`;
future or evaluation-derived calibration is rejected rather than silently consumed.

### 6. Parameters requiring later calibration

All numeric ATR, normalized-ATR, realized-range, and relative-volume low/high thresholds.
Their research selection, sensitivity analysis, and production review remain outside
TFEX-3 infrastructure.

### 7. Trading-alpha assumptions

The four structure mappings are descriptive identities. The volatility interface makes no
claim that a state predicts returns. No strategy action is emitted.

### 8. Recommendation

**LOCK_NOW** for structure mapping, threshold provenance/validation, fail-closed
`UNCALIBRATED`, and composite representation. Numeric calibration remains explicitly
`UNCALIBRATED`, not a missing TFEX-3 implementation.

## 3. Liquidity importance

### 1. Existing repository evidence

The architecture lists source, age, touch/sweep state, distance, timeframe alignment,
volume response, and contract identity as possible ranking factors. The current engine
creates confirmed pivot/equality/session/opening-range levels, but neither the architecture
nor real research establishes weights or a total source hierarchy. The 15m/5m/1m roles are
context layers, not proof that every higher-timeframe level outranks every lower one.

### 2. Ambiguity found

There is no canonical ordering among previous-day, session, opening-range, equal-pivot, and
swing-pivot sources. Directions for touch count, age, distance, and volume-response effects
are also unvalidated. A numeric or lexicographic total rank would therefore encode hidden
alpha assumptions.

### 3. Proposed deterministic rule

Recommendation: **LOCK_NOW** a causal feature vector and conservative partial order, not a
total ranking.

Each vector exposes raw symbol, level ID, confirmation state, timeframe, categorical source
type, confluence count, age at the requested as-of time, exact lifecycle/swept state, and
confirmation time. Stable presentation order is by level ID and is explicitly not an
importance rank.

Two confirmed vectors are comparable only when raw symbol, timeframe, and source type are
identical. Within that homogeneous class, one dominates only if it is no worse on every
transparent dimension (confirmed, confluence count, unswept state, and recency) and strictly
better on at least one. Conflicting dimensions, different categorical sources/timeframes,
or unconfirmed inputs are `INCOMPARABLE`; identical vectors are `EQUAL`.

### 4. Alternatives rejected

- Weighted score: no weights have research support.
- Lexicographic total order with source ranks: it turns arbitrary enum order into policy.
- Treating 15m as universally superior to 5m/1m: timeframe roles do not prove importance.
- Using final-run touch/sweep state for earlier frames: direct future leakage.

### 5. Non-repaint implications

Feature extraction takes an explicit aware `as_of`. Unconfirmed levels cannot contribute
to confluence. A level revision made after `as_of` cannot be reconstructed from the later
object and is rejected fail-closed. The engine exposes immutable final-as-of vectors and
never backfills an earlier frame with a later touch or sweep.

### 6. Parameters requiring later calibration

Any source hierarchy, cross-timeframe priority, weights, total-order tie breakers, distance
from current price, volume-response interpretation, or strategy selection rule.

### 7. Trading-alpha assumptions

The vector and Pareto-style partial order preserve observable facts. They do not assert a
cross-source ranking or select a setup.

### 8. Recommendation

**LOCK_NOW** for feature extraction, stable non-rank ordering, and partial-order semantics.
**DEFER_TO_RESEARCH** only the total ranking/weighting policy; it is not required for neutral
TFEX-3 infrastructure.

## 4. Confluence

### 1. Existing repository evidence

Existing equal pivots require exact price equality because no tolerance is authorized.
Prices are `Decimal` and TFEX tick size is verified separately.

### 2. Ambiguity found

No canonical distance says when distinct liquidity prices are "near enough" to be one
cluster.

### 3. Proposed deterministic rule

Recommendation: **LOCK_NOW** exact-price confluence as the fail-closed default. Count unique
confirmed same-symbol levels, including the subject level, whose prices are exactly equal.
If an explicit non-negative `price_tolerance_ticks` is supplied, a verified positive tick
size is also required and the inclusive distance is
`price_tolerance_ticks * tick_size`.

### 4. Alternatives rejected

- An undocumented point/percentage/ATR tolerance.
- Returning a guessed count from levels not yet confirmed.
- Grouping different raw contracts.

### 5. Non-repaint implications

Only levels confirmed and created by `as_of` participate. A future level or later lifecycle
revision cannot change an already materialized vector.

### 6. Parameters requiring later calibration

Any nonzero `price_tolerance_ticks`. Exact equality needs no empirical calibration and is
safer than `UNCALIBRATED` because it provides a conservative, non-manufactured lower bound
without implying proximity.

### 7. Trading-alpha assumptions

Exact equality is identity, not an efficacy claim. A nonzero tolerance remains external
research configuration.

### 8. Recommendation

**LOCK_NOW.**

## 5. Milestone boundary

If the locked implementations and mandatory behavioral suites pass, deterministic Order
Blocks, descriptive regime infrastructure, and liquidity importance features satisfy the
remaining TFEX-3 analysis requirements. Numeric volatility thresholds and any total
liquidity ranking belong to future declared research; leaving them uncalibrated does not
justify inventing values and is not itself a TFEX-3 implementation blocker.
