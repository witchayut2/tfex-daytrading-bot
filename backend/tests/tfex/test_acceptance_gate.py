"""The synthetic-promotion guard (data-readiness gate PART V).

One rule, tested from several directions: **fixtures alone can never mark TFEX-2 complete.**
A suite that passes on data its author invented has proved the code matches the author's
expectations, not that it survives the market.
"""

from __future__ import annotations

from datetime import UTC, datetime

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


def dataset(
    dataset_id: str, *, synthetic: bool, source: str = "Settrade Open API"
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        source="unit-test fixture" if synthetic else source,
        original_filename=f"{dataset_id}.csv",
        sha256="a" * 64,
        symbol="S50Z26",
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        record_count=355,
        synthetic=synthetic,
    )


def report(
    dataset_id: str, *, synthetic: bool, status: CheckStatus = CheckStatus.PASS
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
        manifest=dataset(dataset_id, synthetic=synthetic),
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
        [report("fixture-a", synthetic=True), report("s50z26-1m", synthetic=False)]
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
    assert mark_tfex2_complete([warned]).real_data_validated


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
