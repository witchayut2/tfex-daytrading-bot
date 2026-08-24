"""Provenance tracking for exchange metadata (`CLAUDE_TFEX.md` section 2).

Nothing the platform believes about TFEX should be believable without knowing where it came
from, when it was retrieved, and whether it has been verified. This module supplies:

* :class:`SourceRecord` — the per-source audit row section 2 enumerates.
* :class:`OfficialSourceRegistry` — a JSON-backed collection of those rows, seeded with the
  official URLs, able to render `docs/tfex_official_sources.md`.
* :class:`Provenance` — the small embeddable stamp that data models (holidays, contract
  metadata, margins) carry so a value can always be traced back to a source.

Deliberately absent: any network fetching. Section 2 forbids scraping on market events and
requires scheduled refresh jobs; those arrive with the modules that consume live metadata.
This layer only records and validates what an operator or a job has already retrieved.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.tfex.errors import SourceRegistryError, StaleMetadataError, UnverifiedMetadataError

__all__ = [
    "OFFICIAL_SOURCE_SEED",
    "OfficialSourceRegistry",
    "Provenance",
    "SourceRecord",
    "VerificationResult",
    "content_fingerprint",
]


class VerificationResult(StrEnum):
    """Outcome of the most recent check of a source against its live URL."""

    NOT_VERIFIED = "NOT_VERIFIED"
    """Never checked. The default, and the honest state for a freshly seeded registry."""

    VERIFIED_UNCHANGED = "VERIFIED_UNCHANGED"
    VERIFIED_CHANGED = "VERIFIED_CHANGED"
    """Fetched successfully but the fingerprint moved: consumers must re-import."""

    UNREACHABLE = "UNREACHABLE"
    INVALID = "INVALID"


def content_fingerprint(content: bytes | str) -> str:
    """SHA-256 of retrieved content, used to detect that an official page has changed."""
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class Provenance(BaseModel):
    """Where a piece of exchange metadata came from.

    Embedded in holiday files, contract metadata and margin records. ``retrieved_at`` and
    ``stale_after`` together answer "may I still use this?"; ``verified`` answers "was it
    ever checked against the official source?".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_name: str
    source_url: HttpUrl | None = None
    retrieved_at: datetime | None = None
    effective_date: date | None = None
    fingerprint: str | None = None
    verified: bool = False
    stale_after: datetime | None = None
    imported_by: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _timestamps_are_aware(self) -> Self:
        for field_name in ("retrieved_at", "stale_after"):
            value: datetime | None = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.retrieved_at and self.stale_after and self.stale_after <= self.retrieved_at:
            raise ValueError("stale_after must be after retrieved_at")
        return self

    def is_stale(self, as_of: datetime) -> bool:
        """True when the data may no longer be used.

        Data that was never retrieved counts as stale: an unknown age is not a young age.
        """
        if self.retrieved_at is None:
            return True
        if self.stale_after is None:
            return False
        return as_of >= self.stale_after

    def require_usable(self, as_of: datetime, *, require_verified: bool) -> None:
        """Raise unless this metadata may be used for a decision at ``as_of``.

        Raises:
            StaleMetadataError: the data is past its freshness window or was never retrieved.
            UnverifiedMetadataError: verification is required and this source lacks it.
        """
        if self.is_stale(as_of):
            raise StaleMetadataError(
                f"metadata from {self.source_name!r} is stale at {as_of.isoformat()} "
                f"(retrieved_at={self.retrieved_at}, stale_after={self.stale_after})"
            )
        if require_verified and not self.verified:
            raise UnverifiedMetadataError(
                f"metadata from {self.source_name!r} has not been verified against its "
                f"official source"
            )

    def with_staleness(self, *, days: int) -> Provenance:
        """Return a copy whose ``stale_after`` is ``days`` after retrieval."""
        if self.retrieved_at is None:
            raise SourceRegistryError("cannot derive staleness without retrieved_at")
        return self.model_copy(update={"stale_after": self.retrieved_at + timedelta(days=days)})


class SourceRecord(BaseModel):
    """One row of the official-source register described in section 2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    url: HttpUrl
    fields_consumed: tuple[str, ...] = ()
    """What the platform actually reads from this page. Empty means reference-only."""

    retrieval_date: datetime | None = None
    effective_date: date | None = None
    fingerprint: str | None = None
    last_verification_result: VerificationResult = VerificationResult.NOT_VERIFIED
    last_verification_at: datetime | None = None
    fallback_behavior: str
    """What the platform does when this source is unavailable. Never "carry on silently"."""

    refresh_interval_days: int | None = Field(default=None, ge=1)
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (
            self.last_verification_result is not VerificationResult.NOT_VERIFIED
            and self.last_verification_at is None
        ):
            raise ValueError(
                f"source {self.name!r} claims verification result "
                f"{self.last_verification_result} without last_verification_at"
            )
        if self.retrieval_date is not None and self.retrieval_date.tzinfo is None:
            raise ValueError("retrieval_date must be timezone-aware")
        return self

    @property
    def is_verified(self) -> bool:
        return self.last_verification_result in {
            VerificationResult.VERIFIED_UNCHANGED,
            VerificationResult.VERIFIED_CHANGED,
        }

    def to_provenance(self) -> Provenance:
        return Provenance(
            source_name=self.name,
            source_url=self.url,
            retrieved_at=self.retrieval_date,
            effective_date=self.effective_date,
            fingerprint=self.fingerprint,
            verified=self.is_verified,
        )


def _seed() -> tuple[SourceRecord, ...]:
    """The official sources listed in section 2, seeded unverified.

    Seeding them as ``NOT_VERIFIED`` with no retrieval date is the point: the register starts
    by admitting that nothing has been checked yet.
    """
    return (
        SourceRecord(
            name="TFEX SET50 Index Futures contract specification",
            url=HttpUrl(
                "https://www.tfex.co.th/en/products/equity/set50-index-futures/"
                "contract-specification"
            ),
            fields_consumed=(
                "multiplier",
                "tick_size",
                "tick_value",
                "listed_contract_months",
                "daily_price_limit",
                "trading_hours",
                "last_trading_day_rule",
                "settlement_method",
            ),
            fallback_behavior=(
                "Use the checked-in contract configuration and mark contract metadata "
                "unverified. Order-capable modes reject."
            ),
            refresh_interval_days=90,
        ),
        SourceRecord(
            name="SET50 Index Futures product trading calendar",
            url=HttpUrl(
                "https://www.tfex.co.th/en/products/equity/set50-index-futures/trading-calendar"
            ),
            fields_consumed=("contract_month", "first_trading_day", "last_trading_day"),
            fallback_behavior=(
                "Fall back to the derived last-trading-day rule and stamp the contract as "
                "DERIVED_RULE. Rejected when expiry.require_published_last_trading_day is true."
            ),
            refresh_interval_days=30,
        ),
        SourceRecord(
            name="TFEX annual trading calendar",
            url=HttpUrl("https://www.tfex.co.th/en/about/trading-calendar"),
            fields_consumed=("trading_days", "shortened_sessions"),
            fallback_behavior="Calendar raises CalendarDataUnavailableError for unloaded years.",
            refresh_interval_days=30,
        ),
        SourceRecord(
            name="TFEX holidays",
            url=HttpUrl("https://www.tfex.co.th/en/about/holiday"),
            fields_consumed=("holiday_date", "holiday_name"),
            fallback_behavior="Calendar raises CalendarDataUnavailableError for unloaded years.",
            refresh_interval_days=30,
        ),
        SourceRecord(
            name="TFEX margin announcements",
            url=HttpUrl("https://www.tfex.co.th/en/market-data/news-and-notice/margin"),
            fields_consumed=("initial_margin", "maintenance_margin", "effective_date"),
            fallback_behavior=(
                "Margin gate rejects new positions when margin.reject_when_stale is true (TFEX-4)."
            ),
            refresh_interval_days=7,
        ),
        SourceRecord(
            name="SET50 Futures margin page",
            url=HttpUrl("https://www.tfex.co.th/en/products/equity/set50-index-futures/margin"),
            fields_consumed=("initial_margin", "maintenance_margin"),
            fallback_behavior="As above; cross-check only.",
            refresh_interval_days=7,
        ),
        SourceRecord(
            name="Settrade Open API documentation",
            url=HttpUrl("https://developer.settrade.com/open-api/"),
            fallback_behavior="Adapter interfaces only; no live connectivity in this build.",
            note="Reference only until a broker and credentials exist (section 26).",
        ),
        SourceRecord(
            name="Settrade Open API broker list",
            url=HttpUrl("https://developer.settrade.com/open-api/document/broker-list"),
            fallback_behavior="Live connectivity blocked until the broker is confirmed supported.",
            note="Section 26 prerequisite 1.",
        ),
        SourceRecord(
            name="Settrade derivatives use cases",
            url=HttpUrl("https://developer.settrade.com/open-api/use-case"),
            fallback_behavior="Reference only.",
        ),
        SourceRecord(
            name="SET50 Index overview",
            url=HttpUrl("https://www.set.or.th/en/market/index/set50/overview"),
            fields_consumed=("index_level",),
            fallback_behavior="Basis calculations are skipped and reported as unavailable.",
            note="Optional spot reference for basis analysis (section 14 of CLAUDE_TFEX.md).",
        ),
    )


OFFICIAL_SOURCE_SEED: tuple[SourceRecord, ...] = _seed()


class OfficialSourceRegistry:
    """The register described in section 2, persisted as JSON.

    Keyed by source name. Records are immutable; updating one replaces it wholesale so an
    edit cannot silently mutate a shared object held elsewhere.
    """

    SCHEMA_VERSION = 1

    def __init__(self, records: Iterable[SourceRecord] | None = None) -> None:
        self._records: dict[str, SourceRecord] = {}
        for record in records if records is not None else OFFICIAL_SOURCE_SEED:
            self.upsert(record)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[SourceRecord]:
        return iter(sorted(self._records.values(), key=lambda r: r.name))

    def __contains__(self, name: object) -> bool:
        return name in self._records

    def upsert(self, record: SourceRecord) -> None:
        self._records[record.name] = record

    def get(self, name: str) -> SourceRecord:
        try:
            return self._records[name]
        except KeyError:
            raise SourceRegistryError(f"no official source registered under {name!r}") from None

    def record_verification(
        self,
        name: str,
        *,
        result: VerificationResult,
        at: datetime,
        fingerprint: str | None = None,
        effective_date: date | None = None,
    ) -> SourceRecord:
        """Stamp the outcome of a refresh job onto a source."""
        if at.tzinfo is None:
            raise SourceRegistryError("verification timestamp must be timezone-aware")
        current = self.get(name)
        updates: dict[str, object] = {
            "last_verification_result": result,
            "last_verification_at": at,
        }
        if result in {VerificationResult.VERIFIED_UNCHANGED, VerificationResult.VERIFIED_CHANGED}:
            updates["retrieval_date"] = at
            if fingerprint is not None:
                updates["fingerprint"] = fingerprint
            if effective_date is not None:
                updates["effective_date"] = effective_date
        updated = current.model_copy(update=updates)
        self.upsert(updated)
        return updated

    def unverified(self) -> tuple[SourceRecord, ...]:
        return tuple(r for r in self if not r.is_verified)

    def due_for_refresh(self, as_of: datetime) -> tuple[SourceRecord, ...]:
        """Sources whose refresh interval has elapsed, plus any never retrieved."""
        due: list[SourceRecord] = []
        for record in self:
            if record.refresh_interval_days is None:
                continue
            interval = timedelta(days=record.refresh_interval_days)
            if record.retrieval_date is None or as_of - record.retrieval_date >= interval:
                due.append(record)
        return tuple(due)

    # --- persistence ------------------------------------------------------------------

    def to_json(self) -> str:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "sources": [json.loads(r.model_dump_json()) for r in self],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> OfficialSourceRegistry:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SourceRegistryError(f"cannot read source registry at {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SourceRegistryError(
                f"source registry at {path} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict) or "sources" not in payload:
            raise SourceRegistryError(f"source registry at {path} is missing a 'sources' key")
        version = payload.get("schema_version")
        if version != cls.SCHEMA_VERSION:
            raise SourceRegistryError(
                f"source registry at {path} has schema_version {version!r}, expected "
                f"{cls.SCHEMA_VERSION}"
            )
        return cls(SourceRecord.model_validate(item) for item in payload["sources"])

    # --- reporting --------------------------------------------------------------------

    def render_markdown(self, *, generated_at: datetime | None = None) -> str:
        """Render `docs/tfex_official_sources.md`.

        Generated rather than hand-written so the document cannot drift away from the
        register the code actually consults.
        """
        stamp = (generated_at or datetime.now(UTC)).date().isoformat()
        lines = [
            "# TFEX Official Sources",
            "",
            "<!-- GENERATED FILE - do not edit by hand.",
            "     Regenerate with: uv run python scripts/render_official_sources.py -->",
            "",
            f"Generated: {stamp}",
            "",
            "Register of every official source the platform depends on, as required by",
            "`CLAUDE_TFEX.md` section 2. A source that has never been verified is shown as",
            "`NOT_VERIFIED`; that is a statement of fact, not an oversight.",
            "",
        ]
        for record in self:
            lines.extend(
                [
                    f"## {record.name}",
                    "",
                    f"- **URL:** {record.url}",
                    f"- **Retrieval date:** {_fmt(record.retrieval_date, '_not retrieved_')}",
                    f"- **Effective date:** {_fmt(record.effective_date, '_none published_')}",
                    "- **Fields consumed:** "
                    + (", ".join(f"`{f}`" for f in record.fields_consumed) or "_reference only_"),
                    f"- **Fingerprint:** {record.fingerprint or '_none recorded_'}",
                    f"- **Last verification result:** `{record.last_verification_result}`"
                    + (
                        f" at {_fmt(record.last_verification_at)}"
                        if record.last_verification_at
                        else ""
                    ),
                    "- **Refresh interval:** "
                    + (
                        f"{record.refresh_interval_days} days"
                        if record.refresh_interval_days
                        else "_on demand_"
                    ),
                    f"- **Fallback behavior:** {record.fallback_behavior}",
                ]
            )
            if record.note:
                lines.append(f"- **Note:** {record.note}")
            lines.append("")

        unverified = self.unverified()
        lines.extend(
            [
                "## Verification summary",
                "",
                f"- Registered sources: **{len(self)}**",
                f"- Verified: **{len(self) - len(unverified)}**",
                f"- Not verified: **{len(unverified)}**",
                "",
            ]
        )
        if unverified:
            lines.append("Sources still awaiting verification:")
            lines.append("")
            lines.extend(f"- {r.name}" for r in unverified)
            lines.append("")
        return "\n".join(lines)


def _fmt(value: datetime | date | None, absent: str = "_none recorded_") -> str:
    return value.isoformat() if value is not None else absent
