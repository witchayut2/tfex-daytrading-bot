# TFEX backend

Backend for the TFEX SET50 Index Futures research and paper-trading platform.
Specification: `../CLAUDE.md` and `../CLAUDE_TFEX.md`. Architecture: `../docs/tfex_architecture.md`.
Current gate decision: `../docs/tfex_data_readiness_gate.md` —
**`READY_FOR_TFEX2`**. Five complete real S50U26 1-minute days are validated with checksum
lineage. TFEX-2 deterministic replay/market state and TFEX-3 deterministic neutral analysis
are complete; locked definitions and evidence are documented in
`../docs/tfex3_definition_lock.md` and `../docs/tfex3_acceptance.md`.

**Paper trading only.** There is no live order route, and `config/tfex.yaml` cannot enable one.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed and managed by uv.

```bash
cd backend
uv sync
```

## Checks

```bash
uv run pytest tests/tfex             # full suite
uv run pytest -m anti_repaint        # the non-repainting invariants only
uv run pytest -m real_market_data    # validates local real data; history sufficiency is separate
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

## Operator tools

```bash
# exchange metadata (imports raw captures with SHA-256 provenance)
uv run python scripts/import_tfex_holidays.py --year 2026
uv run python scripts/import_tfex_contracts.py
uv run python scripts/validate_calendar_data.py --year 2026
uv run python scripts/update_source_verification.py --corroborate-spec

# market data: use the exact read-only acquisition/validation commands in the canonical docs
# ../docs/tfex_historical_data_sources.md
# ../docs/tfex_data_readiness_gate.md
```

Validator exit codes: `0` PASS, `1` PASS_WITH_WARNINGS, `2` REJECTED,
`3` CONFIGURATION_OR_PROVENANCE_ERROR.

## Data status

| Data | State |
| --- | --- |
| TFEX holidays | **2026 imported and verified** (20 holidays). 2025 and 2027 unavailable from the source; the calendar fails closed for them. |
| SET50 contract calendar | **6 contracts imported**; the four 2026 contracts cross-checked against the derived rule with zero conflicts. |
| 1-minute market data | **S50U26, five complete days, 1,775 rows, real-data validated.** The readiness minimum is met. |

Credentials are never stored here. The Settrade downloader reads `SETTRADE_APP_ID`,
`SETTRADE_APP_SECRET`, `SETTRADE_BROKER_ID` and `SETTRADE_APP_CODE` from the environment and
never prints them.

## Layout

```text
app/tfex/
  config.py          exchange facts + research defaults, validated on load
  errors.py          typed failure hierarchy
  provenance.py      official-source register and metadata freshness
  calendar/          imported holiday data -> trading days -> expiry
  contracts/         symbols -> resolved contracts -> registry -> roll policy
  sessions/          phases for a date -> session state -> entry/exit gates
  costs/             fee provenance: a published cap is not an actual charge
  marketdata/        bars -> dataset provenance -> validation -> acceptance gate
  margins/ liquidity/ basis/ feeds/ brokers/ risk/
                     documented placeholders; each names its milestone
config/tfex.yaml     the configuration
data/tfex/official/  immutable raw captures of exchange metadata + provenance
data/tfex/holidays/  per-year calendar files the platform reads
data/tfex/historical/ ignored licensed raw data, normalized derivatives, and atomic staging
scripts/             operator tools
tests/tfex/          TFEX unit, anti-repaint, and real-market acceptance tests
```
