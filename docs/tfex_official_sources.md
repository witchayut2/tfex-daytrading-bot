# TFEX Official Sources

<!-- GENERATED FILE - do not edit by hand.
     Regenerate with: uv run python scripts/render_official_sources.py -->

Generated: 2026-08-23

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
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `contract_month`, `first_trading_day`, `last_trading_day`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** 30 days
- **Fallback behavior:** Fall back to the derived last-trading-day rule and stamp the contract as DERIVED_RULE. Rejected when expiry.require_published_last_trading_day is true.

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
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `multiplier`, `tick_size`, `tick_value`, `listed_contract_months`, `daily_price_limit`, `trading_hours`, `last_trading_day_rule`, `settlement_method`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** 90 days
- **Fallback behavior:** Use the checked-in contract configuration and mark contract metadata unverified. Order-capable modes reject.

## TFEX annual trading calendar

- **URL:** https://www.tfex.co.th/en/about/trading-calendar
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `trading_days`, `shortened_sessions`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** 30 days
- **Fallback behavior:** Calendar raises CalendarDataUnavailableError for unloaded years.

## TFEX holidays

- **URL:** https://www.tfex.co.th/en/about/holiday
- **Retrieval date:** _not retrieved_
- **Effective date:** _none published_
- **Fields consumed:** `holiday_date`, `holiday_name`
- **Fingerprint:** _none recorded_
- **Last verification result:** `NOT_VERIFIED`
- **Refresh interval:** 30 days
- **Fallback behavior:** Calendar raises CalendarDataUnavailableError for unloaded years.

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
- Verified: **0**
- Not verified: **10**

Sources still awaiting verification:

- SET50 Futures margin page
- SET50 Index Futures product trading calendar
- SET50 Index overview
- Settrade Open API broker list
- Settrade Open API documentation
- Settrade derivatives use cases
- TFEX SET50 Index Futures contract specification
- TFEX annual trading calendar
- TFEX holidays
- TFEX margin announcements
