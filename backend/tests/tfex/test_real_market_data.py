"""Acceptance tests that require a real SET50 futures dataset (gate PART U).

Every test here is marked ``real_market_data`` and **skips** when no validated non-synthetic
dataset is present under ``backend/data/tfex/historical/normalized/<SYMBOL>/``. Skipping is not
passing. Structural real-data validity and the minimum-history requirement are deliberately
reported separately. The four-day parent proves only structural validity; its five-day
extended child proves both structural validity and minimum-history sufficiency.

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
from app.tfex.errors import ConfigurationError, RealMarketDataValidationRequired
from app.tfex.feeds.base import ReplayStatus
from app.tfex.feeds.csv_feed import load_csv_replay_input
from app.tfex.marketdata.acceptance import assess_tfex2_status, mark_tfex2_complete
from app.tfex.marketdata.csv_loader import LoadResult, load_bars
from app.tfex.marketdata.manifest import HISTORICAL_NORMALIZED_ROOT, file_sha256, load_manifest
from app.tfex.marketdata.models import (
    CheckStatus,
    DatasetManifest,
    ValidationOutcome,
    ValidationReport,
)
from app.tfex.marketdata.replay import ReplayEngine, ReplayRun, replay_digest
from app.tfex.marketdata.validation import MarketDataValidator
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine

_DATA_SUFFIXES = (".csv", ".txt")


def discover_datasets() -> list[tuple[Path, DatasetManifest]]:
    """Every normalized file that has a valid, non-synthetic manifest beside it."""
    found: list[tuple[Path, DatasetManifest]] = []
    if not HISTORICAL_NORMALIZED_ROOT.is_dir():
        return found
    for path in sorted(HISTORICAL_NORMALIZED_ROOT.rglob("*")):
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
            "no real SET50 futures dataset present under data/tfex/historical/normalized/. "
            "See docs/tfex_historical_data_sources.md for the safe acquisition workflow; "
            "absence of a dataset cannot satisfy structural or minimum-history readiness."
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


def test_real_data_valid_is_distinct_from_minimum_history_requirement(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    """Structural validity and minimum-history sufficiency remain separate evidence."""
    _, report = _report(dataset, real_config, real_calendar)
    _, manifest = dataset
    evidence = assess_tfex2_status([report])

    assert evidence.real_data_valid
    assert evidence.minimum_history_requirement_met is (
        manifest.minimum_dataset_requirement_met is True
    )
    if manifest.minimum_dataset_requirement_met is not True:
        assert report.outcome in {
            ValidationOutcome.PASS,
            ValidationOutcome.PASS_WITH_WARNINGS,
        }
        assert manifest.acquired_complete_trading_days is not None
        assert manifest.acquired_complete_trading_days < 5
    else:
        assert manifest.complete_trading_days == len(manifest.trading_dates)
        assert manifest.complete_trading_days >= 5
        assert manifest.acquired_complete_trading_days == manifest.complete_trading_days
        if manifest.historical_availability_status == ("EXTENDED_REAL_DATASET_MINIMUM_HISTORY_MET"):
            assert manifest.parent_dataset_id
            assert manifest.parent_normalized_sha256
            assert manifest.source_raw_capture_sha256s == tuple(
                capture.sha256 for capture in manifest.source_captures
            )
            assert set(manifest.new_raw_capture_sha256s).issubset(
                manifest.source_raw_capture_sha256s
            )


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


# --- 3-5, 10-12: TFEX-2 replay acceptance -----------------------------------------------


def _validated_replay(
    dataset: tuple[Path, DatasetManifest],
    config: TfexConfig,
    calendar: TradingCalendar,
) -> ReplayRun:
    _, report = _report(dataset, config, calendar)
    assert report.outcome is ValidationOutcome.PASS, report.render_text()
    path, _ = dataset
    return ReplayEngine.from_csv(
        path,
        SessionEngine(config, calendar),
        require_real=True,
    ).run_to_end()


def test_real_1m_bars_replay_with_manifest_identity(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    run = _validated_replay(dataset, real_config, real_calendar)
    _, manifest = dataset
    assert run.source_bar_count == manifest.record_count
    assert run.dataset_id == manifest.dataset_id
    assert run.dataset_sha256 == manifest.sha256
    assert {frame.event.bar.symbol for frame in run.frames} == {manifest.symbol}
    assert all(
        frame.event.continuous_session in {ContinuousSession.MORNING, ContinuousSession.AFTERNOON}
        for frame in run.frames
    )


def test_real_5m_aggregation_is_tfex_session_aligned(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    run = _validated_replay(dataset, real_config, real_calendar)
    _, manifest = dataset
    days = manifest.complete_trading_days or manifest.trading_days
    assert days is not None
    assert len(run.confirmed_5m) == days * 71
    assert all(bar.source_bar_count == 5 for bar in run.confirmed_5m)
    assert all(bar.open_time.date() == bar.close_time.date() for bar in run.confirmed_5m)
    assert all(bar.open_time.minute % 5 == 0 for bar in run.confirmed_5m)


def test_real_15m_aggregation_reanchors_at_afternoon_open(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    run = _validated_replay(dataset, real_config, real_calendar)
    _, manifest = dataset
    days = manifest.complete_trading_days or manifest.trading_days
    assert days is not None
    assert len(run.confirmed_15m) == days * 24
    afternoons = [bar for bar in run.confirmed_15m if bar.session is ContinuousSession.AFTERNOON]
    assert len(afternoons) == days * 13
    assert all(bar.open_time.time().minute % 15 == 0 for bar in afternoons)
    tails = [bar for bar in afternoons if bar.is_short_session_close_bucket]
    assert len(tails) == days
    assert all(bar.source_bar_count == 10 for bar in tails)


@pytest.mark.anti_repaint
def test_real_replay_is_deterministic_with_matching_hash(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    first = _validated_replay(dataset, real_config, real_calendar)
    second = _validated_replay(dataset, real_config, real_calendar)
    assert first.frames == second.frames
    assert first.digest == second.digest


@pytest.mark.anti_repaint
def test_real_batch_and_one_bar_incremental_replay_are_equivalent(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    batch = _validated_replay(dataset, real_config, real_calendar)
    path, _ = dataset
    incremental = ReplayEngine.from_csv(
        path,
        SessionEngine(real_config, real_calendar),
        require_real=True,
    )
    incremental.start()
    frames = []
    while incremental.status is ReplayStatus.RUNNING:
        frame = incremental.next_event()
        if frame is not None:
            frames.append(frame)
    assert tuple(frames) == batch.frames
    assert replay_digest(frames) == batch.digest


@pytest.mark.anti_repaint
def test_real_replay_prefix_is_stable(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    full = _validated_replay(dataset, real_config, real_calendar)
    path, _ = dataset
    source = load_csv_replay_input(path, require_real=True)
    prefix_length = min(420, len(source.bars))
    prefix = ReplayEngine(
        source.bars[:prefix_length],
        SessionEngine(real_config, real_calendar),
    ).run_to_end()
    assert prefix.frames == full.frames[:prefix_length]


def test_only_minimum_history_real_replay_can_complete_tfex2(
    dataset: tuple[Path, DatasetManifest],
    real_config: TfexConfig,
    real_calendar: TradingCalendar,
) -> None:
    _, report = _report(dataset, real_config, real_calendar)
    run = _validated_replay(dataset, real_config, real_calendar)
    _, manifest = dataset
    if manifest.minimum_dataset_requirement_met is True:
        evidence = mark_tfex2_complete([report], [run])
        assert evidence.minimum_history_requirement_met
    else:
        with pytest.raises(RealMarketDataValidationRequired, match="minimum five"):
            mark_tfex2_complete([report], [run])
