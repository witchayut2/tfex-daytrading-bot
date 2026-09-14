# TFEX Candle Alignment

Status: **TFEX-2 COMPLETE / TESTED ON REAL S50U26 DATA**

This document is the canonical alignment policy required by `CLAUDE_TFEX.md` section 10.
All timestamps are timezone-aware `Asia/Bangkok` timestamps. A source one-minute bar labelled
`t` covers `[t, t + 1 minute)` and becomes available at `confirmed_at = t + 1 minute`.

## Session anchors

Higher-timeframe buckets restart at each independent continuous session:

| Session | Half-open interval | 5m result | 15m result |
| --- | --- | --- | --- |
| Morning | `[09:45, 12:30)` | 33 full buckets | 11 full buckets |
| Regular afternoon | `[13:45, 16:55)` | 38 full buckets | 12 full buckets plus `[16:45, 16:55)` |
| LTD afternoon | `[13:45, 16:30)` | 33 full buckets | 11 full buckets |

The regular afternoon's final 15-minute alignment slot contains ten actual minutes. It is
confirmed only at the verified 16:55 session close, records
`expected_source_bar_count = source_bar_count = 10`, and sets
`is_short_session_close_bucket = true`. It is never padded to 17:00 and never discarded.
The same rule applies to an officially shortened session: a shorter terminal bucket is
published only at the actual session close and only when every one-minute constituent in
that shortened interval exists.

## Causal availability

- A forming aggregate has `is_closed = false` and `confirmed_at = null`.
- Only a bucket with every contiguous one-minute constituent is appended to confirmed
  history.
- Confirmed bars have `confirmed_at = close_time`; their `event_time` is the final source
  bar's event time.
- Missing constituents raise a replay error. No price or volume is filled.
- Morning buckets end at or before 12:30. Afternoon buckets begin at 13:45. No bucket spans
  lunch, a session boundary, midnight, or a raw contract change.
- OHLC is first-open, maximum-high, minimum-low, last-close. Volume and complete trade counts
  are summed; last-observation fields remain last-observation fields.

## Reproducibility

Batch processing delegates to the same one-event-at-a-time engine used by incremental
replay. Restart discards all derived state. Seek reconstructs from source bar 1 through the
requested cursor and never restores future-derived state.
