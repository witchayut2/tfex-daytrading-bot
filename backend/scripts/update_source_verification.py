"""Update official-source verification statuses from the evidence actually on disk.

`CLAUDE_TFEX.md` section 2 requires a per-source verification record. This script writes it
**from the stored captures**, never by hand: a status that a human typed is a claim, a status
derived from a capture with a matching SHA-256 is a fact.

Verification is per source *and per fact*. Importing the holiday calendar says nothing about
whether the broker's commission is known, so those sources keep their own statuses and most
of them stay ``NOT_VERIFIED``.

Usage::

    uv run python scripts/update_source_verification.py
    uv run python scripts/update_source_verification.py --corroborate-spec
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.tfex.config import load_config
from app.tfex.provenance import OfficialSourceRegistry, VerificationResult
from scripts.data_sources.tfex_web import FetchError, TfexWebClient

OFFICIAL_ROOT = BACKEND_ROOT / "data" / "tfex" / "official"
REGISTRY_PATH = OFFICIAL_ROOT / "source_registry.json"
DOC_PATH = BACKEND_ROOT.parent / "docs" / "tfex_official_sources.md"
SPEC_CAPTURE = OFFICIAL_ROOT / "contracts" / "spec_corroboration.json"

HOLIDAY_SOURCE = "TFEX holidays"
ANNUAL_CALENDAR_SOURCE = "TFEX annual trading calendar"
PRODUCT_CALENDAR_SOURCE = "SET50 Index Futures product trading calendar"
SPECIFICATION_SOURCE = "TFEX SET50 Index Futures contract specification"

#: The contract facts the platform hard-codes as configuration, and which a corroborating
#: source must agree with. A mismatch is a CONFLICT, not a rounding difference.
SPEC_FIELDS = {
    "tickSize": ("contract.tick_size_points", Decimal("0.1")),
    "priceQuotationFactor": ("contract.point_value_thb", Decimal("200")),
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _capture_is_intact(
    directory: Path, provenance: dict[str, Any], key: str, filename: str
) -> bool:
    """Re-hash the stored capture. A status is only as good as the bytes behind it."""
    recorded = provenance.get("requests", {}).get(key, {}).get("sha256")
    raw = directory / filename
    if not recorded or not raw.is_file():
        return False
    return bool(hashlib.sha256(raw.read_bytes()).hexdigest() == recorded)


def update_from_holiday_capture(registry: OfficialSourceRegistry, *, now: datetime) -> list[str]:
    notes: list[str] = []
    holidays_root = OFFICIAL_ROOT / "holidays"
    if not holidays_root.is_dir():
        return ["no holiday captures on disk; TFEX holidays remains NOT_VERIFIED"]

    years = sorted(p.name for p in holidays_root.iterdir() if p.is_dir())
    verified_years: list[str] = []
    latest: dict[str, Any] | None = None

    for year in years:
        directory = holidays_root / year
        provenance = _load_json(directory / "provenance.json")
        if provenance is None:
            notes.append(f"{year}: provenance.json missing or unreadable")
            continue
        if not _capture_is_intact(directory, provenance, "en", "raw.en.json"):
            notes.append(f"{year}: raw capture does not match its recorded SHA-256")
            continue
        verified_years.append(year)
        latest = provenance

    if not verified_years or latest is None:
        return notes or ["no intact holiday capture found"]

    fingerprint = "sha256:" + latest["requests"]["en"]["sha256"]
    registry.record_verification(
        HOLIDAY_SOURCE,
        result=VerificationResult.VERIFIED_OFFICIAL,
        at=now,
        retrieved_at=datetime.fromisoformat(latest["retrieved_at"]),
        fingerprint=fingerprint,
        note=(
            f"Imported for {', '.join(verified_years)} from the exchange's own holiday "
            f"endpoint; English and Thai variants cross-checked; "
            f"{latest['holiday_count']} holidays including "
            f"{latest['special_holiday_count']} exchange special holiday(s)."
        ),
    )
    notes.append(f"{HOLIDAY_SOURCE}: VERIFIED_OFFICIAL for {', '.join(verified_years)}")

    # The annual trading calendar is the same underlying data presented differently. We did
    # not fetch that page, so it gets CROSS_CHECKED, not VERIFIED_OFFICIAL.
    registry.record_verification(
        ANNUAL_CALENDAR_SOURCE,
        result=VerificationResult.CROSS_CHECKED,
        at=now,
        retrieved_at=datetime.fromisoformat(latest["retrieved_at"]),
        note=(
            "Trading days are derived from the imported holiday calendar rather than from "
            "this page directly. Shortened sessions are NOT covered and remain unverified."
        ),
    )
    notes.append(f"{ANNUAL_CALENDAR_SOURCE}: CROSS_CHECKED (trading days only)")
    return notes


def update_from_contract_capture(registry: OfficialSourceRegistry, *, now: datetime) -> list[str]:
    directory = OFFICIAL_ROOT / "contracts"
    provenance = _load_json(directory / "provenance.json")
    if provenance is None:
        return ["no contract capture on disk; the product trading calendar remains NOT_VERIFIED"]

    recorded = provenance.get("request", {}).get("sha256")
    raw = directory / "set50_futures_raw.json"
    if not recorded or not raw.is_file():
        return ["contract capture is incomplete"]
    if hashlib.sha256(raw.read_bytes()).hexdigest() != recorded:
        registry.record_verification(
            PRODUCT_CALENDAR_SOURCE,
            result=VerificationResult.CONFLICT,
            at=now,
            note="the stored capture no longer matches its recorded SHA-256",
        )
        return [f"{PRODUCT_CALENDAR_SOURCE}: CONFLICT - capture checksum mismatch"]

    conflicts = provenance.get("conflict_symbols") or []
    unverified = provenance.get("published_unverified_symbols") or []
    verified_count = provenance.get("verified_count", 0)

    if conflicts:
        registry.record_verification(
            PRODUCT_CALENDAR_SOURCE,
            result=VerificationResult.CONFLICT,
            at=now,
            retrieved_at=datetime.fromisoformat(provenance["retrieved_at"]),
            fingerprint="sha256:" + recorded,
            note=(
                f"published and derived last trading days disagree for {conflicts}; "
                f"expiry-dependent processing is blocked for those contracts"
            ),
        )
        return [f"{PRODUCT_CALENDAR_SOURCE}: CONFLICT for {conflicts}"]

    registry.record_verification(
        PRODUCT_CALENDAR_SOURCE,
        result=VerificationResult.VERIFIED_OFFICIAL,
        at=now,
        retrieved_at=datetime.fromisoformat(provenance["retrieved_at"]),
        fingerprint="sha256:" + recorded,
        note=(
            f"{provenance['contract_count']} listed S50 contracts; {verified_count} had their "
            f"published last trading day confirmed against the contract-specification rule "
            f"using the imported holiday calendar. Not cross-checked (no holiday data for "
            f"that year yet): {unverified or 'none'}."
        ),
    )
    return [
        f"{PRODUCT_CALENDAR_SOURCE}: VERIFIED_OFFICIAL "
        f"({verified_count}/{provenance['contract_count']} cross-checked)"
    ]


def corroborate_specification(registry: OfficialSourceRegistry, *, now: datetime) -> list[str]:
    """Check the configured contract terms against the exchange's own series endpoint.

    This does not retrieve the specification page, so the strongest honest claim is
    ``CROSS_CHECKED``: two independent exchange surfaces agree with our configuration.
    """
    config = load_config()
    client = TfexWebClient()
    try:
        response = client.series_info("S50Z26")
        payload = response.json()
    except FetchError as exc:
        registry.record_verification(
            SPECIFICATION_SOURCE,
            result=VerificationResult.UNAVAILABLE,
            at=now,
            note=f"corroboration attempt failed: {exc}",
        )
        return [f"{SPECIFICATION_SOURCE}: UNAVAILABLE - {exc}"]

    SPEC_CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    SPEC_CAPTURE.write_bytes(response.content)

    configured = {
        "contract.tick_size_points": config.contract.tick_size_points,
        "contract.point_value_thb": config.contract.point_value_thb,
    }
    mismatches: list[str] = []
    observed: dict[str, str] = {}
    for api_field, (config_key, _) in SPEC_FIELDS.items():
        raw_value = payload.get(api_field)
        if raw_value is None:
            mismatches.append(f"{api_field} absent from the series payload")
            continue
        value = Decimal(str(raw_value))
        observed[api_field] = str(value)
        if value != configured[config_key]:
            mismatches.append(f"{api_field}={value} but {config_key}={configured[config_key]}")

    if mismatches:
        registry.record_verification(
            SPECIFICATION_SOURCE,
            result=VerificationResult.CONFLICT,
            at=now,
            retrieved_at=response.retrieved_at,
            fingerprint="sha256:" + response.sha256,
            note="configuration disagrees with the exchange: " + "; ".join(mismatches),
        )
        return [f"{SPECIFICATION_SOURCE}: CONFLICT - {'; '.join(mismatches)}"]

    registry.record_verification(
        SPECIFICATION_SOURCE,
        result=VerificationResult.CROSS_CHECKED,
        at=now,
        retrieved_at=response.retrieved_at,
        fingerprint="sha256:" + response.sha256,
        note=(
            f"tick size and point value corroborated against the exchange series endpoint "
            f"for S50Z26 ({observed}). The specification page itself was not retrieved, so "
            f"fee, price-limit and settlement terms remain unverified."
        ),
    )
    return [f"{SPECIFICATION_SOURCE}: CROSS_CHECKED ({observed})"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corroborate-spec",
        action="store_true",
        help="make one read-only call to check the configured contract terms",
    )
    args = parser.parse_args(argv)

    registry = (
        OfficialSourceRegistry.load(REGISTRY_PATH)
        if REGISTRY_PATH.is_file()
        else OfficialSourceRegistry()
    )
    now = datetime.now(UTC)

    notes = update_from_holiday_capture(registry, now=now)
    notes += update_from_contract_capture(registry, now=now)
    if args.corroborate_spec:
        notes += corroborate_specification(registry, now=now)

    registry.save(REGISTRY_PATH)
    DOC_PATH.write_text(registry.render_markdown(generated_at=now), encoding="utf-8")

    print("Verification updates:")
    for note in notes:
        print(f"  - {note}")

    unverified = registry.unverified()
    print(
        f"\n{len(registry)} sources: {len(registry) - len(unverified)} verified, "
        f"{len(unverified)} not verified"
    )
    for record in unverified:
        print(f"  NOT VERIFIED  {record.name}  [{record.last_verification_result}]")
    print(f"\nwrote {REGISTRY_PATH}")
    print(f"wrote {DOC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
