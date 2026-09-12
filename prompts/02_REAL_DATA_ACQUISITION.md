Read `AGENTS.md`.

Proceed only if prior probe result is `SETTRADE_REAL_DATA_READY`.

Acquire a SMALL real raw-contract S50 Futures dataset first.

Requirements:
- one individual raw contract
- 1-minute interval
- initially 5–10 complete trading days
- preserve source timestamps and provenance
- no continuous contract
- no raw-file mutation
- no credentials in source/docs/logs
- do not commit licensed raw data unless license permits it

Create/update manifest and SHA-256.

Run the existing validator against the real dataset.

Report separately:
- timestamp
- timezone
- OHLC
- tick size
- volume
- duplicates
- missing bars
- session boundary
- contract identity
- expiry
- provenance

Then run:
`uv run pytest -m real_market_data`

Do not start TFEX-2 unless the real-data gate is satisfied.
