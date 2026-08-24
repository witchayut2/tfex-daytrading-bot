# TFEX Historical 1-Minute Data — Source Audit

Researched 2026-08-24. Purpose: identify a legitimate source of **1-minute (or finer)
historical SET50 Index Futures data that preserves individual contract symbols**
(`S50U26`, `S50Z26`, …), as required before TFEX-2 can be declared market-validated.

`YES` appears only where evidence was obtained. Everything else is `UNKNOWN`, and
`UNKNOWN` is not a synonym for "probably fine".

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `CONFIRMED` | Verified against primary evidence (official docs, SDK source, or a permitted read-only call). |
| `PARTIALLY_CONFIRMED` | Some of the claim is evidenced; the rest is not. |
| `NOT_SUPPORTED` | Evidence shows the capability is absent. |
| `ACCESS_REQUIRED` | Cannot be verified without credentials, a subscription, or a contract. |
| `UNKNOWN` | No evidence either way. |

## Summary table

| Source | Official? | S50 Futures | Raw contract | 1m | History | API/Export | Cost | Verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Settrade Open API | Yes (SET subsidiary) | UNKNOWN | UNKNOWN | **CONFIRMED** (interval set incl. `1m`) | UNKNOWN | REST + Python SDK `settrade-v2` | Free API; broker account required | `PARTIALLY_CONFIRMED` |
| SETSMART / SMART Marketplace | Yes (SET) | CONFIRMED (TFEX data from 2006) | UNKNOWN | `PARTIALLY_CONFIRMED` (intraday advertised; 1m OHLCV export unconfirmed) | 2006→ | Web + API | ~USD 420–1,000 / month | `ACCESS_REQUIRED` |
| SET Historical Data-Request Service | Yes (SET) | CONFIRMED | UNKNOWN | UNKNOWN | UNKNOWN | Manual request | Quoted per request | `ACCESS_REQUIRED` |
| SET tick data service | Yes (SET) | CONFIRMED (TFEX tick from Nov 2014) | Likely (tick carries the series) | Finer than 1m | Nov 2014→ | By request / EOD subscription | Paid | `ACCESS_REQUIRED` |
| TFEX website market statistics | Yes (TFEX) | CONFIRMED | CONFIRMED | **NOT_SUPPORTED** (daily aggregates) | Long | Web tables | Free | `CONFIRMED` — daily only |
| TFEX series endpoints (used by this repo) | Yes (TFEX) | CONFIRMED | CONFIRMED | **NOT_SUPPORTED** (quote snapshot, not history) | n/a | JSON | Free | `CONFIRMED` — metadata only |
| Operator's broker historical feed | Depends | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | `UNKNOWN` — **broker not yet identified** |
| Paid vendors (Portara, FirstRate, Databento, Barchart) | No | UNKNOWN | UNKNOWN | Vendor-dependent | Vendor-dependent | Yes | Paid | `UNKNOWN` — TFEX S50 coverage unverified |
| TradingView | No | — | — | — | — | — | — | **EXCLUDED** — scraping would breach its terms |

---

## 1. Settrade Open API — Priority 1

**Evidence obtained by reading the official Python SDK source** (`settrade-v2` 2.2.1 from
PyPI), not by paraphrasing marketing copy.

### `settrade_v2/market.py`

```python
class MarketData(metaclass=LogWrapperMetaClass):
    def __init__(self, context: Context):
        if config["environment"] == "prod":
            self.market_url = "https://marketapi.settrade.com"
        elif config["environment"] == "uat":
            self.market_url = "https://marketapi-test.settrade.com"
        self.market_url += f"/api/marketdata/v3/{self._ctx.broker_id}"

    def get_candlestick(
        self,
        symbol: str,
        interval: str,
        limit: Optional[int] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        normalized: Optional[bool] = None,
    ):
        path = f"{self.market_url}/candlesticks".replace("marketdata", "techchart", 1)
```

Effective endpoint: `https://marketapi.settrade.com/api/techchart/v3/{broker_id}/candlesticks`.

### `settrade_v2/realtime.py` — the documented interval set

```text
interval : str
    interval of candlestick data
    ('1m', '3m', '5m', '10m', '15m', '30m', '60m', '120m', '240m', '1d', '1w', '1M')
```

### `settrade_v2/context.py` — rate limiting

```text
rate_per_second: int = 5
rate_per_minute: int = 60
```
Updated at runtime from `X-RateLimit-Limit-second` / `X-RateLimit-Limit-minute` response
headers, so the server is authoritative and these are only defaults.

### Verdict on each required fact

| Question | Answer | Evidence |
| --- | --- | --- |
| Historical derivatives candlestick? | **UNKNOWN** | `MarketData` is account-level, not asset-class-scoped: `Investor.MarketData` returns one generic client and `symbol` is an unconstrained `str`. Nothing in the SDK states which symbol namespace the techchart service serves. Notably, `get_quote_futures` and `get_series_futures` exist in the source but are **commented out**. |
| Raw S50 contract symbol (`S50U26`)? | **UNKNOWN** | Not documented; not testable without credentials. |
| 1-minute interval? | **CONFIRMED** | `'1m'` is first in the documented interval list, and `get_candlestick` takes the same `interval: str` against the same techchart service. |
| Maximum lookback? | **UNKNOWN** | `start`/`end`/`limit` exist; no bound is documented client-side. Server-side. |
| Maximum bars per request? | **UNKNOWN** | `limit` is `Optional[int]` with no documented ceiling. |
| Pagination? | **UNKNOWN** | No pagination token in the signature; windowing via `start`/`end` would be the only mechanism. |
| Production entitlement required? | **YES** | `broker_id` is embedded in the URL path — the data path is broker-scoped. |
| Broker dependency? | **YES** | Same reason; capability may differ per participating broker. |
| Sandbox vs production? | **CONFIRMED they differ** | Separate hosts `marketapi.settrade.com` vs `marketapi-test.settrade.com`. UAT data content is unverified and must not be treated as market truth. |

**Conclusion:** the documentation statement "Market Info supports historical data" is *not*
proof of 1-minute S50 contract history, exactly as the gate warned. The interval vocabulary
is proven; the symbol coverage and depth are not. Resolving them needs one permitted
read-only call with real credentials.

---

## 2. SETSMART / SET Information Services — Priority 2

- SETSMART compiles historical SET **and TFEX** data; TFEX coverage is stated from **2006**.
- **SMART Marketplace** provides SET/TFEX data via API and advertises *historical intraday
  trading data for equity and derivatives*.
- **Tick data**: TFEX tick data available from **November 2014**, by historical request or
  end-of-day subscription. Tick is finer than 1m and would satisfy the requirement, provided
  each record carries its contract series.
- Subscription tiers reported at roughly **USD 420–1,000 per month**.

**Not confirmed:** that a 1-minute OHLCV export exists as a product, that exports are
machine-readable per contract symbol, or the licence terms for storing the data in this
repository. A "5 years of history" feature statement is not a granularity statement.

**Next action:** contact SET Information Services (`infoproducts@set.or.th`) with three
specific questions — (a) is per-contract 1-minute OHLCV available for SET50 futures,
(b) from what date, (c) what licence governs local storage and derived backtests.

---

## 3. Operator's broker historical feed — Priority 3

**Blocked at step zero: the broker has not been identified.** Section 26 prerequisite 1
requires confirming the broker is on the Settrade supported-broker list before any
connectivity work. Until the operator names the broker, nothing here can be assessed.

Questions to answer once known: interface, interval, history depth, symbol namespace,
licence, authentication, export mechanism.

---

## 4. Paid vendors — Priority 4

Portara CQG, FirstRate Data, Databento and Barchart all sell historical intraday futures
data, and Barchart publishes TFEX SET50 quote pages. **None was verified to carry
per-contract 1-minute SET50 futures history**, and vendor coverage of TFEX is materially
less common than of CME/Eurex. Any purchase must be checked for: raw contract symbols
(not a stitched continuous series), 1-minute or finer bars, the exact history window, and a
licence permitting local storage and derived research.

## 5. Explicitly excluded

- **TradingView** — its terms prohibit scraping. Excluded regardless of data availability.
- **Any pirated or redistributed dataset.**
- **Generic "SET50 index" history** — the index is not the futures contract; basis and roll
  make them different instruments (section 14).
- **Provider continuous series** (`S50`, `S50!`, "front month adjusted") as *primary
  execution data* — section 7 forbids it. A continuous series may be built later as a
  clearly labelled derived dataset.

---

## Selection

```text
PRIMARY_REAL_DATA_SOURCE      Settrade Open API — get_candlestick(symbol, "1m", start, end)
                              pending: credentials + one read-only probe of S50 symbol coverage

SECONDARY_VALIDATION_SOURCE   SET / SETSMART tick or intraday data request
                              pending: subscription or a quoted data request
```

## Current status

```text
REAL_1M_DATA_BLOCKED
```

No real 1-minute SET50 futures dataset could be acquired in this environment. Nothing was
substituted for it: no synthetic candles were generated and labelled as market data.

### Exactly what is required from the operator

**Option A — Settrade (preferred, likely free with an existing account)**

1. Name the broker and confirm it appears on
   <https://developer.settrade.com/open-api/document/broker-list>.
2. Obtain Open API credentials and export them as environment variables — never into a file
   in this repository:
   ```text
   SETTRADE_APP_ID
   SETTRADE_APP_SECRET
   SETTRADE_BROKER_ID
   SETTRADE_APP_CODE
   ```
3. Run the capability probe, which performs a **single read-only** call and writes an
   evidence file — it does not place orders and it does not print secrets:
   ```bash
   uv run python scripts/data_sources/settrade_history.py --probe --symbol S50Z26
   ```
4. If the probe confirms S50 symbols and 1-minute bars, download:
   ```bash
   uv run python scripts/data_sources/settrade_history.py \
       --symbol S50Z26 --interval 1m --start 2026-06-01 --end 2026-08-21
   ```

**Option B — SET / SETSMART**

Purchase or request the data, place the original files under
`backend/data/tfex/historical/raw/<SYMBOL>/`, and record the licence in the dataset
manifest. Then validate:

```bash
uv run python scripts/validate_tfex_market_data.py \
    --file backend/data/tfex/historical/raw/S50Z26/<file>.csv \
    --symbol S50Z26 --interval 1m --timezone Asia/Bangkok
```

Either path ends at the same place: a validated raw contract dataset, at which point the
gate can be re-evaluated.

## Sources

- [Settrade Open API](https://developer.settrade.com/open-api/) — and the `settrade-v2` 2.2.1 SDK source on PyPI (primary evidence)
- [Settrade Open API broker list](https://developer.settrade.com/open-api/document/broker-list)
- [SET Historical Data-Request Service](https://www.set.or.th/en/services/connectivity-and-data/data/data-request)
- [SET Information Services — historical data](https://www.set.or.th/en/services/connectivity-and-data/data/historical)
- [SET SMART Marketplace](https://set.or.th/en/services/connectivity-and-data/data/smart-marketplace)
- [SET tick data](https://set.or.th/app/online-data/tick-data?lang=en)
- [TFEX market statistics](https://www.tfex.co.th/en/market-data/historical-data/market-statistics)
