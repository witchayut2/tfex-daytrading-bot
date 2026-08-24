"""Validate every imported TFEX calendar year file and report what it implies.

Run this after importing a year, before trusting any date-sensitive behaviour::

    uv run python scripts/validate_calendar_data.py

For each loaded year it prints the holiday count, the freshness verdict, and the derived
last trading day for each of the twelve contract months — the fastest way to notice that a
holiday import is wrong, because a wrong holiday moves those dates visibly.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tfex.calendar import HolidayStore, TradingCalendar
from app.tfex.config import load_config
from app.tfex.errors import TfexError


def main() -> int:
    config = load_config()
    store = HolidayStore()
    calendar = TradingCalendar(config, store)
    now = datetime.now(calendar.timezone)

    years = store.available_years()
    if not years:
        print(f"No calendar data imported in {store.directory}.")
        print("See data/tfex/holidays/README.md for the import procedure.")
        return 1

    exit_code = 0
    for year in years:
        try:
            data = store.year(year)
        except TfexError as exc:
            print(f"{year}: FAILED TO LOAD - {exc}")
            exit_code = 1
            continue

        stale = data.provenance.is_stale(now)
        print(
            f"\n{year}: {len(data.holidays)} holidays, "
            f"verified={data.provenance.verified}, stale={stale}"
        )
        if data.shortened_sessions:
            early = [s.session_date.isoformat() for s in data.shortened_sessions]
            print(f"  shortened sessions: {early}")
        if data.effective_overrides:
            print(f"  approved overrides: {len(data.effective_overrides)}")

        for month in range(1, 13):
            try:
                expiry = calendar.contract_expiry(year, month, resolved_at=now)
            except TfexError as exc:
                print(f"  {year}-{month:02d}: unresolved - {exc}")
                exit_code = 1
                continue
            print(
                f"  {year}-{month:02d}: last trading day "
                f"{expiry.last_trading_date.isoformat()} "
                f"{expiry.last_trading_time.isoformat(timespec='minutes')} "
                f"[{expiry.source}]"
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
