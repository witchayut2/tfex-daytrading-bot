"""CSV import (data-readiness gate PART K).

The rule this module exists to enforce: **a naive timestamp requires a declared source
timezone.** Assuming UTC would shift every TFEX bar by seven hours, relabelling the morning
session as pre-open and the afternoon as post-close — and it would do so silently.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.tfex.errors import ConfigurationError
from app.tfex.marketdata.csv_loader import load_bars
from app.tfex.marketdata.manifest import (
    build_manifest,
    file_sha256,
    load_manifest,
    manifest_path_for,
    save_manifest,
)
from app.tfex.marketdata.models import BarInterval
from tests.tfex.conftest import BANGKOK

HEADER = "timestamp,symbol,open,high,low,close,volume"
ROWS = (
    "2026-12-23 09:45:00,S50Z26,1080.0,1080.5,1079.8,1080.2,120",
    "2026-12-23 09:46:00,S50Z26,1080.2,1080.6,1080.0,1080.4,95",
)


def write_csv(tmp_path: Path, *lines: str, name: str = "S50Z26_1m.csv") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_well_formed_file_loads(tmp_path: Path) -> None:
    path = write_csv(tmp_path, HEADER, *ROWS)
    result = load_bars(path, source_timezone="Asia/Bangkok")

    assert result.row_count == 2
    assert not result.findings
    first = result.bars[0]
    assert first.symbol == "S50Z26"
    assert first.timestamp == datetime(2026, 12, 23, 9, 45, tzinfo=BANGKOK)
    assert first.open == Decimal("1080.0")
    assert first.volume == 120


def test_a_missing_source_timezone_is_an_error_not_an_assumption(tmp_path: Path) -> None:
    path = write_csv(tmp_path, HEADER, *ROWS)
    with pytest.raises(ConfigurationError, match="never be assumed to be UTC"):
        load_bars(path, source_timezone=None)


def test_an_unknown_timezone_is_rejected(tmp_path: Path) -> None:
    path = write_csv(tmp_path, HEADER, *ROWS)
    with pytest.raises(ConfigurationError, match="unknown source timezone"):
        load_bars(path, source_timezone="Mars/Olympus_Mons")


def test_an_offset_bearing_timestamp_is_converted_not_reinterpreted(tmp_path: Path) -> None:
    """02:45Z is 09:45 in Bangkok. Reinterpreting rather than converting would be a 7h error."""
    path = write_csv(
        tmp_path,
        HEADER,
        "2026-12-23T02:45:00+00:00,S50Z26,1080.0,1080.5,1079.8,1080.2,120",
    )
    bar = load_bars(path, source_timezone="Asia/Bangkok").bars[0]
    assert bar.timestamp == datetime(2026, 12, 23, 9, 45, tzinfo=BANGKOK)


def test_a_trailing_z_is_understood(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path, HEADER, "2026-12-23T02:45:00Z,S50Z26,1080.0,1080.5,1079.8,1080.2,120"
    )
    assert load_bars(path, source_timezone="Asia/Bangkok").bars[0].timestamp.hour == 9


def test_a_separate_date_and_time_column_pair_works(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "date,time,symbol,open,high,low,close,volume",
        "2026-12-23,09:45:00,S50Z26,1080.0,1080.5,1079.8,1080.2,120",
    )
    bar = load_bars(path, source_timezone="Asia/Bangkok").bars[0]
    assert bar.timestamp == datetime(2026, 12, 23, 9, 45, tzinfo=BANGKOK)


def test_vendor_column_spellings_are_accepted(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "DateTime,Ticker,O,H,L,C,Vol,OI",
        "2026-12-23 09:45:00,s50z26,1080.0,1080.5,1079.8,1080.2,120,50000",
    )
    bar = load_bars(path, source_timezone="Asia/Bangkok").bars[0]
    assert bar.symbol == "S50Z26"
    assert bar.open_interest == 50_000


def test_a_missing_price_column_is_a_configuration_error(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "timestamp,symbol,open,high,low,volume", "x,y,1,1,1,1")
    with pytest.raises(ConfigurationError, match="missing required column"):
        load_bars(path, source_timezone="Asia/Bangkok")


def test_a_file_with_no_symbol_anywhere_is_refused(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "timestamp,open,high,low,close,volume",
        "2026-12-23 09:45:00,1080.0,1080.5,1079.8,1080.2,120",
    )
    with pytest.raises(ConfigurationError, match="does not know its contract"):
        load_bars(path, source_timezone="Asia/Bangkok")


def test_the_symbol_may_come_from_the_caller(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "timestamp,open,high,low,close,volume",
        "2026-12-23 09:45:00,1080.0,1080.5,1079.8,1080.2,120",
    )
    assert (
        load_bars(path, source_timezone="Asia/Bangkok", symbol="S50Z26").bars[0].symbol == "S50Z26"
    )


def test_bad_rows_are_reported_and_the_rest_still_load(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        HEADER,
        ROWS[0],
        "2026-12-23 09:46:00,S50Z26,1080.2,1080.6,1080.0,1080.4,not-a-number",
        "not-a-timestamp,S50Z26,1,1,1,1,1",
        ROWS[1],
    )
    result = load_bars(path, source_timezone="Asia/Bangkok")

    assert len(result.bars) == 2
    assert len(result.findings) == 2
    assert result.row_count == 4
    assert [f.line_number for f in result.findings] == [3, 4]


def test_thousands_separators_and_float_volumes_are_tolerated(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path, HEADER, '2026-12-23 09:45:00,S50Z26,"1,080.0",1080.5,1079.8,1080.2,120.0'
    )
    bar = load_bars(path, source_timezone="Asia/Bangkok").bars[0]
    assert bar.open == Decimal("1080.0")
    assert bar.volume == 120


def test_a_fractional_volume_is_rejected(tmp_path: Path) -> None:
    path = write_csv(tmp_path, HEADER, "2026-12-23 09:45:00,S50Z26,1080.0,1080.5,1079.8,1080.2,1.5")
    result = load_bars(path, source_timezone="Asia/Bangkok")
    assert not result.bars
    assert "not a whole number" in result.findings[0].message


def test_a_missing_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot read market-data file"):
        load_bars(tmp_path / "absent.csv", source_timezone="Asia/Bangkok")


# --- manifests ------------------------------------------------------------------------------


def test_a_manifest_round_trips(tmp_path: Path) -> None:
    path = write_csv(tmp_path, HEADER, *ROWS)
    bars = load_bars(path, source_timezone="Asia/Bangkok").bars

    manifest = build_manifest(
        path,
        dataset_id="s50z26-1m-test",
        source="unit test",
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        bars=bars,
        synthetic=True,
    )
    save_manifest(manifest, path)

    reloaded = load_manifest(path)
    assert reloaded.sha256 == file_sha256(path)
    assert reloaded.record_count == 2
    assert reloaded.trading_days == 1
    assert reloaded.synthetic
    assert manifest_path_for(path).name == "S50Z26_1m.csv.manifest.json"


def test_editing_the_raw_file_invalidates_the_manifest(tmp_path: Path) -> None:
    """Raw inputs are immutable; a changed checksum voids every result that cited them."""
    path = write_csv(tmp_path, HEADER, *ROWS)
    save_manifest(
        build_manifest(
            path,
            dataset_id="s50z26-1m-test",
            source="unit test",
            symbol="S50Z26",
            interval=BarInterval.ONE_MINUTE,
            source_timezone="Asia/Bangkok",
        ),
        path,
    )
    path.write_text("\n".join((HEADER, *ROWS, ROWS[1])) + "\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="has been modified"):
        load_manifest(path)


def test_a_file_without_a_manifest_is_refused(tmp_path: Path) -> None:
    path = write_csv(tmp_path, HEADER, *ROWS)
    with pytest.raises(ConfigurationError, match="no dataset manifest"):
        load_manifest(path)
