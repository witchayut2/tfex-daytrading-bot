"""The synthetic-promotion guard (data-readiness gate PART V).

One rule, tested from several directions: **fixtures alone can never mark TFEX-2 complete.**
A suite that passes on data its author invented has proved the code matches the author's
expectations, not that it survives the market.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

import pytest

from app.tfex.errors import RealMarketDataValidationRequired
from app.tfex.marketdata import Tfex2Status, assess_tfex2_status, mark_tfex2_complete
from app.tfex.marketdata.models import (
    BarInterval,
    CheckResult,
    CheckStatus,
    DatasetManifest,
    ValidationOutcome,
    ValidationReport,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


@dataclass(frozen=True)
class FakeReplayRun:
    symbol: str
    source_bar_count: int
    frames: tuple[object, ...]
    confirmed_5m: tuple[object, ...]
    confirmed_15m: tuple[object, ...]
    digest: str
    dataset_id: str | None
    dataset_sha256: str | None


def replay(dataset_id: str, *, rows: int = 355) -> FakeReplayRun:
    marker = object()
    return FakeReplayRun(
        symbol="S50Z26",
        source_bar_count=rows,
        frames=(marker,) * rows,
        confirmed_5m=(marker,),
        confirmed_15m=(marker,),
        digest="b" * 64,
        dataset_id=dataset_id,
        dataset_sha256="a" * 64,
    )


def dataset(
    dataset_id: str,
    *,
    synthetic: bool,
    source: str = "Settrade Open API",
    minimum_history_met: bool | None = None,
) -> DatasetManifest:
    if minimum_history_met is None:
        minimum_history_met = not synthetic
    return DatasetManifest(
        dataset_id=dataset_id,
        source="unit-test fixture" if synthetic else source,
        original_filename=f"{dataset_id}.csv",
        sha256="a" * 64,
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        record_count=355,
        acquired_complete_trading_days=5 if minimum_history_met else None,
        minimum_dataset_requirement_met=minimum_history_met,
        trading_dates=(
            (
                date(2026, 9, 7),
                date(2026, 9, 8),
                date(2026, 9, 9),
                date(2026, 9, 10),
                date(2026, 9, 11),
            )
            if minimum_history_met
            else ()
        ),
        complete_trading_days=5 if minimum_history_met else None,
        synthetic=synthetic,
    )


def report(
    dataset_id: str,
    *,
    synthetic: bool,
    status: CheckStatus = CheckStatus.PASS,
    minimum_history_met: bool | None = None,
) -> ValidationReport:
    return ValidationReport(
        dataset_id=dataset_id,
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        file_path=f"{dataset_id}.csv",
        sha256="a" * 64,
        row_count=355,
        checks=(CheckResult("everything", status, "fixture"),),
        validator_version="test",
        generated_at=NOW,
        manifest=dataset(
            dataset_id,
            synthetic=synthetic,
            minimum_history_met=minimum_history_met,
        ),
    )


def test_synthetic_data_alone_cannot_mark_tfex2_complete() -> None:
    with pytest.raises(RealMarketDataValidationRequired, match="at least one validated real"):
        mark_tfex2_complete(
            [report("fixture-a", synthetic=True), report("fixture-b", synthetic=True)]
        )


def test_no_data_at_all_cannot_mark_tfex2_complete() -> None:
    with pytest.raises(RealMarketDataValidationRequired):
        mark_tfex2_complete([])


def test_a_validated_real_dataset_promotes_the_milestone() -> None:
    evidence = mark_tfex2_complete(
        [report("fixture-a", synthetic=True), report("s50z26-1m", synthetic=False)],
        [replay("s50z26-1m")],
    )

    assert evidence.status is Tfex2Status.REAL_DATA_VALIDATED
    assert evidence.real_datasets == ("s50z26-1m",)
    assert evidence.synthetic_datasets == ("fixture-a",)


def test_a_rejected_real_dataset_does_not_count() -> None:
    """Passing validation is part of the requirement, not a separate one."""
    rejected = report("s50z26-1m", synthetic=False, status=CheckStatus.FAIL)
    assert rejected.outcome is ValidationOutcome.REJECTED

    with pytest.raises(RealMarketDataValidationRequired):
        mark_tfex2_complete([rejected])


def test_a_real_dataset_with_warnings_still_counts() -> None:
    warned = report("s50z26-1m", synthetic=False, status=CheckStatus.WARNING)
    assert warned.outcome is ValidationOutcome.PASS_WITH_WARNINGS
    assert mark_tfex2_complete([warned], [replay("s50z26-1m")]).real_data_validated


def test_data_readiness_without_a_matching_replay_cannot_complete_tfex2() -> None:
    ready = report("s50z26-1m", synthetic=False)
    with pytest.raises(RealMarketDataValidationRequired, match="data readiness alone"):
        mark_tfex2_complete([ready])

    wrong_hash = replace(replay("s50z26-1m"), dataset_sha256="c" * 64)
    with pytest.raises(RealMarketDataValidationRequired, match="matching real replay"):
        mark_tfex2_complete([ready], [wrong_hash])


def test_valid_four_day_real_dataset_is_interim_and_cannot_complete_tfex2() -> None:
    interim = report(
        "s50u26-four-days",
        synthetic=False,
        minimum_history_met=False,
    )

    evidence = assess_tfex2_status([interim])

    assert evidence.status is Tfex2Status.INTERIM_REAL_DATA_VALIDATED
    assert evidence.real_data_valid
    assert not evidence.minimum_history_requirement_met
    assert evidence.real_datasets == ("s50u26-four-days",)
    assert evidence.interim_real_datasets == ("s50u26-four-days",)
    with pytest.raises(RealMarketDataValidationRequired, match="minimum five"):
        mark_tfex2_complete([interim])


def test_a_boolean_without_explicit_five_day_dates_cannot_satisfy_the_gate() -> None:
    manifest = DatasetManifest(
        dataset_id="unsupported-boolean-only-claim",
        source="Settrade Open API",
        original_filename="unsupported.csv",
        sha256="a" * 64,
        symbol="S50U26",
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        record_count=1775,
        acquired_complete_trading_days=5,
        minimum_dataset_requirement_met=True,
        synthetic=False,
    )
    unsupported = ValidationReport(
        dataset_id=manifest.dataset_id,
        symbol=manifest.symbol,
        interval=manifest.interval,
        file_path=manifest.original_filename,
        sha256=manifest.sha256,
        row_count=manifest.record_count,
        checks=(CheckResult("everything", CheckStatus.PASS, "fixture"),),
        validator_version="test",
        generated_at=NOW,
        manifest=manifest,
    )

    evidence = assess_tfex2_status([unsupported])

    assert evidence.status is Tfex2Status.INTERIM_REAL_DATA_VALIDATED
    assert not evidence.minimum_history_requirement_met


def test_a_dataset_without_a_manifest_cannot_count_as_real() -> None:
    anonymous = ValidationReport(
        dataset_id="anonymous",
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        file_path="anonymous.csv",
        sha256="a" * 64,
        row_count=355,
        checks=(CheckResult("everything", CheckStatus.PASS, "fine"),),
        validator_version="test",
        generated_at=NOW,
        manifest=None,
    )
    with pytest.raises(RealMarketDataValidationRequired):
        mark_tfex2_complete([anonymous])


@pytest.mark.parametrize("source", ["   ", "UNVERIFIED - fill this in", "unverified"])
def test_a_manifest_without_a_named_source_is_not_real_data(source: str) -> None:
    """A starter manifest the validator generated must not graduate into evidence."""
    blank = DatasetManifest(
        dataset_id="blank",
        source=source,
        original_filename="blank.csv",
        sha256="a" * 64,
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        record_count=1,
        synthetic=False,
    )
    assert not blank.source_is_verified
    assert not blank.is_real_market_data


def test_a_placeholder_source_cannot_mark_tfex2_complete() -> None:
    placeholder = ValidationReport(
        dataset_id="starter",
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        file_path="starter.csv",
        sha256="a" * 64,
        row_count=355,
        checks=(CheckResult("everything", CheckStatus.PASS, "fine"),),
        validator_version="test",
        generated_at=NOW,
        manifest=DatasetManifest(
            dataset_id="starter",
            source="UNVERIFIED - fill this in",
            original_filename="starter.csv",
            sha256="a" * 64,
            symbol="S50Z26",
            interval=BarInterval.ONE_MINUTE,
            source_timezone="Asia/Bangkok",
            record_count=355,
            synthetic=False,
        ),
    )
    with pytest.raises(RealMarketDataValidationRequired):
        mark_tfex2_complete([placeholder])


# --- the non-raising view ------------------------------------------------------------------


def test_assessment_reports_status_without_raising() -> None:
    evidence = assess_tfex2_status([report("fixture-a", synthetic=True)])

    assert evidence.status is Tfex2Status.FIXTURE_VALIDATED
    assert not evidence.real_data_validated
    assert any("synthetic" in reason for reason in evidence.reasons)


def test_an_empty_assessment_is_not_started() -> None:
    assert assess_tfex2_status([]).status is Tfex2Status.NOT_STARTED


def test_the_refusal_explains_what_is_missing() -> None:
    with pytest.raises(RealMarketDataValidationRequired) as excinfo:
        mark_tfex2_complete([report("fixture-a", synthetic=True)])

    message = str(excinfo.value)
    assert "TFEX2_FIXTURE_VALIDATED" in message
    assert "fixture-a" in message
