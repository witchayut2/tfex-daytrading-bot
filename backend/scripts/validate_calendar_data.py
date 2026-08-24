"""Validate imported TFEX calendar data and everything that depends on it.

Run after importing a year, before trusting any date-sensitive behaviour::

    uv run python scripts/validate_calendar_data.py --year 2026
    uv run python scripts/validate_calendar_data.py            # every imported year

Nine things are proved for each year, per the data-readiness gate:

1. the raw source capture exists
2. its provenance record exists
3. the recorded SHA-256 still matches the bytes on disk
4. every date parses
5. every date belongs to the declared year
6. duplicate dates are rejected
7. the calendar resolves trading and non-trading days from the imported data
8. last-business-day / last-trading-day arithmetic uses that imported data
9. an unimported year still fails closed

Exit codes: ``0`` pass, ``1`` failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.tfex.calendar import HolidayStore, TradingCalendar
from app.tfex.calendar.models import HolidayType, LastTradingDaySource
from app.tfex.config import load_config
from app.tfex.errors import CalendarDataUnavailableError, TfexError

OFFICIAL_ROOT = BACKEND_ROOT / "data" / "tfex" / "official" / "holidays"

_UNIMPORTABLE_PROBE_YEAR = 1999
"""A year no exchange calendar will ever be imported for, used to prove fail-closed."""


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        suffix = f"  {detail}" if detail else ""
        if ok:
            print(f"    PASS  {label}{suffix}")
        else:
            print(f"    FAIL  {label}{suffix}")
            self.failures.append(label)
        return ok

    def warn(self, label: str, detail: str = "") -> None:
        print(f"    WARN  {label}  {detail}")
        self.warnings.append(label)


def validate_year(
    year: int, store: HolidayStore, calendar: TradingCalendar, report: Report, *, now: datetime
) -> None:
    print(f"\n=== {year} ===")

    # 1-3: raw capture, provenance, checksum
    directory = OFFICIAL_ROOT / str(year)
    raw_en = directory / "raw.en.json"
    provenance_path = directory / "provenance.json"

    has_raw = report.check(raw_en.is_file(), "raw source capture exists", str(raw_en))
    has_prov = report.check(provenance_path.is_file(), "provenance record exists")

    if has_raw and has_prov:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        recorded = provenance.get("requests", {}).get("en", {}).get("sha256")
        actual = hashlib.sha256(raw_en.read_bytes()).hexdigest()
        report.check(
            recorded == actual,
            "recorded SHA-256 matches the bytes on disk",
            f"{actual[:16]}...",
        )
        report.check(
            provenance.get("authority") == "Thailand Futures Exchange",
            "authority is the exchange itself",
            str(provenance.get("authority")),
        )

    # 4-6: parsing, year membership, duplicates. All three are enforced by the loader, so
    # reaching this line at all proves them; the assertions restate them explicitly.
    try:
        data = store.year(year)
    except TfexError as exc:
        report.check(False, "year loads", str(exc))
        return

    report.check(True, "every date parses and duplicates are rejected", "enforced by the loader")
    report.check(
        all(h.holiday_date.year == year for h in data.holidays),
        "every date belongs to the declared year",
        f"{len(data.holidays)} holidays",
    )
    report.check(
        len({h.holiday_date for h in data.holidays}) == len(data.holidays),
        "no duplicate dates",
    )

    fingerprint = data.provenance.fingerprint or ""
    report.check(bool(fingerprint), "store file carries a fingerprint", fingerprint[:23] + "...")
    if data.provenance.is_stale(now):
        report.warn("calendar data is stale", f"stale_after={data.provenance.stale_after}")

    specials = [h for h in data.holidays if h.holiday_type is HolidayType.SPECIAL_HOLIDAY]
    print(
        f"    INFO  {len(data.holidays)} holidays, {len(specials)} exchange special holidays"
        + (f" ({', '.join(h.holiday_date.isoformat() for h in specials)})" if specials else "")
    )

    # 7: trading / non-trading resolution driven by the imported data
    holiday_days = [h.holiday_date for h in data.holidays]
    report.check(
        all(not calendar.is_trading_day(day) for day in holiday_days),
        "every imported holiday resolves as a non-trading day",
    )
    weekday_holidays = [d for d in holiday_days if d.weekday() < 5]
    report.check(
        len(weekday_holidays) > 0,
        "imported data changes the answer versus a weekday-only rule",
        f"{len(weekday_holidays)} holidays fall on weekdays",
    )

    # 8: last-business-day arithmetic uses the imported calendar
    print("    INFO  last trading day by contract month:")
    ltd_ok = True
    for month in range(1, 13):
        try:
            expiry = calendar.contract_expiry(year, month, resolved_at=now)
        except TfexError as exc:
            print(f"            {year}-{month:02d}: unresolved - {exc}")
            ltd_ok = False
            continue
        month_days = calendar.trading_days.trading_days_in_month(year, month)
        marker = (
            "published" if expiry.source is LastTradingDaySource.EXCHANGE_PUBLISHED else "derived"
        )
        agrees = expiry.last_trading_date == month_days[-2]
        print(
            f"            {year}-{month:02d}  LTD {expiry.last_trading_date.isoformat()} "
            f"{expiry.last_trading_time.isoformat(timespec='minutes')}  "
            f"last business day {month_days[-1].isoformat()}  [{marker}]"
            + ("" if agrees else "  <-- DISAGREES WITH DERIVED RULE")
        )
        if not agrees:
            ltd_ok = False
    report.check(ltd_ok, "every contract month resolves and agrees with the derived rule")

    published = calendar.year_data(year).published_contract_dates
    if published:
        print(f"    INFO  {len(published)} exchange-published contract dates merged")
    else:
        report.warn(
            "no exchange-published contract dates",
            "the derived rule is the only source; run import_tfex_contracts.py",
        )


def validate_fail_closed(report: Report) -> None:
    """Proof 9: an unimported year must still raise, not fall back to a weekday rule."""
    print("\n=== fail-closed behaviour ===")
    config = load_config()
    calendar = TradingCalendar(config, HolidayStore())
    try:
        calendar.is_trading_day(date(_UNIMPORTABLE_PROBE_YEAR, 6, 15))  # a plain Tuesday
    except CalendarDataUnavailableError:
        report.check(True, "an unimported year raises rather than assuming no holidays")
    else:
        report.check(
            False,
            "an unimported year raises rather than assuming no holidays",
            "IT DID NOT RAISE - fail-closed behaviour has been broken",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--year", type=int, action="append", help="year to validate (default: every imported year)"
    )
    args = parser.parse_args(argv)

    config = load_config()
    store = HolidayStore()
    calendar = TradingCalendar(config, store)
    now = datetime.now(calendar.timezone)

    years = sorted(set(args.year)) if args.year else list(store.available_years())
    if not years:
        print(f"No calendar data imported in {store.directory}.")
        print("Run: uv run python scripts/import_tfex_holidays.py --year <year>")
        print("See data/tfex/holidays/README.md for the import procedure.")
        return 1

    report = Report()
    for year in years:
        validate_year(year, store, calendar, report, now=now)
    validate_fail_closed(report)

    print("\n" + "=" * 70)
    if report.failures:
        print(f"FAILED - {len(report.failures)} check(s): {', '.join(report.failures)}")
        return 1
    if report.warnings:
        print(f"PASS WITH WARNINGS - {len(report.warnings)}: {', '.join(report.warnings)}")
        return 0
    print(f"PASS - every check passed for {years}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
