"""The gate that stops synthetic data being mistaken for market validation.

Synthetic fixtures are necessary — unit tests, edge cases, fault injection and anti-repaint
proofs all need data whose every property is chosen deliberately. What they cannot do is
demonstrate that the platform handles *the actual market*: real SET50 futures data has quiet
minutes, feed gaps, off-tick prints and holidays nobody remembered, and a fixture author
writes none of those by accident.

So the two are kept apart by type. Structurally valid real data is also kept separate from
the minimum-history requirement: an interim dataset is evidence about the feed, but cannot
promote :data:`Tfex2Status.REAL_DATA_VALIDATED` until its manifest proves at least five
complete trading days.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.tfex.errors import RealMarketDataValidationRequired
from app.tfex.marketdata.models import DatasetManifest, ValidationOutcome, ValidationReport

__all__ = [
    "AcceptanceEvidence",
    "ReplayAcceptanceRun",
    "Tfex2Status",
    "assess_tfex2_status",
    "mark_tfex2_complete",
]


class ReplayAcceptanceRun(Protocol):
    """Minimum reproducible replay result required by the completion guard."""

    @property
    def symbol(self) -> str: ...

    @property
    def source_bar_count(self) -> int: ...

    @property
    def frames(self) -> Sequence[object]: ...

    @property
    def confirmed_5m(self) -> Sequence[object]: ...

    @property
    def confirmed_15m(self) -> Sequence[object]: ...

    @property
    def digest(self) -> str: ...

    @property
    def dataset_id(self) -> str | None: ...

    @property
    def dataset_sha256(self) -> str | None: ...


class Tfex2Status(StrEnum):
    """How far the real-data prerequisite for TFEX-2 has got."""

    NOT_STARTED = "TFEX2_NOT_STARTED"
    FIXTURE_VALIDATED = "TFEX2_FIXTURE_VALIDATED"
    """Everything passes on synthetic fixtures. Necessary, and not sufficient."""

    INTERIM_REAL_DATA_VALIDATED = "TFEX2_INTERIM_REAL_DATA_VALIDATED"
    """Real market data passed structural validation but not the minimum-history gate."""

    REAL_DATA_VALIDATED = "TFEX2_REAL_DATA_VALIDATED"
    """At least one real contract dataset passed the five-day data-readiness gate."""


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    """What was actually validated, and what it proves."""

    status: Tfex2Status
    real_datasets: tuple[str, ...]
    minimum_history_datasets: tuple[str, ...]
    interim_real_datasets: tuple[str, ...]
    synthetic_datasets: tuple[str, ...]
    rejected_datasets: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def real_data_validated(self) -> bool:
        return self.status is Tfex2Status.REAL_DATA_VALIDATED

    @property
    def real_data_valid(self) -> bool:
        """At least one structurally valid, non-synthetic dataset was supplied."""
        return bool(self.real_datasets)

    @property
    def minimum_history_requirement_met(self) -> bool:
        return bool(self.minimum_history_datasets)


def _manifest_of(report: ValidationReport) -> DatasetManifest | None:
    return report.manifest


def _minimum_history_is_proven(manifest: DatasetManifest) -> bool:
    """Require explicit dates/counts rather than trusting a lone boolean assertion."""
    return bool(
        manifest.minimum_dataset_requirement_met is True
        and manifest.acquired_complete_trading_days is not None
        and manifest.acquired_complete_trading_days >= 5
        and manifest.complete_trading_days is not None
        and manifest.complete_trading_days >= 5
        and len(manifest.trading_dates) == manifest.complete_trading_days
    )


def assess_tfex2_status(reports: Sequence[ValidationReport]) -> AcceptanceEvidence:
    """Classify the evidence without raising, for reporting and dashboards."""
    real: list[str] = []
    minimum_history: list[str] = []
    interim_real: list[str] = []
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
            if _minimum_history_is_proven(manifest):
                minimum_history.append(report.dataset_id)
            else:
                interim_real.append(report.dataset_id)
                reasons.append(
                    f"{report.dataset_id}: real data is structurally valid, but the "
                    "minimum five-complete-trading-day requirement is not met"
                )
        else:
            synthetic.append(report.dataset_id)
            why = (
                "synthetic" if manifest.synthetic else f"source is unverified ({manifest.source!r})"
            )
            reasons.append(f"{report.dataset_id}: {why}, cannot satisfy acceptance")

    if minimum_history:
        status = Tfex2Status.REAL_DATA_VALIDATED
    elif interim_real:
        status = Tfex2Status.INTERIM_REAL_DATA_VALIDATED
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
        minimum_history_datasets=tuple(minimum_history),
        interim_real_datasets=tuple(interim_real),
        synthetic_datasets=tuple(synthetic),
        rejected_datasets=tuple(rejected),
        reasons=tuple(reasons),
    )


def _has_matching_replay(
    report: ValidationReport,
    replay_runs: Sequence[ReplayAcceptanceRun],
) -> bool:
    return any(
        run.dataset_id == report.dataset_id
        and run.dataset_sha256 == report.sha256
        and run.symbol == report.symbol
        and run.source_bar_count == report.row_count
        and len(run.frames) == report.row_count
        and bool(run.confirmed_5m)
        and bool(run.confirmed_15m)
        and re.fullmatch(r"[0-9a-f]{64}", run.digest) is not None
        for run in replay_runs
    )


def mark_tfex2_complete(
    reports: Sequence[ValidationReport],
    replay_runs: Sequence[ReplayAcceptanceRun] = (),
) -> AcceptanceEvidence:
    """Declare TFEX-2 complete, or refuse to.

    Raises:
        RealMarketDataValidationRequired: no validated non-synthetic dataset meeting the
            minimum-history requirement and no matching deterministic replay were supplied.
    """
    evidence = assess_tfex2_status(reports)
    if not evidence.real_data_validated:
        raise RealMarketDataValidationRequired(
            "TFEX-2 cannot be marked complete without at least one validated real market-data "
            "set meeting the minimum five-complete-trading-day requirement. Status is "
            f"{evidence.status}; real={list(evidence.real_datasets)}, "
            f"synthetic={list(evidence.synthetic_datasets)}, "
            f"rejected={list(evidence.rejected_datasets)}. " + " ".join(evidence.reasons)
        )
    qualifying_reports = [
        report for report in reports if report.dataset_id in evidence.minimum_history_datasets
    ]
    if not any(_has_matching_replay(report, replay_runs) for report in qualifying_reports):
        raise RealMarketDataValidationRequired(
            "TFEX-2 cannot be marked complete from data readiness alone; supply a matching "
            "real replay with the same dataset ID/SHA-256/row count, non-empty confirmed "
            "5m and 15m outputs, and a deterministic digest"
        )
    return evidence
