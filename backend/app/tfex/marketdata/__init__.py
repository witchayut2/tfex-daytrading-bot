"""Market-data domain: bars, dataset provenance, validation, and the acceptance gate.

The validator was added by the data-readiness gate ahead of TFEX-2, because a validator
written *after* the importer tends to be written to agree with it. TFEX-2 now consumes its
canonical bars and manifests through the replay modules in this package.

Validation still decides whether a file may become input (`CLAUDE_TFEX.md` section 28), and
the completion guard requires matching real replay evidence. Synthetic fixtures never
satisfy acceptance.
"""

from app.tfex.marketdata.acceptance import (
    AcceptanceEvidence,
    ReplayAcceptanceRun,
    Tfex2Status,
    assess_tfex2_status,
    mark_tfex2_complete,
)
from app.tfex.marketdata.models import (
    Bar,
    BarInterval,
    CheckResult,
    CheckStatus,
    DatasetDateRange,
    DatasetManifest,
    Finding,
    MissingRange,
    MissingRangeKind,
    SessionMembership,
    SourceCapture,
    ValidationOutcome,
    ValidationReport,
)

__all__ = [
    "AcceptanceEvidence",
    "Bar",
    "BarInterval",
    "CheckResult",
    "CheckStatus",
    "DatasetDateRange",
    "DatasetManifest",
    "Finding",
    "MissingRange",
    "MissingRangeKind",
    "ReplayAcceptanceRun",
    "SessionMembership",
    "SourceCapture",
    "Tfex2Status",
    "ValidationOutcome",
    "ValidationReport",
    "assess_tfex2_status",
    "mark_tfex2_complete",
]
