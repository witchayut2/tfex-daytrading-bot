# TFEX Data-Readiness Gate — Decision

- **Date:** 2026-08-24
- **Baseline:** verified TFEX-0 / TFEX-1, tree `4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc`

## Decision

```text
BLOCKED_REAL_MARKET_DATA
```

Everything the gate asked for was completed **except** the one thing that cannot be produced
from this environment: a real historical 1-minute SET50 futures dataset. No substitute was
created. **TFEX-2 was not started**, per the gate's own instruction.

| Requirement for `READY_FOR_TFEX2` | Status |
| --- | --- |
| 2026 TFEX holiday calendar imported and verified | ✅ 20 official holidays, `VERIFIED_OFFICIAL` |
| SET50 Futures contract / last-trading-day calendar imported and verified | ✅ 6 contracts, 4 cross-checked `VERIFIED` |
| Baseline Git state protected or commit blocker documented | ✅ tree recorded; commit blocked and documented |
| Exchange fee semantics corrected | ✅ cap and actual charge separated in the type system |
| Market-data validator implemented | ✅ 11 checks, 4 exit codes, CLI exercised end to end |
| A legitimate real 1-minute S50 source identified | ⚠️ **partially** — Settrade Open API selected; symbol coverage and depth unconfirmed without credentials |
| At least one real raw contract dataset acquired and validated | ❌ **none available** |

Milestone status: **`TFEX2_NOT_STARTED`**. The acceptance machinery exists and refuses to
report anything better on fixtures alone.

---

## What the gate produced

### PART A — baseline preserved

Verified before any modification: 277 passed, 12 anti-repaint, ruff clean, 73 files
formatted, mypy strict clean on 71 files. Evidence: `docs/data_readiness_baseline.md`.
No test was weakened; none was failing.

### PART B — Git initialised, commit blocked

```text
BASELINE COMMIT BLOCKED:
git user.name / user.email not configured
```

No identity was invented and global config was untouched. Instead the baseline was staged
and recorded as an immutable tree object, which needs no author:

```text
4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc
```

Recovery instructions: `docs/baseline_manifest.md`.

### PART C — real 2026 holiday calendar

Retrieved from the exchange's own holiday endpoint — the one the published holiday page
fetches — in both English and Thai, cross-checked against each other.

- **20 holidays**, including **2 exchange-declared special holidays** (2026-01-02,
  2026-10-16) that a generic Thai public-holiday list does not carry. This is precisely the
  failure mode the gate warned about.
- Raw captures: `backend/data/tfex/official/holidays/2026/raw.en.json`, `raw.th.json`
- SHA-256 (en): `895393b6896c9cd567b531d608c36cccb0495eeb8c7af6a601fc25ad6d18b11a`
- SHA-256 (th): `3231597e2343824703b85a1e13480f8f6091467a01a43c249767475d9b18d1fb`

**2025 and 2027 are not available.** The endpoint returns HTTP 401 for every year except the
current display year — confirmed by probing 2024, 2025, 2026 and 2027 with fresh sessions.
TFEX has not published the 2027 calendar yet. This is recorded as a fact, not worked around.

All nine validation proofs pass: `uv run python scripts/validate_calendar_data.py --year 2026`.

### PART D — real SET50 futures contract calendar

| Symbol | Month | First trading day | Published LTD | Derived LTD | Match | Status |
| --- | --- | --- | --- | --- | --- | --- |
| S50Q26 | 2026-08 | 2026-05-28 | 2026-08-28 | 2026-08-28 | ✅ | `VERIFIED` |
| S50U26 | 2026-09 | 2025-09-29 | 2026-09-29 | 2026-09-29 | ✅ | `VERIFIED` |
| S50V26 | 2026-10 | 2026-07-30 | 2026-10-29 | 2026-10-29 | ✅ | `VERIFIED` |
| S50Z26 | 2026-12 | 2025-12-29 | 2026-12-29 | 2026-12-29 | ✅ | `VERIFIED` |
| S50H27 | 2027-03 | 2026-03-30 | 2027-03-30 | — | n/a | `PUBLISHED_UNVERIFIED` |
| S50M27 | 2027-06 | 2026-06-29 | 2027-06-29 | — | n/a | `PUBLISHED_UNVERIFIED` |

Last trading time **16:30 Asia/Bangkok** for every contract, matching the specification.
Raw capture SHA-256: `eac06e64c6180cf93f1cf7c41b0c3f42344563fc4e7124733c51ed949a6ad3b2`.

**Zero conflicts.** Every 2026 contract's published last trading day matches the
contract-specification rule computed against the imported holiday calendar. Two independent
sources agreeing is the strongest evidence available that both the holiday import and the
last-trading-day implementation are correct.

The 2027 contracts are `PUBLISHED_UNVERIFIED` because their holiday year is not published.
They are **not** merged into the calendar store, so nothing can quietly rely on them.

### PART E — exchange fee semantics corrected

Audit found the cap in exactly two places (`config.py`, `tfex.yaml`) and in no P&L path —
there is no P&L engine yet, which is why fixing this *now* mattered.

| Figure | Value | Status | Charged in production? |
| --- | --- | --- | --- |
| Exchange fee **cap** | THB 7 / contract / side | `VERIFIED_EXCHANGE_CAP` | **No** |
| Exchange fee **actual** | not configured | `UNKNOWN` | No |
| Broker commission | not configured (negotiable) | `UNKNOWN` | No |
| Backtest assumption | `CONSERVATIVE_STRESS_TEST` | labelled | n/a |
| Production assumption | none | — | — |

The distinction is enforced by types, not documentation:

- `FeeComponent.charge_for(CostScenario.PRODUCTION)` on the cap raises `FeeSemanticsError`.
- `production_charge=True` with any status other than `VERIFIED_BROKER_RATE` fails validation.
- An `UNKNOWN` cost cannot be charged in **any** scenario.
- `ExchangeFeeConfig` refuses to let `actual_status` be `VERIFIED_EXCHANGE_CAP`.

19 tests in `tests/tfex/test_fee_semantics.py`.

### PARTS F, G, X — historical data source research

Full audit: `docs/tfex_historical_data_sources.md`.

Primary evidence came from reading the official `settrade-v2` 2.2.1 SDK source, not from
marketing copy:

```python
def get_candlestick(self, symbol, interval, limit=None, start=None, end=None, normalized=None)
# -> https://marketapi.settrade.com/api/techchart/v3/{broker_id}/candlesticks
```

| Question | Answer | Basis |
| --- | --- | --- |
| 1-minute interval | **CONFIRMED** | SDK documents `'1m', '3m', '5m', … '1M'` |
| Historical derivatives candlestick | **UNKNOWN** | `MarketData` is generic; `get_quote_futures` is commented out in the SDK |
| Raw S50 contract symbol | **UNKNOWN** | undocumented; untestable without credentials |
| Max lookback / bars per request | **UNKNOWN** | server-side |
| Pagination | **UNKNOWN** | none in the signature; windowing only |
| Entitlement / broker dependency | **YES** | `broker_id` is embedded in the URL path |
| Sandbox vs production | **differ** | separate hosts `marketapi` / `marketapi-test` |
| Rate limits | 5/second, 60/minute defaults | `context.py`, server-overridable via headers |

Selected: **primary** Settrade Open API, **secondary** SET/SETSMART tick or intraday request
(TFEX tick from Nov 2014; ~USD 420–1,000/month). TradingView excluded on terms of service.

### PARTS H–T — market-data validator

`scripts/validate_tfex_market_data.py`, built **before** TFEX-2 so it cannot be written to
agree with the importer. Eleven independent checks, each keeping its own status:

`provenance` · `row_parsing` · `contract_identity` · `timestamps` · `duplicates` · `ohlc` ·
`tick_size` · `volume` · `session_boundaries` · `missing_bars` · `expiry`

Exit codes `0` PASS, `1` PASS_WITH_WARNINGS, `2` REJECTED, `3` CONFIGURATION_OR_PROVENANCE_ERROR.

Behaviours worth naming:

- A naive timestamp with no declared source timezone is an **error**, never an assumed UTC.
- Anomalous rows are **reported, never deleted**.
- A zero-volume bar is a quiet minute, **not** missing data.
- Conflicting duplicates (same timestamp, different OHLCV) are never silently deduplicated.
- The expected bar grid is built **per session** and never runs through lunch.
- Missing runs are classified `POSSIBLE_NO_TRADE` / `SOURCE_DATA_GAP` / `CRITICAL_DATA_GAP`.
- A derived-only contract calendar returns `BLOCKED_UNVERIFIED_CONTRACT_CALENDAR`, not a pass.
- An edited raw file fails on checksum: "any result citing this dataset is void".

Exercised end to end against a synthetic day using the **real imported calendar**: 355
expected bars, 0 missing, expiry resolved `EXCHANGE_PUBLISHED`. Exit 3 without a manifest,
exit 3 on a checksum mismatch, exit 1 with a placeholder source.

### PARTS U, V — acceptance gate

`mark_tfex2_complete()` raises `RealMarketDataValidationRequired` unless at least one
validated, non-synthetic dataset is supplied. Status ladder:
`TFEX2_NOT_STARTED` → `TFEX2_FIXTURE_VALIDATED` → `TFEX2_REAL_DATA_VALIDATED`.

A gap found while testing the CLI and closed: a validator-generated starter manifest carries
`source: "UNVERIFIED - fill this in"`, which would otherwise have counted as real data.
`source_is_verified` now rejects the placeholder, and a test pins it.

Nine `real_market_data` tests exist and **skip** for want of data. Skipping is not passing.

### PART W — download scripts

`scripts/data_sources/settrade_history.py` with a `--probe` mode. Credentials come from the
environment only; the SDK is imported lazily and is not a project dependency. **No API
response is fabricated** — without credentials the script explains what is missing and exits 3.

### PART Y — source verification statuses

Written from the stored captures by `scripts/update_source_verification.py`, never by hand.

| Source | Status |
| --- | --- |
| TFEX holidays | `VERIFIED_OFFICIAL` |
| SET50 Index Futures product trading calendar | `VERIFIED_OFFICIAL` (4/6 cross-checked) |
| TFEX SET50 Index Futures contract specification | `CROSS_CHECKED` — tick size 0.1 and point value 200 corroborated against the exchange series endpoint |
| TFEX annual trading calendar | `CROSS_CHECKED` — trading days only; shortened sessions **not** covered |
| TFEX margin announcements | `NOT_VERIFIED` |
| SET50 Futures margin page | `NOT_VERIFIED` |
| Settrade Open API documentation | `NOT_VERIFIED` |
| Settrade Open API broker list | `NOT_VERIFIED` |
| Settrade derivatives use cases | `NOT_VERIFIED` |
| SET50 Index overview | `NOT_VERIFIED` |

Per fact rather than per source: the exchange fee **cap** is verified while the **actual**
exchange fee and the broker commission remain `UNKNOWN`.

---

## Verification

```text
uv run pytest tests/tfex          365 passed, 9 skipped
uv run pytest -m anti_repaint      13 passed, 2 skipped
uv run pytest -m real_market_data   9 skipped   <-- the blocker, visible in the suite
uv run ruff check .                All checks passed
uv run ruff format --check .       93 files already formatted
uv run mypy .                      Success - 91 source files
uv run python scripts/validate_calendar_data.py --year 2026   PASS (all 9 proofs)
uv run python scripts/import_tfex_contracts.py                0 conflicts
```

The 2 skipped anti-repaint tests are the real-data ones. They are the gate, working.

---

## Exactly what the operator must provide

### Option A — Settrade Open API (preferred; likely free with an existing account)

1. Identify the broker and confirm it is on
   <https://developer.settrade.com/open-api/document/broker-list>.
2. Export credentials in your shell — never into a file in this repository:
   ```bash
   export SETTRADE_APP_ID=...
   export SETTRADE_APP_SECRET=...
   export SETTRADE_BROKER_ID=...
   export SETTRADE_APP_CODE=...
   ```
3. Install the optional SDK and run the capability probe (one read-only call, no orders):
   ```bash
   uv add --dev settrade-v2
   uv run python scripts/data_sources/settrade_history.py --probe --symbol S50Z26
   ```
   It writes `backend/data/tfex/official/settrade_capability.json` answering the three open
   questions: are S50 contract symbols served, is `1m` accepted, how far back does it go.
4. If confirmed, download two contracts (the gate prefers two, to prove contract isolation):
   ```bash
   uv run python scripts/data_sources/settrade_history.py --symbol S50U26 --interval 1m \
       --start 2026-06-01 --end 2026-08-21
   uv run python scripts/data_sources/settrade_history.py --symbol S50Z26 --interval 1m \
       --start 2026-06-01 --end 2026-08-21
   ```

### Option B — SET / SETSMART

Purchase or request the data, place the original files under
`backend/data/tfex/historical/raw/<SYMBOL>/`, and record source, authority and licence in the
manifest beside each file.

### Then, either way

```bash
uv run python scripts/validate_tfex_market_data.py \
    --file backend/data/tfex/historical/raw/S50Z26/<file>.csv \
    --symbol S50Z26 --interval 1m --timezone Asia/Bangkok
uv run pytest -m real_market_data
```

When those pass on a non-synthetic dataset the decision becomes `READY_FOR_TFEX2` and TFEX-2
implementation can begin.

### Also outstanding (does not block TFEX-2)

1. **Configure Git identity** so the baseline becomes a real commit (`docs/baseline_manifest.md`).
2. **Import the 2027 holiday calendar** when TFEX publishes it; until then S50H27 and S50M27
   have no cross-checked expiry and anything reaching into 2027 fails closed.
3. **Verify the actual exchange fee and broker commission** against a statement. Until then
   every cost figure is a labelled assumption.
4. **Confirm shortened-session announcements** — the annual trading calendar page was not
   retrieved, so early closes are unverified.

---

## What was deliberately not done

- No holiday date was invented; 2025 and 2027 remain unimported and fail closed.
- No last trading day was guessed; the 2027 contracts stay `PUBLISHED_UNVERIFIED`.
- No synthetic candles were generated and presented as market data.
- The exchange fee cap was not treated as an actual charge.
- No dataset was scraped from TradingView or any source whose terms forbid it.
- No S50 contracts were merged before raw validation.
- TFEX-2 was not started, and TFEX-2 was not simulated as complete.
- No live order route exists; `live_orders_enabled: true` still raises.
