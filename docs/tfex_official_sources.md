# TFEX Official Sources

<!-- GENERATED FILE - do not edit by hand.
     Statuses are derived from the captures under backend/data/tfex/official/.
     Regenerate with: uv run python scripts/update_source_verification.py -->

Generated: 2026-08-24

Register of every official source the platform depends on, as required by
`CLAUDE_TFEX.md` section 2. A source that has never been verified is shown as
`NOT_VERIFIED`; that is a statement of fact, not an oversight.

## SET50 Futures margin page

- **URL:** https://www.tfex.co.th/en/products/equity/set50-index-futures/margin
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `initial_margin`, `maintenance_margin`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** 7 days
- **Fallback behavior:** As above; cross-check only.

## SET50 Index Futures product trading calendar

- **URL:** https://www.tfex.co.th/en/products/equity/set50-index-futures/trading-calendar
- **Retrieval date:** 2026-08-24T06:35:31.263492+00:00
- **Effective date:** _none published_
- **Fields consumed:** `contract_month`, `first_trading_day`, `last_trading_day`
- **Fingerprint:** sha256:eac06e64c6180cf93f1cf7c41b0c3f42344563fc4e7124733c51ed949a6ad3b2
- **Last verification result:** `VERIFIED_OFFICIAL` at 2026-08-24T07:17:41.811192+00:00
- **Refresh interval:** 30 days
- **Fallback behavior:** Fall back to the derived last-trading-day rule and stamp the contract as DERIVED_RULE. Rejected when expiry.require_published_last_trading_day is true.
- **Note:** 6 listed S50 contracts; 4 had their published last trading day confirmed against the contract-specification rule using the imported holiday calendar. Not cross-checked (no holiday data for that year yet): ['S50H27', 'S50M27'].

## SET50 Index overview

- **URL:** https://www.set.or.th/en/market/index/set50/overview
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `index_level`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** _on demand_
- **Fallback behavior:** Basis calculations are skipped and reported as unavailable.
- **Note:** Optional spot reference for basis analysis (section 14 of CLAUDE_TFEX.md).

## Settrade Open API broker list

- **URL:** https://developer.settrade.com/open-api/document/broker-list
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** _reference only_
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** _on demand_
- **Fallback behavior:** Live connectivity blocked until the broker is confirmed supported.
- **Note:** Section 26 prerequisite 1.

## Settrade Open API documentation

- **URL:** https://developer.settrade.com/open-api/
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** _reference only_
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** _on demand_
- **Fallback behavior:** Adapter interfaces only; no live connectivity in this build.
- **Note:** Reference only until a broker and credentials exist (section 26).

## Settrade derivatives use cases

- **URL:** https://developer.settrade.com/open-api/use-case
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** _reference only_
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** _on demand_
- **Fallback behavior:** Reference only.

## TFEX SET50 Index Futures contract specification

- **URL:** https://www.tfex.co.th/en/products/equity/set50-index-futures/contract-specification
- **Retrieval date:** 2026-08-24T07:17:42.392053+00:00
- **Effective date:** _none published_
- **Fields consumed:** `multiplier`, `tick_size`, `tick_value`, `listed_contract_months`, `daily_price_limit`, `trading_hours`, `last_trading_day_rule`, `settlement_method`
- **Fingerprint:** sha256:a1bb009b81841fd2808d8b364d631facc18f4eb6e033347369f9febfefc94ace
- **Last verification result:** `CROSS_CHECKED` at 2026-08-24T07:17:41.811192+00:00
- **Refresh interval:** 90 days
- **Fallback behavior:** Use the checked-in contract configuration and mark contract metadata unverified. Order-capable modes reject.
- **Note:** tick size and point value corroborated against the exchange series endpoint for S50Z26 ({'tickSize': '0.1', 'priceQuotationFactor': '200.0'}). The specification page itself was not retrieved, so fee, price-limit and settlement terms remain unverified.

## TFEX annual trading calendar

- **URL:** https://www.tfex.co.th/en/about/trading-calendar
- **Retrieval date:** 2026-08-24T06:32:03.839723+00:00
- **Effective date:** _none published_
- **Fields consumed:** `trading_days`, `shortened_sessions`
- **Fingerprint:** _none recorded_
- **Last verification result:** `CROSS_CHECKED` at 2026-08-24T07:17:41.811192+00:00
- **Refresh interval:** 30 days
- **Fallback behavior:** Calendar raises CalendarDataUnavailableError for unloaded years.
- **Note:** Trading days are derived from the imported holiday calendar rather than from this page directly. Shortened sessions are NOT covered and remain unverified.

## TFEX holidays

- **URL:** https://www.tfex.co.th/en/about/holiday
- **Retrieval date:** 2026-08-24T06:32:03.839723+00:00
- **Effective date:** _none published_
- **Fields consumed:** `holiday_date`, `holiday_name`
- **Fingerprint:** sha256:895393b6896c9cd567b531d608c36cccb0495eeb8c7af6a601fc25ad6d18b11a
- **Last verification result:** `VERIFIED_OFFICIAL` at 2026-08-24T07:17:41.811192+00:00
- **Refresh interval:** 30 days
- **Fallback behavior:** Calendar raises CalendarDataUnavailableError for unloaded years.
- **Note:** Imported for 2026 from the exchange's own holiday endpoint; English and Thai variants cross-checked; 20 holidays including 2 exchange special holiday(s).

## TFEX margin announcements

- **URL:** https://www.tfex.co.th/en/market-data/news-and-notice/margin
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `initial_margin`, `maintenance_margin`, `effective_date`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** 7 days
- **Fallback behavior:** Margin gate rejects new positions when margin.reject_when_stale is true (TFEX-4).

## Verification summary

- Registered sources: **10**
- Verified: **4**
- Not verified: **6**

Sources still awaiting verification:

- SET50 Futures margin page
- SET50 Index overview
- Settrade Open API broker list
- Settrade Open API documentation
- Settrade derivatives use cases
- TFEX margin announcements
