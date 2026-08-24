"""Acceptance tests that require a real SET50 futures dataset (gate PART U).

Every test here is marked ``real_market_data`` and **skips** when no validated non-synthetic
dataset is present under ``backend/data/tfex/historical/raw/<SYMBOL>/``. Skipping is not
passing: `docs/tfex_data_readiness_gate.md` records the milestone status as
``TFEX2_FIXTURE_VALIDATED`` until these actually run.

Run them explicitly::

    uv run pytest -m real_market_data

The checks below are the ones the current codebase can perform. The remaining acceptance
tests from the gate - 1m/5m/15m aggregation, deterministic double replay with a matching
hash, and incremental equivalence - need the TFEX-2 replay engine and are listed at the
bottom of this module so they are added, not forgotten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tfex.calendar import HolidayStore, TradingCalendar
from app.tfex.config import TfexConfig, load_config
from app.tfex.errors import ConfigurationError
from app.tfex.marketdata.csv_loader import LoadResult, load_bars
from app.tfex.marketdata.manifest import HISTORICAL_RAW_ROOT, file_sha256, load_manifest
from app.tfex.marketdata.models import (
    CheckStatus,
    DatasetManifest,
    ValidationOutcome,
    ValidationReport,
)
from app.tfex.marketdata.validation import MarketDataValidator

_DATA_SUFFIXES = (".csv", ".txt")


def discover_datasets() -> list[tuple[Path, DatasetManifest]]:
    """Every raw file that has a valid, non-synthetic manifest beside it."""
    found: list[tuple[Path, DatasetManifest]] = []
    if not HISTORICAL_RAW_ROOT.is_dir():
        return found
    for path in sorted(HISTORICAL_RAW_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _DATA_SUFFIXES:
            continue
        try:
            manifest = load_manifest(path)
        except ConfigurationError:
            continue
        if manifest.is_real_market_data:
            found.append((path, manifest))
    return found


DATASETS = discover_datasets()

pytestmark = [
    pytest.mark.real_market_data,
    pytest.mark.skipif(
        not DATASETS,
        reason=(
            "no real SET50 futures dataset present under data/tfex/historical/raw/. "
            "See docs/tfex_historical_data_sources.md for how to acquire one; the gate "
            "status is REAL_1M_DATA_BLOCKED until then."
        ),
    ),
]


@pytest.fixture(scope="module")
def real_config() -> TfexConfig:
    return load_config()


@pytest.fixture(scope="module")
def real_calendar(real_config: TfexConfig) -> TradingCalendar:
    """The *imported* calendar, not the synthetic fixture one - this is real-data territory."""
    return TradingCalendar(real_config, HolidayStore())


_PARAMS: list[tuple[Path, DatasetManifest] | None] = list(DATASETS) or [None]


@pytest.fixture(
    params=_PARAMS,
    ids=[m.dataset_id for _, m in DATASETS] or ["no-dataset"],
)
def dataset(request: pytest.FixtureRequest) -> tuple[Path, DatasetManifest]:
    if request.param is None:  # unreachable while the module-level skipif holds
        pytest.skip("no real dataset available")
    path, manifest = request.param
    return path, manifest


def _report(
    dataset: tuple[Path, DatasetManifest],
    config: TfexConfig,
    calendar: TradingCalendar,
) -> tuple[LoadResult, ValidationReport]:
    path, manifest = dataset
    loaded = load_bars(path, source_timezone=manifest.source_timezone, symbol=manifest.symbol)
    validator = MarketDataValidator(config, calendar)
    return loaded, validator.validate(
        loaded.bars,
        symbol=manifest.symbol,
        interval=manifest.interval,
        file_path=str(path),
        sha256=file_sha256(path),
        manifest=manifest,
        load_findings=tuple(loaded.findings),
        row_count=loaded.row_count,
    )


# --- 1. load a real S50 contract ---------------------------------------------------------


def test_the_dataset_loads(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    loaded, _ = _report(dataset, real_config, real_calendar)
    assert loaded.bars, "the file parsed to zero bars"
    assert not loaded.findings, f"{len(loaded.findings)} unparseable row(s)"


def test_the_manifest_still_describes_the_file(dataset: tuple[Path, DatasetManifest]) -> None:
    """A checksum mismatch means the immutable raw input was edited."""
    path, manifest = dataset
    assert file_sha256(path) == manifest.sha256


def test_the_dataset_is_not_synthetic(dataset: tuple[Path, DatasetManifest]) -> None:
    _, manifest = dataset
    assert manifest.is_real_market_data
    assert manifest.source.strip()


# --- 2. validate the full dataset --------------------------------------------------------


def test_the_dataset_passes_validation(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    _, report = _report(dataset, real_config, real_calendar)
    assert report.outcome in {
        ValidationOutcome.PASS,
        ValidationOutcome.PASS_WITH_WARNINGS,
    }, report.render_text()


# --- 6-9. the invariants that must hold on real data --------------------------------------


@pytest.mark.anti_repaint
def test_no_bar_crosses_the_midday_break(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    _, report = _report(dataset, real_config, real_calendar)
    check = report.check("session_boundaries")
    assert check is not None
    assert check.details.get("midday_break_crossings", 0) == 0


def test_contract_identity_is_preserved(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    _, report = _report(dataset, real_config, real_calendar)
    check = report.check("contract_identity")
    assert check is not None and check.status is CheckStatus.PASS


def test_no_data_exists_past_expiry(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    _, report = _report(dataset, real_config, real_calendar)
    check = report.check("expiry")
    assert check is not None
    assert check.status is CheckStatus.PASS, check.summary


def test_no_bar_lies_outside_a_known_session(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    _, report = _report(dataset, real_config, real_calendar)
    check = report.check("session_boundaries")
    assert check is not None
    assert check.details.get("UNKNOWN", 0) == 0
    assert check.details.get("NON_TRADING_DAY", 0) == 0


@pytest.mark.anti_repaint
def test_validation_is_deterministic(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    """Two runs over the same bytes must reach the same verdict, check for check."""
    _, first = _report(dataset, real_config, real_calendar)
    _, second = _report(dataset, real_config, real_calendar)

    assert [(c.name, c.status, c.summary) for c in first.checks] == [
        (c.name, c.status, c.summary) for c in second.checks
    ]
    assert first.outcome is second.outcome


# --- 3-5, 10-12: awaiting the TFEX-2 replay engine ----------------------------------------
#
# These acceptance tests cannot be written until the engine exists. Listed rather than
# stubbed, so they are added when it lands:
#
#   3.  build TFEX session-aware 1m bars from the raw dataset
#   4.  derive 5m bars and verify TFEX-aligned buckets
#   5.  derive 15m bars and verify the afternoon bucket starts at 13:45
#   10. run the replay deterministically twice
#   11. compare the replay hash across the two runs
#   12. incremental equivalence: prefix calculation == one-candle-at-a-time replay
