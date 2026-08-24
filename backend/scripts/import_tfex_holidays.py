"""Import the official TFEX holiday calendar for one or more years.

Source of truth: the Thailand Futures Exchange's own holiday endpoint, the one the published
holiday page fetches. Generic Thai government holiday lists, bank holidays, Google Calendar
and broker articles are **not** used — the exchange declares additional special holidays that
those lists do not carry, and a missing closure moves the last business day of a contract
month, which moves the last trading day, which moves the expiry gate.

Both the English and Thai lists are retrieved and cross-checked against each other. Raw
responses are written verbatim and never rewritten; their SHA-256 is the provenance.

Usage::

    uv run python scripts/import_tfex_holidays.py --year 2026
    uv run python scripts/import_tfex_holidays.py --year 2025 --year 2026 --year 2027
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.tfex.calendar.models import Holiday, HolidayCalendarYear, HolidayType
from app.tfex.config import load_config
from app.tfex.provenance import Provenance
from scripts.data_sources.tfex_web import FetchError, RawResponse, TfexWebClient

OFFICIAL_ROOT = BACKEND_ROOT / "data" / "tfex" / "official" / "holidays"
STORE_ROOT = BACKEND_ROOT / "data" / "tfex" / "holidays"

SOURCE_ID = "tfex-holiday"
AUTHORITY = "Thailand Futures Exchange"
SOURCE_TYPE = "OFFICIAL_EXCHANGE"
PARSER_VERSION = "tfex-holiday-parser/1"
IMPORTER_VERSION = "import_tfex_holidays/1"

#: Marks an exchange-announced extra closure rather than a standing annual holiday. Late
#: announcements are what invalidate a cached calendar, so they are typed differently.
_SPECIAL_MARKERS = ("special holiday", "additional")


@dataclass(frozen=True, slots=True)
class ParsedHoliday:
    holiday_date: date
    name_en: str
    name_th: str
    holiday_type: HolidayType
    raw_en: str
    raw_th: str


def _classify(name_en: str) -> HolidayType:
    lowered = name_en.lower()
    if any(marker in lowered for marker in _SPECIAL_MARKERS):
        return HolidayType.SPECIAL_HOLIDAY
    return HolidayType.FULL_CLOSURE


def _rows(response: RawResponse) -> list[dict[str, Any]]:
    payload = response.json()
    if not isinstance(payload, list):
        raise FetchError(f"{response.url} returned {type(payload).__name__}, expected a list")
    return payload


def parse_year(year: int, english: RawResponse, thai: RawResponse) -> list[ParsedHoliday]:
    """Parse and cross-check the two language variants of one year.

    The two lists must describe the same dates. A mismatch means the source changed between
    the two requests or the endpoint is not what it appears to be; either way the import
    stops rather than guessing which list to believe.
    """
    en_rows = _rows(english)
    th_rows = _rows(thai)

    en_by_date: dict[date, str] = {}
    for row in en_rows:
        stamp = str(row["date"])
        parsed = datetime.fromisoformat(stamp).date()
        if parsed.year != year:
            raise FetchError(f"{english.url} returned {parsed} which is not in {year}")
        if parsed in en_by_date:
            raise FetchError(f"{english.url} lists {parsed} twice")
        en_by_date[parsed] = str(row["description"]).strip()

    th_by_date: dict[date, str] = {}
    for row in th_rows:
        parsed = datetime.fromisoformat(str(row["date"])).date()
        th_by_date[parsed] = str(row["description"]).strip()

    if set(en_by_date) != set(th_by_date):
        only_en = sorted(set(en_by_date) - set(th_by_date))
        only_th = sorted(set(th_by_date) - set(en_by_date))
        raise FetchError(
            f"English and Thai holiday lists for {year} disagree; only-EN={only_en}, "
            f"only-TH={only_th}"
        )

    return [
        ParsedHoliday(
            holiday_date=day,
            name_en=en_by_date[day].rstrip(" *").strip(),
            name_th=th_by_date[day].rstrip(" *").strip(),
            holiday_type=_classify(en_by_date[day]),
            raw_en=en_by_date[day],
            raw_th=th_by_date[day],
        )
        for day in sorted(en_by_date)
    ]


def write_official_capture(
    year: int,
    english: RawResponse,
    thai: RawResponse,
    remark: RawResponse | None,
    holidays: list[ParsedHoliday],
    *,
    stale_after_days: int,
) -> Path:
    """Write the immutable raw capture, the normalized view, and the provenance record."""
    directory = OFFICIAL_ROOT / str(year)
    directory.mkdir(parents=True, exist_ok=True)

    (directory / "raw.en.json").write_bytes(english.content)
    (directory / "raw.th.json").write_bytes(thai.content)
    if remark is not None:
        (directory / "raw.remark.json").write_bytes(remark.content)

    normalized = {
        "exchange": "TFEX",
        "year": year,
        "timezone": "Asia/Bangkok",
        "holidays": [
            {
                "date": h.holiday_date.isoformat(),
                "name_en": h.name_en,
                "name_th": h.name_th,
                "holiday_type": h.holiday_type.value,
                "source_id": f"{SOURCE_ID}-{year}",
                "raw_description_en": h.raw_en,
                "raw_description_th": h.raw_th,
            }
            for h in holidays
        ],
    }
    _write_json(directory / "normalized.json", normalized)

    provenance = {
        "source_id": f"{SOURCE_ID}-{year}",
        "authority": AUTHORITY,
        "source_type": SOURCE_TYPE,
        "source_title": "TFEX Holiday",
        "year": year,
        "status": "VERIFIED_OFFICIAL",
        "verification_basis": (
            "retrieved directly from the exchange's own holiday endpoint and cross-checked "
            "between the English and Thai language variants"
        ),
        "retrieved_at": english.retrieved_at.isoformat(),
        "effective_year": year,
        "stale_after": (english.retrieved_at + timedelta(days=stale_after_days)).isoformat(),
        "parser_version": PARSER_VERSION,
        "importer_version": IMPORTER_VERSION,
        "holiday_count": len(holidays),
        "special_holiday_count": sum(
            1 for h in holidays if h.holiday_type is HolidayType.SPECIAL_HOLIDAY
        ),
        "requests": {
            "en": english.describe(),
            "th": thai.describe(),
            **({"remark": remark.describe()} if remark is not None else {}),
        },
        "human_page": "https://www.tfex.co.th/en/about/holiday",
        "notes": (
            "Raw files in this directory are immutable captures. Their SHA-256 is recorded "
            "above; do not edit them. Regenerate by re-running the importer, which writes a "
            "new capture and a new retrieved_at."
        ),
    }
    _write_json(directory / "provenance.json", provenance)
    return directory


def write_store_file(
    year: int,
    holidays: list[ParsedHoliday],
    english: RawResponse,
    *,
    stale_after_days: int,
    imported_by: str,
) -> Path:
    """Write the file `HolidayStore` reads, preserving any contract dates already imported.

    `published_contract_dates`, `shortened_sessions` and `overrides` are owned by other
    importers and by operators. Re-running the holiday import must not silently discard them.
    """
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    path = STORE_ROOT / f"{year}.json"

    preserved: dict[str, Any] = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for key in ("published_contract_dates", "shortened_sessions", "overrides"):
            if existing.get(key):
                preserved[key] = existing[key]

    year_data = HolidayCalendarYear(
        year=year,
        provenance=Provenance(
            source_name=f"TFEX official holiday calendar {year}",
            source_url="https://www.tfex.co.th/en/about/holiday",  # type: ignore[arg-type]
            retrieved_at=english.retrieved_at,
            effective_date=date(year, 1, 1),
            fingerprint="sha256:" + english.sha256,
            verified=True,
            stale_after=english.retrieved_at + timedelta(days=stale_after_days),
            imported_by=imported_by,
            note=(
                f"{len(holidays)} holidays from the exchange endpoint; EN/TH cross-checked; "
                f"see data/tfex/official/holidays/{year}/provenance.json"
            ),
        ),
        holidays=tuple(
            Holiday(
                holiday_date=h.holiday_date,
                name=h.name_en,
                holiday_type=h.holiday_type,
                note=h.name_th,
            )
            for h in holidays
        ),
    )

    payload = json.loads(year_data.model_dump_json(exclude_none=False))
    payload.update(preserved)
    _write_json(path, payload)
    return path


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def import_year(
    client: TfexWebClient, year: int, *, stale_after_days: int, imported_by: str
) -> int:
    english = client.holidays(year, "en")
    thai = client.holidays(year, "th")
    try:
        remark: RawResponse | None = client.holiday_remark("en")
    except FetchError:
        remark = None  # the remark endpoint is supplementary, not authoritative

    holidays = parse_year(year, english, thai)
    if not holidays:
        raise FetchError(
            f"the exchange returned an empty holiday list for {year}; refusing to import an "
            f"empty year, which would silently make every weekday a trading day"
        )

    directory = write_official_capture(
        year, english, thai, remark, holidays, stale_after_days=stale_after_days
    )
    store_path = write_store_file(
        year, holidays, english, stale_after_days=stale_after_days, imported_by=imported_by
    )

    specials = [h for h in holidays if h.holiday_type is HolidayType.SPECIAL_HOLIDAY]
    print(f"\n{year}: imported {len(holidays)} official TFEX holidays")
    print(f"  raw capture   {directory}")
    print(f"  store file    {store_path}")
    print(f"  sha256(en)    {english.sha256}")
    print(f"  sha256(th)    {thai.sha256}")
    print(
        f"  special       {len(specials)} "
        + ", ".join(h.holiday_date.isoformat() for h in specials)
    )
    for holiday in holidays:
        marker = "*" if holiday.holiday_type is HolidayType.SPECIAL_HOLIDAY else " "
        print(f"    {marker} {holiday.holiday_date.isoformat()}  {holiday.name_en}")
    return len(holidays)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, action="append", required=True, help="year to import")
    parser.add_argument(
        "--imported-by", default="data-readiness-gate", help="recorded in the provenance"
    )
    args = parser.parse_args(argv)

    config = load_config()
    stale_after_days = config.metadata.holiday_data_stale_after_days

    client = TfexWebClient()
    failures: list[str] = []
    for year in sorted(set(args.year)):
        try:
            import_year(
                client, year, stale_after_days=stale_after_days, imported_by=args.imported_by
            )
        except FetchError as exc:
            failures.append(f"{year}: {exc}")
            print(f"\n{year}: IMPORT FAILED - {exc}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} year(s) failed to import.", file=sys.stderr)
        return 1
    print(f"\nGenerated at {datetime.now(UTC).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
