"""The gate that stops synthetic data being mistaken for market validation.

Synthetic fixtures are necessary — unit tests, edge cases, fault injection and anti-repaint
proofs all need data whose every property is chosen deliberately. What they cannot do is
demonstrate that the platform handles *the actual market*: real SET50 futures data has quiet
minutes, feed gaps, off-tick prints and holidays nobody remembered, and a fixture author
writes none of those by accident.

So the two are kept apart by type, and the promotion to
:data:`Tfex2Status.REAL_DATA_VALIDATED` refuses to happen without at least one validated,
non-synthetic dataset.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.tfex.errors import RealMarketDataValidationRequired
from app.tfex.marketdata.models import DatasetManifest, ValidationOutcome, ValidationReport

__all__ = [
    "AcceptanceEvidence",
    "Tfex2Status",
    "assess_tfex2_status",
    "mark_tfex2_complete",
]


class Tfex2Status(StrEnum):
    """How far TFEX-2 acceptance has actually got."""

    NOT_STARTED = "TFEX2_NOT_STARTED"
    FIXTURE_VALIDATED = "TFEX2_FIXTURE_VALIDATED"
    """Everything passes on synthetic fixtures. Necessary, and not sufficient."""

    REAL_DATA_VALIDATED = "TFEX2_REAL_DATA_VALIDATED"
    """At least one real contract dataset was validated and replayed. The only state that
    counts as TFEX-2 complete."""


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    """What was actually validated, and what it proves."""

    status: Tfex2Status
    real_datasets: tuple[str, ...]
    synthetic_datasets: tuple[str, ...]
    rejected_datasets: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def real_data_validated(self) -> bool:
        return self.status is Tfex2Status.REAL_DATA_VALIDATED


def _manifest_of(report: ValidationReport) -> DatasetManifest | None:
    return report.manifest


def assess_tfex2_status(reports: Sequence[ValidationReport]) -> AcceptanceEvidence:
    """Classify the evidence without raising, for reporting and dashboards."""
    real: list[str] = []
    synthetic: list[str] = []
    rejected: list[str] = []
    reasons: list[str] = []

    for report in reports:
        manifest = _manifest_of(report)
        if report.outcome is ValidationOutcome.REJECTED:
            rejected.append(report.dataset_id)
            reasons.append(f"{report.dataset_id}: validation REJECTED")
            continue
        if report.outcome is ValidationOutcome.CONFIGURATION_OR_PROVENANCE_ERROR:
            rejected.append(report.dataset_id)
            reasons.append(f"{report.dataset_id}: provenance or configuration error")
            continue
        if manifest is None:
            rejected.append(report.dataset_id)
            reasons.append(f"{report.dataset_id}: no manifest, so provenance is unknown")
            continue
        if manifest.is_real_market_data:
            real.append(report.dataset_id)
        else:
            synthetic.append(report.dataset_id)
            why = (
                "synthetic" if manifest.synthetic else f"source is unverified ({manifest.source!r})"
            )
            reasons.append(f"{report.dataset_id}: {why}, cannot satisfy acceptance")

    if real:
        status = Tfex2Status.REAL_DATA_VALIDATED
    elif synthetic:
        status = Tfex2Status.FIXTURE_VALIDATED
        reasons.append(
            "every validated dataset is synthetic; TFEX-2 acceptance requires real "
            "historical SET50 futures data"
        )
    else:
        status = Tfex2Status.NOT_STARTED
        reasons.append("no dataset passed validation")

    return AcceptanceEvidence(
        status=status,
        real_datasets=tuple(real),
        synthetic_datasets=tuple(synthetic),
        rejected_datasets=tuple(rejected),
        reasons=tuple(reasons),
    )


def mark_tfex2_complete(reports: Sequence[ValidationReport]) -> AcceptanceEvidence:
    """Declare TFEX-2 complete, or refuse to.

    Raises:
        RealMarketDataValidationRequired: no validated non-synthetic dataset was supplied.
            This is the hard guard: fixtures alone can never promote the milestone.
    """
    evidence = assess_tfex2_status(reports)
    if not evidence.real_data_validated:
        raise RealMarketDataValidationRequired(
            "TFEX-2 cannot be marked complete without at least one validated real market-data "
            "set. Status is "
            f"{evidence.status}; real={list(evidence.real_datasets)}, "
            f"synthetic={list(evidence.synthetic_datasets)}, "
            f"rejected={list(evidence.rejected_datasets)}. " + " ".join(evidence.reasons)
        )
    return evidence
