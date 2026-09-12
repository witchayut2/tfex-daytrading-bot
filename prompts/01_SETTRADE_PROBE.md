Read `AGENTS.md` and current data-readiness documentation first.

Objective: perform a SAFE READ-ONLY Settrade TFEX market-data capability probe.

Never place, change, or cancel an order.

Before probing:

1. Check only PRESENT/MISSING for:
   - SETTRADE_APP_ID
   - SETTRADE_APP_SECRET
   - SETTRADE_BROKER_ID
   - SETTRADE_APP_CODE
2. Never print values.
3. Inspect the installed/current Settrade SDK.
4. Inspect existing `scripts/data_sources/settrade_history.py`.
5. Keep live trading disabled.

Probe an appropriate currently valid S50 contract from the verified contract registry.
Do not blindly hardcode a contract that may now be expired or inactive.

Answer from actual API behavior or exact SDK/API evidence:

- authentication succeeds?
- derivatives market-data entitlement exists?
- raw S50 contract symbol recognized?
- historical derivatives candlestick supported?
- 1m interval supported?
- earliest retrievable timestamp?
- latest retrievable timestamp?
- max bars/request?
- pagination behavior?
- rate limits?
- broker-specific entitlement restrictions?

Persist only non-secret evidence.

Never persist:
- App ID
- Secret
- access/refresh tokens
- account numbers
- PIN/password

Return exactly one:

SETTRADE_REAL_DATA_READY
SETTRADE_AUTH_REQUIRED
SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING
SETTRADE_1M_HISTORY_NOT_SUPPORTED
SETTRADE_RAW_CONTRACT_NOT_SUPPORTED
SETTRADE_PROBE_FAILED

Do not begin TFEX-2.
