"""Manifest-aware raw-contract CSV input for TFEX-2 replay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.tfex.errors import ReplayError
from app.tfex.marketdata.csv_loader import load_bars
from app.tfex.marketdata.manifest import load_manifest
from app.tfex.marketdata.models import Bar, BarInterval, DatasetManifest

__all__ = ["CsvReplayInput", "load_csv_replay_input"]


@dataclass(frozen=True, slots=True)
class CsvReplayInput:
    path: Path
    manifest: DatasetManifest
    bars: tuple[Bar, ...]


def load_csv_replay_input(
    path: Path | str,
    *,
    require_real: bool = False,
) -> CsvReplayInput:
    """Load immutable one-minute bars while preserving manifest identity and checksum."""
    data_path = Path(path)
    manifest = load_manifest(data_path, verify_checksum=True)
    if manifest.interval is not BarInterval.ONE_MINUTE:
        raise ReplayError(f"TFEX-2 replay requires 1m source bars, not {manifest.interval.value}")
    if require_real and not manifest.is_real_market_data:
        raise ReplayError("real-data replay requires a verified, non-synthetic manifest")

    loaded = load_bars(
        data_path,
        source_timezone=manifest.source_timezone,
        symbol=manifest.symbol,
    )
    if loaded.findings:
        raise ReplayError(
            f"{data_path} has {len(loaded.findings)} unparseable row(s); replay never drops rows"
        )
    if loaded.row_count != manifest.record_count:
        raise ReplayError(
            f"manifest records {manifest.record_count} rows but CSV contains {loaded.row_count}"
        )
    if any(bar.symbol != manifest.symbol for bar in loaded.bars):
        raise ReplayError("CSV bar symbol differs from the manifest raw contract symbol")
    return CsvReplayInput(data_path, manifest, tuple(loaded.bars))
