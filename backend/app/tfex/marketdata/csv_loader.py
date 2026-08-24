"""Read a raw market-data CSV into :class:`Bar` objects without judging them.

Two rules shape this module.

**A naive timestamp requires a declared source timezone.** Section 27 and the whole session
model depend on Asia/Bangkok wall-clock time; silently assuming UTC would shift every bar by
seven hours and quietly relabel the morning session as pre-open. So a file whose timestamps
carry no offset is rejected unless the caller states what timezone they are in.

**Bad rows are reported, not dropped.** The loader collects findings and keeps going, so the
validator can show an operator every problem in one pass instead of one per run.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tfex.errors import ConfigurationError
from app.tfex.marketdata.models import Bar, Finding

__all__ = ["COLUMN_ALIASES", "LoadResult", "load_bars"]

#: Accepted spellings for each field. Vendors differ; the platform should not care.
COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "symbol": ("symbol", "ticker", "contract", "instrument", "series"),
    "timestamp": ("timestamp", "datetime", "date_time", "bar_time", "time_stamp", "t"),
    "date": ("date", "trade_date", "bar_date"),
    "time": ("time", "bar_time_only", "trade_time"),
    "open": ("open", "o", "open_price"),
    "high": ("high", "h", "high_price"),
    "low": ("low", "l", "low_price"),
    "close": ("close", "c", "close_price", "last"),
    "volume": ("volume", "vol", "v", "quantity", "qty"),
    "trade_count": ("trade_count", "trades", "num_trades", "n_trades", "count"),
    "open_interest": ("open_interest", "oi", "openinterest"),
    "bid": ("bid", "bid_price"),
    "ask": ("ask", "ask_price", "offer", "offer_price"),
    "settlement_price": ("settlement_price", "settlement", "settle"),
    "source_sequence": ("source_sequence", "sequence", "seq", "sequence_no"),
}

_REQUIRED = ("open", "high", "low", "close", "volume")


class LoadResult:
    """Bars that parsed, plus a finding for every row that did not."""

    def __init__(self, bars: list[Bar], findings: list[Finding], row_count: int) -> None:
        self.bars = bars
        self.findings = findings
        self.row_count = row_count
        """Data rows seen in the file, including those that failed to parse."""


def _normalise_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_").lstrip("﻿")


def _resolve_columns(header: Sequence[str]) -> dict[str, str]:
    normalised = {_normalise_header(h): h for h in header}
    resolved: dict[str, str] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                resolved[field_name] = normalised[alias]
                break
    return resolved


def _decimal(raw: str, field_name: str) -> Decimal:
    text = raw.strip().replace(",", "")
    if not text:
        raise ValueError(f"{field_name} is empty")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name}={raw!r} is not a number") from exc
    if not value.is_finite():
        raise ValueError(f"{field_name}={raw!r} is not finite")
    return value


def _optional_decimal(raw: str | None, field_name: str) -> Decimal | None:
    if raw is None or not raw.strip():
        return None
    return _decimal(raw, field_name)


def _integer(raw: str, field_name: str) -> int:
    text = raw.strip().replace(",", "")
    if not text:
        raise ValueError(f"{field_name} is empty")
    try:
        # Accept "1234.0" from exporters that write every numeric column as a float.
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name}={raw!r} is not a number") from exc
    if not value.is_finite():
        raise ValueError(f"{field_name}={raw!r} is not finite")
    if value != value.to_integral_value():
        raise ValueError(f"{field_name}={raw!r} is not a whole number")
    return int(value)


def _optional_integer(raw: str | None, field_name: str) -> int | None:
    if raw is None or not raw.strip():
        return None
    return _integer(raw, field_name)


def _parse_timestamp(raw: str, tz: ZoneInfo, field_name: str) -> datetime:
    text = raw.strip()
    if not text:
        raise ValueError(f"{field_name} is empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y%m%d %H%M%S", "%Y%m%d%H%M%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"{field_name}={raw!r} is not a recognisable timestamp") from None
    if parsed.tzinfo is None:
        # Declared, never assumed. The caller had to state the source timezone to get here.
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def load_bars(
    path: Path | str,
    *,
    source_timezone: str | None,
    symbol: str | None = None,
) -> LoadResult:
    """Load a CSV into bars, converting every timestamp into ``source_timezone``.

    Args:
        source_timezone: the timezone the file's naive timestamps are in. Required —
            passing ``None`` is an error, not a licence to assume UTC. Timestamps that carry
            their own offset are converted into this zone rather than being reinterpreted.
        symbol: used only when the file has no symbol column.

    Raises:
        ConfigurationError: no source timezone, unknown zone, unreadable file, or a header
            missing a required OHLCV column.
    """
    if source_timezone is None:
        raise ConfigurationError(
            "a source timezone must be declared for market-data import; naive timestamps are "
            "ambiguous and must never be assumed to be UTC"
        )
    try:
        tz = ZoneInfo(source_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigurationError(f"unknown source timezone {source_timezone!r}: {exc}") from exc

    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigurationError(f"cannot read market-data file {file_path}: {exc}") from exc

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ConfigurationError(f"{file_path} has no header row")

    columns = _resolve_columns(reader.fieldnames)
    missing = [name for name in _REQUIRED if name not in columns]
    if missing:
        raise ConfigurationError(
            f"{file_path} is missing required column(s) {missing}; header was "
            f"{list(reader.fieldnames)}"
        )
    if "timestamp" not in columns and not ("date" in columns and "time" in columns):
        raise ConfigurationError(
            f"{file_path} has no timestamp column and no date+time pair; header was "
            f"{list(reader.fieldnames)}"
        )
    if "symbol" not in columns and symbol is None:
        raise ConfigurationError(
            f"{file_path} has no symbol column and no --symbol was supplied; a bar that does "
            f"not know its contract cannot be validated"
        )

    bars: list[Bar] = []
    findings: list[Finding] = []
    row_count = 0

    for line_number, row in enumerate(reader, start=2):
        row_count += 1
        try:
            if "timestamp" in columns:
                stamp = _parse_timestamp(row[columns["timestamp"]] or "", tz, "timestamp")
            else:
                combined = f"{row[columns['date']].strip()} {row[columns['time']].strip()}"
                stamp = _parse_timestamp(combined, tz, "date+time")

            row_symbol = (
                row[columns["symbol"]].strip().upper() if "symbol" in columns else str(symbol)
            )
            if not row_symbol:
                raise ValueError("symbol is empty")

            bars.append(
                Bar(
                    symbol=row_symbol,
                    timestamp=stamp,
                    open=_decimal(row[columns["open"]] or "", "open"),
                    high=_decimal(row[columns["high"]] or "", "high"),
                    low=_decimal(row[columns["low"]] or "", "low"),
                    close=_decimal(row[columns["close"]] or "", "close"),
                    volume=_integer(row[columns["volume"]] or "", "volume"),
                    trade_count=_optional_integer(
                        row.get(columns.get("trade_count", "")), "trade_count"
                    ),
                    bid=_optional_decimal(row.get(columns.get("bid", "")), "bid"),
                    ask=_optional_decimal(row.get(columns.get("ask", "")), "ask"),
                    open_interest=_optional_integer(
                        row.get(columns.get("open_interest", "")), "open_interest"
                    ),
                    settlement_price=_optional_decimal(
                        row.get(columns.get("settlement_price", "")), "settlement_price"
                    ),
                    source_sequence=_optional_integer(
                        row.get(columns.get("source_sequence", "")), "source_sequence"
                    ),
                    line_number=line_number,
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            findings.append(Finding(f"unparseable row: {exc}", line_number=line_number))

    return LoadResult(bars, findings, row_count)
