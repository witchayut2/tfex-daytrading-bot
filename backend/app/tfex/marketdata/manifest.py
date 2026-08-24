"""Dataset manifests: what a replay cites so its result can be reproduced.

Section 30 requires backtests to be reproducible. A run that says "I used the S50Z26
1-minute data" is not reproducible; a run that says "I used dataset ``s50z26-1m-2026h2``,
SHA-256 ``a3f2…``, validated by ``tfex-market-data-validator/1``" is.

The manifest sits next to the raw file it describes and is written once. Raw files under
``data/tfex/historical/raw/`` are immutable inputs — normalization writes elsewhere.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.tfex.errors import ConfigurationError
from app.tfex.marketdata.models import Bar, BarInterval, DatasetManifest

__all__ = [
    "HISTORICAL_NORMALIZED_ROOT",
    "HISTORICAL_RAW_ROOT",
    "build_manifest",
    "file_sha256",
    "load_manifest",
    "manifest_path_for",
    "save_manifest",
]

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
HISTORICAL_RAW_ROOT = _BACKEND_ROOT / "data" / "tfex" / "historical" / "raw"
HISTORICAL_NORMALIZED_ROOT = _BACKEND_ROOT / "data" / "tfex" / "historical" / "normalized"

_CHUNK = 1 << 20


def file_sha256(path: Path | str) -> str:
    """Stream the file so a multi-hundred-megabyte tick export does not have to fit in RAM."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path_for(data_file: Path | str) -> Path:
    path = Path(data_file)
    return path.with_suffix(path.suffix + ".manifest.json")


def build_manifest(
    data_file: Path | str,
    *,
    dataset_id: str,
    source: str,
    symbol: str,
    interval: BarInterval,
    source_timezone: str,
    bars: list[Bar] | None = None,
    authority: str | None = None,
    license: str | None = None,
    retrieved_at: datetime | None = None,
    synthetic: bool = False,
    note: str | None = None,
) -> DatasetManifest:
    """Describe a data file, deriving the checksum and range from the file itself."""
    path = Path(data_file)
    ordered = sorted(bars, key=lambda b: b.timestamp) if bars else []
    return DatasetManifest(
        dataset_id=dataset_id,
        source=source,
        authority=authority,
        retrieved_at=retrieved_at or datetime.now(UTC),
        license=license,
        original_filename=path.name,
        sha256=file_sha256(path),
        symbol=symbol.strip().upper(),
        interval=interval,
        source_timezone=source_timezone,
        record_count=len(ordered),
        first_timestamp=ordered[0].timestamp if ordered else None,
        last_timestamp=ordered[-1].timestamp if ordered else None,
        trading_days=len({b.trading_date for b in ordered}) or None,
        synthetic=synthetic,
        note=note,
    )


def save_manifest(manifest: DatasetManifest, data_file: Path | str) -> Path:
    path = manifest_path_for(data_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_manifest(data_file: Path | str, *, verify_checksum: bool = True) -> DatasetManifest:
    """Load the manifest beside ``data_file``.

    Raises:
        ConfigurationError: the manifest is missing, malformed, or no longer describes the
            file — a checksum mismatch means the "immutable" raw input was edited, and every
            result citing it is void.
    """
    path = manifest_path_for(data_file)
    if not path.is_file():
        raise ConfigurationError(
            f"no dataset manifest at {path}; every market-data file needs provenance before "
            f"it can be validated (see docs/tfex_historical_data_sources.md)"
        )
    try:
        manifest = DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise ConfigurationError(f"invalid dataset manifest at {path}: {exc}") from exc

    if verify_checksum:
        actual = file_sha256(data_file)
        if actual != manifest.sha256:
            raise ConfigurationError(
                f"{Path(data_file).name} has SHA-256 {actual} but its manifest records "
                f"{manifest.sha256}; the raw input has been modified and any result citing "
                f"this dataset is void"
            )
    return manifest


def write_report_json(report_dict: dict[str, object], destination: Path | str) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report_dict, indent=2, default=str) + "\n", encoding="utf-8")
    return path
