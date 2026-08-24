"""Official-source register and metadata provenance (`CLAUDE_TFEX.md` section 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import HttpUrl

from app.tfex.errors import SourceRegistryError, StaleMetadataError, UnverifiedMetadataError
from app.tfex.provenance import (
    OFFICIAL_SOURCE_SEED,
    OfficialSourceRegistry,
    Provenance,
    SourceRecord,
    VerificationResult,
    content_fingerprint,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def test_every_url_from_section_2_is_registered() -> None:
    urls = {str(record.url) for record in OfficialSourceRegistry()}
    for fragment in (
        "set50-index-futures/contract-specification",
        "set50-index-futures/trading-calendar",
        "about/trading-calendar",
        "about/holiday",
        "news-and-notice/margin",
        "set50-index-futures/margin",
        "developer.settrade.com/open-api/",
        "open-api/document/broker-list",
        "open-api/use-case",
        "set50/overview",
    ):
        assert any(fragment in url for url in urls), f"section 2 source missing: {fragment}"


def test_the_register_starts_admitting_that_nothing_is_verified() -> None:
    registry = OfficialSourceRegistry()
    assert len(registry.unverified()) == len(registry) == len(OFFICIAL_SOURCE_SEED)


def test_every_source_declares_a_fallback_behavior() -> None:
    """Section 2: no source may fail into "carry on silently"."""
    for record in OfficialSourceRegistry():
        assert record.fallback_behavior.strip()


def test_recording_a_verification_stamps_retrieval_and_fingerprint() -> None:
    registry = OfficialSourceRegistry()
    name = "TFEX holidays"
    fingerprint = content_fingerprint("2026-01-01 New Year")

    updated = registry.record_verification(
        name, result=VerificationResult.VERIFIED_CHANGED, at=NOW, fingerprint=fingerprint
    )

    assert updated.is_verified
    assert updated.retrieval_date == NOW
    assert updated.fingerprint == fingerprint
    assert registry.get(name).fingerprint == fingerprint
    assert name not in {record.name for record in registry.unverified()}


def test_an_unreachable_source_does_not_count_as_retrieved() -> None:
    registry = OfficialSourceRegistry()
    updated = registry.record_verification(
        "TFEX holidays", result=VerificationResult.UNREACHABLE, at=NOW
    )
    assert not updated.is_verified
    assert updated.retrieval_date is None


def test_a_verification_result_without_a_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="without last_verification_at"):
        SourceRecord(
            name="x",
            url=HttpUrl("https://example.com/"),
            fallback_behavior="stop",
            last_verification_result=VerificationResult.VERIFIED_UNCHANGED,
        )


def test_due_for_refresh_includes_sources_never_retrieved() -> None:
    registry = OfficialSourceRegistry()
    due = {record.name for record in registry.due_for_refresh(NOW)}
    assert "TFEX holidays" in due

    registry.record_verification(
        "TFEX holidays", result=VerificationResult.VERIFIED_UNCHANGED, at=NOW
    )
    assert "TFEX holidays" not in {r.name for r in registry.due_for_refresh(NOW)}
    later = NOW + timedelta(days=31)
    assert "TFEX holidays" in {r.name for r in registry.due_for_refresh(later)}


def test_registry_round_trips_through_json(tmp_path: Path) -> None:
    registry = OfficialSourceRegistry()
    registry.record_verification(
        "TFEX holidays",
        result=VerificationResult.VERIFIED_UNCHANGED,
        at=NOW,
        fingerprint="sha256:abc",
    )
    path = tmp_path / "official_sources.json"
    registry.save(path)

    reloaded = OfficialSourceRegistry.load(path)
    assert len(reloaded) == len(registry)
    assert reloaded.get("TFEX holidays").fingerprint == "sha256:abc"


def test_loading_a_registry_with_a_foreign_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "official_sources.json"
    path.write_text('{"schema_version": 99, "sources": []}', encoding="utf-8")
    with pytest.raises(SourceRegistryError, match="schema_version"):
        OfficialSourceRegistry.load(path)


def test_asking_for_an_unregistered_source_raises() -> None:
    with pytest.raises(SourceRegistryError, match="no official source registered"):
        OfficialSourceRegistry().get("not a source")


def test_rendered_markdown_reports_the_unverified_count() -> None:
    registry = OfficialSourceRegistry()
    rendered = registry.render_markdown(generated_at=NOW)
    assert "# TFEX Official Sources" in rendered
    assert "GENERATED FILE" in rendered
    assert f"Not verified: **{len(registry)}**" in rendered
    assert "NOT_VERIFIED" in rendered


# --- Provenance -----------------------------------------------------------------------


def test_metadata_that_was_never_retrieved_counts_as_stale() -> None:
    """An unknown age is not a young age."""
    assert Provenance(source_name="x").is_stale(NOW)


def test_metadata_without_an_expiry_never_goes_stale() -> None:
    provenance = Provenance(source_name="x", retrieved_at=NOW - timedelta(days=3650))
    assert not provenance.is_stale(NOW)


def test_require_usable_rejects_stale_metadata() -> None:
    provenance = Provenance(
        source_name="holidays",
        retrieved_at=NOW - timedelta(days=200),
        stale_after=NOW - timedelta(days=20),
    )
    with pytest.raises(StaleMetadataError, match="is stale"):
        provenance.require_usable(NOW, require_verified=False)


def test_require_usable_rejects_unverified_metadata_when_verification_is_required() -> None:
    provenance = Provenance(source_name="holidays", retrieved_at=NOW, verified=False)
    provenance.require_usable(NOW, require_verified=False)
    with pytest.raises(UnverifiedMetadataError, match="has not been verified"):
        provenance.require_usable(NOW, require_verified=True)


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Provenance(source_name="x", retrieved_at=datetime(2026, 8, 23, 12, 0))


def test_with_staleness_derives_the_window_from_retrieval() -> None:
    provenance = Provenance(source_name="x", retrieved_at=NOW).with_staleness(days=180)
    assert provenance.stale_after == NOW + timedelta(days=180)
    assert not provenance.is_stale(NOW + timedelta(days=179))
    assert provenance.is_stale(NOW + timedelta(days=180))


def test_fingerprints_detect_a_changed_page() -> None:
    assert content_fingerprint("a") == content_fingerprint(b"a")
    assert content_fingerprint("a") != content_fingerprint("b")
