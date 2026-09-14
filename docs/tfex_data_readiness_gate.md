# TFEX Data-Readiness Gate — Decision

- **Date:** 2026-09-14
- **Baseline:** verified TFEX-0 / TFEX-1, tree `4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc`

## Decision

```text
READY_FOR_TFEX2
```

The immutable extended S50U26 1-minute dataset covers exactly five complete trading dates
(2026-09-08, 09, 10, 11, and 14), contains 1,775 rows, and passed all eleven validator
checks. Its normalized checksum, ten source-capture checksums, two new-capture checksums,
and four-day parent lineage were re-verified. The canonical acceptance classifier returns
`TFEX2_REAL_DATA_VALIDATED`. A later, separately authorized implementation completed
TFEX-2; the data decision in this document remains unchanged.

| Requirement for `READY_FOR_TFEX2` | Status |
| --- | --- |
| 2026 TFEX holiday calendar imported and verified | ✅ 20 official holidays, `VERIFIED_OFFICIAL` |
| SET50 Futures contract / last-trading-day calendar imported and verified | ✅ 6 contracts, 4 cross-checked `VERIFIED` |
| Baseline Git state protected | ✅ baseline commit `0a5daae` exists; historical tree provenance retained |
| Exchange fee semantics corrected | ✅ cap and actual charge separated in the type system |
| Market-data validator implemented | ✅ 11 checks, 4 exit codes, CLI exercised end to end |
| A legitimate real 1-minute S50 source identified | ✅ Settrade Open API production; S50U26 raw contract and `1m` verified by real read-only calls |
| Real, non-synthetic market data | ✅ manifest `synthetic: false`; source provenance PASS |
| Individual raw contract, not a continuous series | ✅ every bar is S50U26; `contract_identity` PASS |
| Five complete trading dates / required sessions | ✅ exactly 5 dates, 1,775 expected bars, `missing_bars` and `session_boundaries` PASS |
| Validator and real-market suite | ✅ validator overall PASS; 20 real-market tests passed across parent and child |
| Provenance and immutable checksums | ✅ normalized file and all 10 raw captures match the manifest |
| Parent extension lineage | ✅ parent dataset/hash match; 2 new capture hashes recorded; no overlap |
| Expiry / LTD | ✅ no bars past S50U26 LTD 2026-09-29 16:30 Asia/Bangkok |
| Minimum five complete trading days | ✅ 5 complete days; `minimum_dataset_requirement_met: true` |

Readiness evidence status: **`TFEX2_REAL_DATA_VALIDATED`**. Data-readiness decision:
**`READY_FOR_TFEX2`**. Implementation milestone status is now **`TFEX2_COMPLETE`** based on
the separate replay acceptance matrix in `docs/tfex2_acceptance.md`; readiness alone did
not promote it.

---

## What the gate produced

### PART A — baseline preserved

Verified before any modification: 277 passed, 12 anti-repaint, ruff clean, 73 files
formatted, mypy strict clean on 71 files. Evidence: `docs/data_readiness_baseline.md`.
No test was weakened; none was failing.

### PART B — Git initialised; commit blocked at the time

The following is historical gate-time evidence. Git identity was later configured and the
baseline commit now exists as `0a5daae`; see `docs/baseline_manifest.md`.

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

The first pass used the official `settrade-v2` 2.2.1 SDK source, not marketing copy. This
SDK-only table records what could and could not be proven before the permitted real operator
probe; its `UNKNOWN` entries are historical evidence, not the current capability verdict:

```python
def get_candlestick(self, symbol, interval, limit=None, start=None, end=None, normalized=None)
# -> https://marketapi.settrade.com/api/techchart/v3/{broker_id}/candlesticks
```

| Question | Answer | Basis |
| --- | --- | --- |
| 1-minute interval | **CONFIRMED** | SDK documents `'1m', '3m', '5m', … '1M'` |
| Historical derivatives candlestick | **UNKNOWN at SDK-only stage** | `MarketData` is generic; `get_quote_futures` is commented out in the SDK |
| Raw S50 contract symbol | **UNKNOWN at SDK-only stage** | undocumented; required a permitted real call |
| Max lookback / bars per request | **UNKNOWN** | server-side |
| Pagination | **UNKNOWN** | none in the signature; windowing only |
| Entitlement / broker dependency | **YES** | `broker_id` is embedded in the URL path |
| Sandbox vs production | **differ** | separate hosts `marketapi` / `marketapi-test` |
| Rate limits | 5/second, 60/minute defaults | `context.py`, server-overridable via headers |

The later read-only production probe resolved the account/server-dependent capability facts:

| Real operator probe fact | Current status |
| --- | --- |
| Authentication | **CONFIRMED** |
| Derivatives market-data entitlement | **CONFIRMED** |
| Historical derivatives candlestick | **CONFIRMED** |
| Raw `S50U26` contract | **CONFIRMED** |
| `1m` interval | **CONFIRMED** |
| Small request | **CONFIRMED** — 5 bars returned |

The first immutable four-day parent and its five-day extended child prove real-dataset
structure separately from both SDK introspection and capability probing. Neither the probe
nor these datasets establish a documented maximum history depth or official retention
policy. The empty 2026-09-07 response followed by complete 2026-09-08 sessions is only an
observed, inferred availability boundary.

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
validated, non-synthetic dataset explicitly proves the minimum five-complete-trading-day
history requirement **and** a matching replay proves dataset ID, SHA-256, row count,
confirmed 5m/15m output, and a deterministic digest. Structural real-data validity, history
sufficiency, and implementation acceptance are separate. Data-evidence status ladder:
`TFEX2_NOT_STARTED` → `TFEX2_FIXTURE_VALIDATED` →
`TFEX2_INTERIM_REAL_DATA_VALIDATED` → `TFEX2_REAL_DATA_VALIDATED`.

An interim four-day dataset may pass every structural market-data check while remaining
insufficient for promotion. Missing days are recorded in provenance and are never filled,
silently skipped, or replaced with synthetic data.

A gap found while testing the CLI and closed: a validator-generated starter manifest carries
`source: "UNVERIFIED - fill this in"`, which would otherwise have counted as real data.
`source_is_verified` now rejects the placeholder, and a test pins it.

The same ten `real_market_data` tests execute independently against the four-day parent and
five-day child: **20 passed**. The parent remains valid interim evidence; the child proves
both structural validity and minimum-history sufficiency. Direct classification of the
child returned `TFEX2_REAL_DATA_VALIDATED`, with no rejected datasets or reasons.

### PART W — download scripts

`scripts/data_sources/settrade_history.py` has probe, one-session diagnostic, standard
five-to-ten-day acquisition, explicit interim acquisition, and verified-parent extension
modes. Extension verifies the parent CSV, its manifest, an exact validator pass, and every
raw checksum before making two session requests. It publishes a new raw directory and a new
five-day normalized dataset atomically; it never rewrites the four-day parent. Credentials
come from the environment only; the SDK is imported lazily and is not a project dependency. **No API
response is fabricated**. An explicitly requested unavailable session fails immediately.
The 2026-09-14 extension completed successfully: two new immutable captures were added and
the parent remained byte-for-byte checksum-valid.

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
uv run pytest tests/tfex          530 passed, 1 skipped
uv run pytest -m anti_repaint      31 passed, 500 deselected
uv run pytest -m real_market_data  34 passed, 497 deselected
uv run ruff check .                All checks passed
uv run ruff format --check .       113 files already formatted
uv run mypy .                      Success - 110 source files
uv run python scripts/validate_calendar_data.py --year 2026   PASS (all 9 proofs)
uv run python scripts/import_tfex_contracts.py                0 conflicts
```

The one skipped TFEX test is the optional installed-SDK signature check. The real-data tests
execute against both local datasets; the five-day child independently satisfies the
minimum-history requirement.

---

## Readiness promotion evidence

The ignored local child dataset is
`backend/data/tfex/historical/normalized/S50U26/S50U26_1m_2026-09-08_2026-09-14.csv`,
with normalized SHA-256
`b916b86e595df0bfbdc6652871202be2c5619b2cfc3196fd6b6daaf0fed24456`.
It contains exactly 1,775 bars across the five manifest dates. Re-running the validator
returned overall PASS with all eleven checks PASS. Re-hashing the normalized file, the
four-day parent, and all ten source captures matched their manifests; two captures are
explicitly identified as the new 2026-09-14 lineage, with no overlapping windows.

These facts satisfy the data gate and only the data gate. No TFEX-2 replay, VWAP,
aggregation, opening-range, or gap-engine implementation started in this re-evaluation.

### Also outstanding (does not block TFEX-2)

1. **Import the 2027 holiday calendar** when TFEX publishes it; until then S50H27 and S50M27
   have no cross-checked expiry and anything reaching into 2027 fails closed.
2. **Verify the actual exchange fee and broker commission** against a statement. Until then
   every cost figure is a labelled assumption.
3. **Confirm shortened-session announcements** — the annual trading calendar page was not
   retrieved, so early closes are unverified.

---

## What was deliberately not done

- No holiday date was invented; 2025 and 2027 remain unimported and fail closed.
- No last trading day was guessed; the 2027 contracts stay `PUBLISHED_UNVERIFIED`.
- No synthetic candles were generated and presented as market data.
- The exchange fee cap was not treated as an actual charge.
- No dataset was scraped from TradingView or any source whose terms forbid it.
- No S50 contracts were merged before raw validation.
- The readiness promotion did not itself start TFEX-2; a later separately authorized task
  implemented it and passed the independent acceptance matrix.
- No live order route exists; `live_orders_enabled: true` still raises.
