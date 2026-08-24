# TFEX calendar data

**This directory is intentionally empty of holiday dates.**

The platform ships no TFEX holidays. A wrong holiday set silently moves the last business
day of a contract month, which moves the last trading day, which moves the expiry gate — so
inventing dates here would be the most damaging shortcut available in this codebase.
`CLAUDE_TFEX.md` section 2 puts it directly: *never silently continue with stale exchange
metadata when expiry, session, or margin calculations depend on it.*

Until a year is imported, `HolidayStore.year(<year>)` raises `CalendarDataUnavailableError`
and every date-sensitive operation for that year fails closed.

## Importing a year

1. Retrieve the official data:
   - TFEX holidays — <https://www.tfex.co.th/en/about/holiday>
   - TFEX annual trading calendar — <https://www.tfex.co.th/en/about/trading-calendar>
   - SET50 futures product calendar (last trading days) —
     <https://www.tfex.co.th/en/products/equity/set50-index-futures/trading-calendar>
2. Write `<year>.json` in this directory using the schema below. The filename and the
   `year` field must agree; the loader rejects the file if they do not.
3. Record honest provenance. `retrieved_at` is when *you* retrieved it, `verified` stays
   `false` until someone has checked it against the source a second time.
4. Run `uv run pytest tests/tfex -q` to confirm the file loads and validates.

## File schema (`schema_version: 1`)

```json
{
  "schema_version": 1,
  "year": 2026,
  "timezone": "Asia/Bangkok",
  "provenance": {
    "source_name": "TFEX holidays",
    "source_url": "https://www.tfex.co.th/en/about/holiday",
    "retrieved_at": "2026-08-23T09:00:00+07:00",
    "effective_date": "2026-01-01",
    "fingerprint": "sha256:...",
    "verified": false,
    "stale_after": "2027-02-19T09:00:00+07:00",
    "imported_by": "operator name",
    "note": "optional"
  },
  "holidays": [
    { "holiday_date": "2026-01-01", "name": "New Year's Day", "holiday_type": "FULL_CLOSURE" }
  ],
  "shortened_sessions": [
    {
      "session_date": "2026-12-30",
      "afternoon_close": "12:30",
      "reason": "exchange announcement 12/2026"
    }
  ],
  "published_contract_dates": [
    { "contract_year": 2026, "contract_month": 12, "last_trading_date": "2026-12-29" }
  ],
  "overrides": []
}
```

### Field notes

- `holidays[].holiday_type` — `FULL_CLOSURE` or `SPECIAL_HOLIDAY`. Use `SPECIAL_HOLIDAY` for
  late government or exchange announcements, because those invalidate cached calendars.
- `shortened_sessions[]` — set `morning_close`, `afternoon_close`, or both. A date may not
  appear in both `holidays` and `shortened_sessions`.
- `published_contract_dates[]` — **strongly preferred** over the derived rule. When present
  the resolved expiry is stamped `EXCHANGE_PUBLISHED`; otherwise it is `DERIVED_RULE`
  (the business day immediately before the last business day of the contract month).
  Setting `expiry.require_published_last_trading_day: true` in `config/tfex.yaml` makes the
  derived fallback an error instead.
- `overrides[]` — manual administrative corrections. Each needs `operator`, `reason`,
  `source`, `created_at`, `effective_date` and an `approval_status`. **Only `APPROVED`
  overrides take effect**; a `PENDING` override is a request and changes nothing.
- `provenance.stale_after` — when omitted, the calendar applies
  `metadata.holiday_data_stale_after_days` from the configuration.

## Which years to import

`TradingCalendar.required_years_for(start, end)` returns the years needed for a date range,
padded by one year on each side: previous/next-trading-day walks and end-of-month expiry
rules routinely cross a year boundary. Call `TradingCalendar.preflight(start, end)` before a
replay so a missing year fails at the start of the run instead of the middle.
