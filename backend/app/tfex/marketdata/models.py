"""Canonical market-data types and the shape of a validation report.

Everything the replay engine will consume must first exist as a :class:`Bar` that came from
a file with a :class:`DatasetManifest`. The manifest is not paperwork: section 30 requires
backtests to be reproducible, and a result you cannot tie back to a specific file with a
specific checksum is not reproducible.

The report types are deliberately granular. Section 28 lists twelve separate data-quality
conditions, and a single aggregate score would hide which one failed — so every check keeps
its own status and its own findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Prefix a starter manifest carries until an operator fills the real source in.
UNVERIFIED_SOURCE_PREFIX = "UNVERIFIED"

__all__ = [
    "UNVERIFIED_SOURCE_PREFIX",
    "Bar",
    "BarInterval",
    "CheckResult",
    "CheckStatus",
    "DatasetManifest",
    "Finding",
    "MissingRange",
    "MissingRangeKind",
    "SessionMembership",
    "ValidationOutcome",
    "ValidationReport",
]


class BarInterval(StrEnum):
    """Intervals this platform accepts as *source* data.

    Section 10 requires 1m/5m/15m, built from ticks or one-minute candles. Coarser source
    data cannot produce them, so it is not accepted as an import granularity.
    """

    ONE_MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"

    @property
    def minutes(self) -> int:
        return {"1m": 1, "5m": 5, "15m": 15}[self.value]


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar of one contract.

    A plain dataclass rather than a pydantic model: a dataset is tens of thousands of these,
    and validation here is the validator's job — it needs to report every bad row, not abort
    on the first one.
    """

    symbol: str
    timestamp: datetime
    """Bar **open** time, timezone-aware, in market local time. Section 10: a bucket closes
    only after it completes, so labelling by open time keeps a bar from claiming to know
    anything about the future."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: int | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    open_interest: int | None = None
    settlement_price: Decimal | None = None
    source_sequence: int | None = None
    line_number: int = 0
    """Line in the source file, so a finding points at something the operator can open."""

    @property
    def trading_date(self) -> date:
        return self.timestamp.date()


class SessionMembership(StrEnum):
    """Where a bar's timestamp falls relative to the TFEX session (section 9)."""

    VALID_CONTINUOUS_SESSION = "VALID_CONTINUOUS_SESSION"
    PREOPEN_DATA = "PREOPEN_DATA"
    MIDDAY_BREAK_DATA = "MIDDAY_BREAK_DATA"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    LAST_TRADING_DAY_AFTER_CUTOFF = "LAST_TRADING_DAY_AFTER_CUTOFF"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    UNKNOWN = "UNKNOWN"
    """The calendar could not answer — the year is not imported. Never treated as valid."""


class MissingRangeKind(StrEnum):
    """Why a slot in the expected bar grid has no bar (section 28)."""

    NO_TRADE_EXPECTED = "NO_TRADE_EXPECTED"
    """Outside a continuous session. Nothing should be there."""

    POSSIBLE_NO_TRADE = "POSSIBLE_NO_TRADE"
    """Short gap inside a session. Many feeds simply omit minutes with no trades."""

    SOURCE_DATA_GAP = "SOURCE_DATA_GAP"
    """Long enough that a quiet market is an unlikely explanation."""

    CRITICAL_DATA_GAP = "CRITICAL_DATA_GAP"
    """Long enough that the dataset cannot be trusted for replay."""

    MARKET_CLOSED = "MARKET_CLOSED"


@dataclass(frozen=True, slots=True)
class MissingRange:
    kind: MissingRangeKind
    start: datetime
    end: datetime
    bar_count: int

    def describe(self) -> str:
        return (
            f"{self.kind}: {self.start.isoformat()} -> {self.end.isoformat()} "
            f"({self.bar_count} bar slots)"
        )


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    """A prerequisite is missing, so the check could not be performed. Never a pass."""

    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class Finding:
    """One concrete problem, anchored where the operator can act on it."""

    message: str
    line_number: int | None = None
    timestamp: datetime | None = None

    def describe(self) -> str:
        where = f" (line {self.line_number})" if self.line_number else ""
        return f"{self.message}{where}"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    summary: str
    findings: tuple[Finding, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status in {CheckStatus.FAIL, CheckStatus.BLOCKED}


class ValidationOutcome(StrEnum):
    """Overall verdict. Maps directly to the CLI exit code."""

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REJECTED = "REJECTED"
    CONFIGURATION_OR_PROVENANCE_ERROR = "CONFIGURATION_OR_PROVENANCE_ERROR"

    @property
    def exit_code(self) -> int:
        return {
            "PASS": 0,
            "PASS_WITH_WARNINGS": 1,
            "REJECTED": 2,
            "CONFIGURATION_OR_PROVENANCE_ERROR": 3,
        }[self.value]


class DatasetManifest(BaseModel):
    """Provenance for one market-data file (section 30, and the gate's PART T).

    ``dataset_id``, ``sha256`` and ``validator_version`` are what a replay records so a
    result can be reproduced. ``synthetic`` is what stops fabricated data being promoted to
    an acceptance test.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    source: str
    authority: str | None = None
    retrieved_at: datetime | None = None
    license: str | None = None
    original_filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str
    interval: BarInterval
    source_timezone: str
    normalized_timezone: str = "UTC"
    record_count: int = Field(ge=0)
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    trading_days: int | None = Field(default=None, ge=0)
    validation_status: str | None = None
    validator_version: str | None = None

    synthetic: bool = False
    """True for anything generated rather than observed. Section-level rule: synthetic data
    is fine for unit tests, edge cases and fault injection, and never satisfies acceptance."""

    note: str | None = None

    @model_validator(mode="after")
    def _timestamps_are_aware_and_ordered(self) -> Self:
        for name in ("retrieved_at", "first_timestamp", "last_timestamp"):
            value: datetime | None = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (
            self.first_timestamp is not None
            and self.last_timestamp is not None
            and self.last_timestamp < self.first_timestamp
        ):
            raise ValueError("last_timestamp precedes first_timestamp")
        return self

    @property
    def source_is_verified(self) -> bool:
        """False for a blank source and for the placeholder a starter manifest carries.

        The validator can generate a manifest for a file it finds, but it cannot know where
        that file came from. A placeholder must not be able to graduate into evidence just
        because nobody edited it.
        """
        source = self.source.strip()
        return bool(source) and not source.upper().startswith(UNVERIFIED_SOURCE_PREFIX)

    @property
    def is_real_market_data(self) -> bool:
        """Only a non-synthetic dataset from a named, verified source counts as real."""
        return not self.synthetic and self.source_is_verified


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The full result: every check, kept separate (PART S)."""

    dataset_id: str
    symbol: str
    interval: BarInterval
    file_path: str
    sha256: str
    row_count: int
    checks: tuple[CheckResult, ...]
    validator_version: str
    generated_at: datetime
    manifest: DatasetManifest | None = None

    @property
    def outcome(self) -> ValidationOutcome:
        if any(c.status is CheckStatus.FAIL for c in self.checks):
            return ValidationOutcome.REJECTED
        if any(c.status is CheckStatus.BLOCKED for c in self.checks):
            return ValidationOutcome.REJECTED
        if any(c.status is CheckStatus.WARNING for c in self.checks):
            return ValidationOutcome.PASS_WITH_WARNINGS
        return ValidationOutcome.PASS

    @property
    def is_acceptable_for_replay(self) -> bool:
        return self.outcome in {ValidationOutcome.PASS, ValidationOutcome.PASS_WITH_WARNINGS}

    def check(self, name: str) -> CheckResult | None:
        for result in self.checks:
            if result.name == name:
                return result
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "symbol": self.symbol,
            "interval": self.interval.value,
            "file": self.file_path,
            "sha256": self.sha256,
            "rows": self.row_count,
            "validator_version": self.validator_version,
            "generated_at": self.generated_at.isoformat(),
            "outcome": self.outcome.value,
            "exit_code": self.outcome.exit_code,
            "synthetic": self.manifest.synthetic if self.manifest else None,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "summary": c.summary,
                    "findings": [f.describe() for f in c.findings[:50]],
                    "finding_count": len(c.findings),
                    "details": c.details,
                }
                for c in self.checks
            ],
        }

    def render_text(self) -> str:
        width = max((len(c.name) for c in self.checks), default=10) + 2
        lines = [
            "TFEX market-data validation report",
            "",
            f"  Dataset            {self.dataset_id}",
            f"  Contract           {self.symbol}",
            f"  Interval           {self.interval.value}",
            f"  File               {self.file_path}",
            f"  SHA-256            {self.sha256}",
            f"  Rows               {self.row_count:,}",
            f"  Synthetic          {self.manifest.synthetic if self.manifest else 'unknown'}",
            f"  Validator          {self.validator_version}",
            "",
        ]
        for result in self.checks:
            lines.append(f"  {result.name:<{width}} {result.status.value:<8} {result.summary}")
            for finding in result.findings[:10]:
                lines.append(f"      - {finding.describe()}")
            if len(result.findings) > 10:
                lines.append(f"      ... {len(result.findings) - 10} more")
        lines += ["", f"Overall: {self.outcome.value}"]
        return "\n".join(lines)
