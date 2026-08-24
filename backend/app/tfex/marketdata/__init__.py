"""Market-data domain: bars, dataset provenance, validation, and the acceptance gate.

Added by the data-readiness gate, ahead of the TFEX-2 replay engine, because a validator
written *after* the importer tends to be written to agree with it.

Nothing here builds candles or runs a replay — that is TFEX-2. What is here decides whether
a file is allowed to become input at all (`CLAUDE_TFEX.md` section 28), and whether the
milestone may be called complete (synthetic fixtures never satisfy acceptance).
"""

from app.tfex.marketdata.acceptance import (
    AcceptanceEvidence,
    Tfex2Status,
    assess_tfex2_status,
    mark_tfex2_complete,
)
from app.tfex.marketdata.models import (
    Bar,
    BarInterval,
    CheckResult,
    CheckStatus,
    DatasetManifest,
    Finding,
    MissingRange,
    MissingRangeKind,
    SessionMembership,
    ValidationOutcome,
    ValidationReport,
)

__all__ = [
    "AcceptanceEvidence",
    "Bar",
    "BarInterval",
    "CheckResult",
    "CheckStatus",
    "DatasetManifest",
    "Finding",
    "MissingRange",
    "MissingRangeKind",
    "SessionMembership",
    "Tfex2Status",
    "ValidationOutcome",
    "ValidationReport",
    "assess_tfex2_status",
    "mark_tfex2_complete",
]
