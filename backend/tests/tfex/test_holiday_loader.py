"""Holiday-data import and the refusal to guess (`CLAUDE_TFEX.md` sections 2 and 8)."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pytest

from app.tfex.calendar.holiday_loader import HolidayStore, load_holiday_year_file
from app.tfex.calendar.models import Holiday, HolidayCalendarYear, ShortenedSession
from app.tfex.errors import CalendarDataInvalidError, CalendarDataUnavailableError
from app.tfex.provenance import Provenance
from tests.tfex.conftest import BANGKOK, build_year


def write_year_file(directory: Path, year: int, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{year}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_payload(year: int = 2026) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "year": year,
        "timezone": "Asia/Bangkok",
        "provenance": {
            "source_name": "TFEX holidays",
            "source_url": "https://www.tfex.co.th/en/about/holiday",
            "retrieved_at": "2026-01-05T09:00:00+07:00",
            "verified": False,
        },
        "holidays": [
            {"holiday_date": f"{year}-01-01", "name": "fixture new year"},
        ],
    }


def test_an_unimported_year_raises_instead_of_assuming_no_holidays(tmp_path: Path) -> None:
    """The single most important behaviour in this module."""
    store = HolidayStore(tmp_path)
    with pytest.raises(CalendarDataUnavailableError, match="has not been imported"):
        store.year(2026)


def test_the_error_points_at_the_import_procedure(tmp_path: Path) -> None:
    store = HolidayStore(tmp_path)
    with pytest.raises(CalendarDataUnavailableError, match=r"data/tfex/holidays/README\.md"):
        store.year(2026)


def test_a_valid_year_file_loads(tmp_path: Path) -> None:
    path = write_year_file(tmp_path, 2026, valid_payload())
    loaded = load_holiday_year_file(path)

    assert loaded.year == 2026
    assert [h.holiday_date for h in loaded.holidays] == [date(2026, 1, 1)]
    assert loaded.provenance.source_name == "TFEX holidays"
    assert loaded.provenance.verified is False


def test_a_filename_that_disagrees_with_its_content_is_rejected(tmp_path: Path) -> None:
    payload = valid_payload(2026)
    path = write_year_file(tmp_path, 2027, payload)  # 2027.json declaring year 2026
    with pytest.raises(CalendarDataInvalidError, match="filename and"):
        load_holiday_year_file(path)


def test_an_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    payload = valid_payload() | {"schema_version": 2}
    path = write_year_file(tmp_path, 2026, payload)
    with pytest.raises(CalendarDataInvalidError, match="schema_version"):
        load_holiday_year_file(path)


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "2026.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CalendarDataInvalidError, match="not valid JSON"):
        load_holiday_year_file(path)


def test_a_holiday_from_the_wrong_year_is_rejected(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["holidays"].append({"holiday_date": "2025-12-25", "name": "wrong year"})
    path = write_year_file(tmp_path, 2026, payload)
    with pytest.raises(CalendarDataInvalidError, match="does not belong to calendar year"):
        load_holiday_year_file(path)


def test_duplicate_holiday_entries_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["holidays"].append({"holiday_date": "2026-01-01", "name": "duplicate"})
    path = write_year_file(tmp_path, 2026, payload)
    with pytest.raises(CalendarDataInvalidError, match="duplicate holiday entry"):
        load_holiday_year_file(path)


def test_a_date_cannot_be_both_a_holiday_and_a_shortened_session() -> None:
    with pytest.raises(ValueError, match="both as holidays and as shortened sessions"):
        HolidayCalendarYear(
            year=2026,
            provenance=Provenance(source_name="fixture"),
            holidays=(Holiday(holiday_date=date(2026, 1, 1), name="fixture"),),
            shortened_sessions=(
                ShortenedSession(
                    session_date=date(2026, 1, 1), afternoon_close=time(12, 30), reason="fixture"
                ),
            ),
        )


def test_a_shortened_session_must_actually_shorten_something() -> None:
    with pytest.raises(ValueError, match="must shorten something"):
        ShortenedSession(session_date=date(2026, 1, 1), reason="announcement")


def test_unknown_fields_in_a_year_file_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload() | {"holidayz": []}
    path = write_year_file(tmp_path, 2026, payload)
    with pytest.raises(CalendarDataInvalidError):
        load_holiday_year_file(path)


def test_available_years_lists_both_cached_and_on_disk_years(tmp_path: Path) -> None:
    write_year_file(tmp_path, 2027, valid_payload(2027))
    store = HolidayStore(tmp_path, preloaded=[build_year(2026)])
    assert store.available_years() == (2026, 2027)


def test_require_years_reports_every_missing_year_at_once(tmp_path: Path) -> None:
    store = HolidayStore(tmp_path, preloaded=[build_year(2026)])
    with pytest.raises(CalendarDataUnavailableError, match=r"\[2024, 2025\]"):
        store.require_years([2024, 2025, 2026])


def test_a_loaded_year_is_cached_and_does_not_change_underneath_a_run(tmp_path: Path) -> None:
    path = write_year_file(tmp_path, 2026, valid_payload())
    store = HolidayStore(tmp_path)
    first = store.year(2026)

    payload = valid_payload()
    payload["holidays"].append({"holiday_date": "2026-07-04", "name": "edited after load"})
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.year(2026) is first
    assert len(store.year(2026).holidays) == 1


def test_freshness_report_flags_stale_years() -> None:
    stale = build_year(
        2026,
        provenance=Provenance(
            source_name="fixture",
            retrieved_at=datetime(2020, 1, 1, tzinfo=BANGKOK),
            stale_after=datetime(2020, 7, 1, tzinfo=BANGKOK),
        ),
    )
    store = HolidayStore("/nonexistent", preloaded=[stale])
    report = store.freshness_report(datetime(2026, 8, 23, tzinfo=BANGKOK))
    assert report == {2026: True}
