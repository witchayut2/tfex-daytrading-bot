# TFEX backend

Backend for the TFEX SET50 Index Futures research and paper-trading platform.
Specification: `../CLAUDE.md` and `../CLAUDE_TFEX.md`. Architecture: `../docs/tfex_architecture.md`.

**Paper trading only.** There is no live order route, and `config/tfex.yaml` cannot enable one.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed and managed by uv.

```bash
cd backend
uv sync
```

## Commands

```bash
uv run pytest tests/tfex          # full suite
uv run pytest -m anti_repaint     # the non-repainting invariants only
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Operator tools:

```bash
uv run python scripts/validate_calendar_data.py     # check imported holiday data
uv run python scripts/render_official_sources.py    # regenerate docs/tfex_official_sources.md
```

## Before anything date-sensitive works

Import official TFEX holiday data into `data/tfex/holidays/<year>.json`. The platform ships
none, and the calendar raises `CalendarDataUnavailableError` for any year that has not been
imported — see `data/tfex/holidays/README.md` for the schema and procedure.

## Layout

```text
app/tfex/
  config.py          exchange facts + research defaults, validated on load
  errors.py          typed failure hierarchy
  provenance.py      official-source register and metadata freshness
  calendar/          imported holiday data -> trading days -> expiry
  contracts/         symbols -> resolved contracts -> registry -> roll policy
  sessions/          phases for a date -> session state -> entry/exit gates
  margins/ costs/ liquidity/ basis/ feeds/ brokers/ risk/
                     documented placeholders; each names its milestone
config/tfex.yaml     the configuration
data/tfex/           imported exchange metadata (holidays are NOT shipped)
scripts/             operator tools
tests/tfex/          277 tests; holiday dates in fixtures are invented, not TFEX data
```
