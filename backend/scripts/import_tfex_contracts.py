"""Import the official SET50 Index Futures contract calendar (first/last trading days).

Source of truth: the exchange's own series endpoint, the one the SET50 Index Futures trading
calendar page fetches. Single Stock Futures and SET50 Options calendars are **not** used —
they are different products with different dates.

Every imported contract is cross-checked against the derived rule from the contract
specification:

    last trading day = the business day immediately preceding
                       the last business day of the contract month

Agreement is recorded as ``VERIFIED``. Disagreement is recorded as ``CONFLICT`` and blocks
expiry-dependent processing; the importer never silently picks a side. Where the holiday
data needed for the derived rule has not been imported, the contract is recorded as
``PUBLISHED_UNVERIFIED`` — published, but not yet cross-checked.

Usage::

    uv run python scripts/import_tfex_contracts.py
    uv run python scripts/import_tfex_contracts.py --root S50 --no-merge
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.service import TradingCalendar
from app.tfex.calendar.trading_day import TradingDayCalculator
from app.tfex.config import load_config
from app.tfex.errors import CalendarError
from scripts.data_sources.tfex_web import FetchError, RawResponse, TfexWebClient

OFFICIAL_ROOT = BACKEND_ROOT / "data" / "tfex" / "official" / "contracts"
STORE_ROOT = BACKEND_ROOT / "data" / "tfex" / "holidays"

SOURCE_ID = "tfex-set50-futures-series"
AUTHORITY = "Thailand Futures Exchange"
SOURCE_TYPE = "OFFICIAL_EXCHANGE"
PARSER_VERSION = "tfex-series-parser/1"
IMPORTER_VERSION = "import_tfex_contracts/1"

STATUS_VERIFIED = "VERIFIED"
STATUS_CONFLICT = "CONFLICT"
STATUS_PUBLISHED_UNVERIFIED = "PUBLISHED_UNVERIFIED"

_MINIMUM_TRADING_DAYS_IN_MONTH = 2


@dataclass(frozen=True, slots=True)
class ImportedContract:
    symbol: str
    contract_year: int
    contract_month: int
    first_trading_day: date | None
    published_last_trading_day: date
    published_last_trading_time: time
    derived_last_trading_day: date | None
    derivation_note: str
    status: str

    @property
    def contract_month_label(self) -> str:
        return f"{self.contract_year:04d}-{self.contract_month:02d}"

    @property
    def cross_checked(self) -> bool:
        return self.derived_last_trading_day is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "contract_month": self.contract_month_label,
            "first_trading_day": (
                self.first_trading_day.isoformat() if self.first_trading_day else None
            ),
            "last_trading_day": self.published_last_trading_day.isoformat(),
            "last_trading_time": self.published_last_trading_time.isoformat(),
            "timezone": "Asia/Bangkok",
            "published": True,
            "derived_last_trading_day": (
                self.derived_last_trading_day.isoformat() if self.derived_last_trading_day else None
            ),
            "derived_cross_check": self.cross_checked,
            "derivation_note": self.derivation_note,
            "status": self.status,
            "source_id": SOURCE_ID,
        }


def derive_last_trading_day(
    trading_days: TradingDayCalculator, year: int, month: int
) -> tuple[date | None, str]:
    """Apply the contract-specification rule, or explain why it cannot be applied."""
    try:
        month_days = trading_days.trading_days_in_month(year, month)
    except CalendarError as exc:
        return None, f"cannot derive: {exc}"
    if len(month_days) < _MINIMUM_TRADING_DAYS_IN_MONTH:
        return None, (
            f"cannot derive: {year}-{month:02d} has {len(month_days)} trading day(s) in the "
            f"imported calendar"
        )
    return month_days[-2], (
        f"business day before the last business day of {year}-{month:02d} "
        f"(last business day {month_days[-1].isoformat()})"
    )


def parse_series(
    response: RawResponse,
    trading_days: TradingDayCalculator,
    *,
    root: str,
) -> list[ImportedContract]:
    payload = response.json()
    series = payload.get("series") if isinstance(payload, dict) else None
    if not isinstance(series, list):
        raise FetchError(f"{response.url} did not return a 'series' list")

    pattern = re.compile(rf"^{re.escape(root)}[FGHJKMNQUVXZ]\d{{2}}$")
    contracts: list[ImportedContract] = []

    for row in series:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not pattern.match(symbol):
            continue

        contract_month = str(row.get("contractMonth", ""))
        if not re.match(r"^\d{2}/\d{4}$", contract_month):
            raise FetchError(f"{symbol}: unexpected contractMonth {contract_month!r}")
        month_text, year_text = contract_month.split("/")
        year, month = int(year_text), int(month_text)

        last_raw = row.get("lastTradingDate")
        if not last_raw:
            raise FetchError(f"{symbol}: the exchange returned no lastTradingDate")
        last_dt = datetime.fromisoformat(str(last_raw))

        first_raw = row.get("firstTradingDate")
        first_day = datetime.fromisoformat(str(first_raw)).date() if first_raw else None

        derived, note = derive_last_trading_day(trading_days, year, month)
        if derived is None:
            status = STATUS_PUBLISHED_UNVERIFIED
        elif derived == last_dt.date():
            status = STATUS_VERIFIED
        else:
            status = STATUS_CONFLICT

        contracts.append(
            ImportedContract(
                symbol=symbol,
                contract_year=year,
                contract_month=month,
                first_trading_day=first_day,
                published_last_trading_day=last_dt.date(),
                published_last_trading_time=last_dt.time(),
                derived_last_trading_day=derived,
                derivation_note=note,
                status=status,
            )
        )

    if not contracts:
        raise FetchError(
            f"no {root} futures contracts found in {response.url}; refusing to write an empty "
            f"contract calendar"
        )
    return sorted(contracts, key=lambda c: (c.contract_year, c.contract_month))


def write_official_capture(
    response: RawResponse, contracts: list[ImportedContract], *, stale_after_days: int
) -> Path:
    OFFICIAL_ROOT.mkdir(parents=True, exist_ok=True)
    (OFFICIAL_ROOT / "set50_futures_raw.json").write_bytes(response.content)

    _write_json(
        OFFICIAL_ROOT / "set50_futures.json",
        {
            "exchange": "TFEX",
            "instrument": "SET50 Index Futures",
            "instrument_id": "SET50_FC",
            "market_list_id": "TXI_F",
            "timezone": "Asia/Bangkok",
            "contracts": [c.to_json() for c in contracts],
        },
    )

    conflicts = [c.symbol for c in contracts if c.status == STATUS_CONFLICT]
    unverified = [c.symbol for c in contracts if c.status == STATUS_PUBLISHED_UNVERIFIED]
    _write_json(
        OFFICIAL_ROOT / "provenance.json",
        {
            "source_id": SOURCE_ID,
            "authority": AUTHORITY,
            "source_type": SOURCE_TYPE,
            "source_title": "SET50 Index Futures series / trading calendar",
            "status": "CONFLICT" if conflicts else "VERIFIED_OFFICIAL",
            "verification_basis": (
                "published first/last trading dates retrieved from the exchange series "
                "endpoint, each cross-checked against the contract-specification rule using "
                "the imported official holiday calendar"
            ),
            "retrieved_at": response.retrieved_at.isoformat(),
            "stale_after": (response.retrieved_at + timedelta(days=stale_after_days)).isoformat(),
            "parser_version": PARSER_VERSION,
            "importer_version": IMPORTER_VERSION,
            "contract_count": len(contracts),
            "verified_count": sum(1 for c in contracts if c.status == STATUS_VERIFIED),
            "conflict_symbols": conflicts,
            "published_unverified_symbols": unverified,
            "request": response.describe(),
            "human_page": (
                "https://www.tfex.co.th/en/products/equity/set50-index-futures/trading-calendar"
            ),
            "specification_page": (
                "https://www.tfex.co.th/en/products/equity/set50-index-futures/"
                "contract-specification"
            ),
            "notes": (
                "set50_futures_raw.json is an immutable capture; its SHA-256 is recorded "
                "above. CONFLICT means the published date and the derived rule disagree and "
                "expiry-dependent processing must stop until it is resolved."
            ),
        },
    )
    return OFFICIAL_ROOT


def merge_into_store(contracts: list[ImportedContract]) -> list[Path]:
    """Write published dates into the per-year files that ``ExpiryResolver`` reads.

    Contracts in `CONFLICT` are deliberately **not** merged: publishing a date the calendar
    disagrees with would resolve the conflict by fiat. They stay in the official capture and
    in the report until an operator settles them.
    """
    written: list[Path] = []
    by_year: dict[int, list[ImportedContract]] = {}
    for contract in contracts:
        if contract.status == STATUS_CONFLICT:
            continue
        by_year.setdefault(contract.contract_year, []).append(contract)

    for year, year_contracts in sorted(by_year.items()):
        path = STORE_ROOT / f"{year}.json"
        if not path.is_file():
            print(
                f"  {year}: no holiday file yet, skipping merge of "
                f"{[c.symbol for c in year_contracts]} "
                f"(import holidays for {year} first)"
            )
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["published_contract_dates"] = [
            {
                "contract_year": c.contract_year,
                "contract_month": c.contract_month,
                "first_trading_date": (
                    c.first_trading_day.isoformat() if c.first_trading_day else None
                ),
                "last_trading_date": c.published_last_trading_day.isoformat(),
                "note": f"{c.symbol} published by TFEX; cross-check {c.status}",
            }
            for c in sorted(year_contracts, key=lambda c: c.contract_month)
        ]
        _write_json(path, payload)
        written.append(path)
    return written


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="S50", help="contract root to import (default S50)")
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="write the official capture only; do not update data/tfex/holidays/<year>.json",
    )
    args = parser.parse_args(argv)

    config = load_config()
    store = HolidayStore()
    calendar = TradingCalendar(config, store)

    client = TfexWebClient()
    try:
        response = client.series_list()
        contracts = parse_series(response, calendar.trading_days, root=args.root)
    except FetchError as exc:
        print(f"IMPORT FAILED - {exc}", file=sys.stderr)
        return 1

    directory = write_official_capture(
        response, contracts, stale_after_days=config.metadata.holiday_data_stale_after_days
    )

    print(f"\nImported {len(contracts)} {args.root} futures contracts")
    print(f"  raw capture  {directory / 'set50_futures_raw.json'}")
    print(f"  sha256       {response.sha256}\n")
    header = f"{'Symbol':<8} {'Month':<9} {'First':<12} {'Published':<12} {'Derived':<12} Status"
    print(header)
    print("-" * len(header))
    for contract in contracts:
        first = contract.first_trading_day.isoformat() if contract.first_trading_day else "-"
        derived = (
            contract.derived_last_trading_day.isoformat()
            if contract.derived_last_trading_day
            else "-"
        )
        print(
            f"{contract.symbol:<8} {contract.contract_month_label:<9} {first:<12} "
            f"{contract.published_last_trading_day.isoformat():<12} {derived:<12} "
            f"{contract.status}"
        )

    conflicts = [c for c in contracts if c.status == STATUS_CONFLICT]
    if conflicts:
        print("\nCONFLICT - published and derived last trading days disagree:", file=sys.stderr)
        for contract in conflicts:
            print(
                f"  {contract.symbol}: published "
                f"{contract.published_last_trading_day.isoformat()} vs derived "
                f"{contract.derived_last_trading_day} ({contract.derivation_note})",
                file=sys.stderr,
            )
        print("  Expiry-dependent processing is blocked for these contracts.", file=sys.stderr)

    if not args.no_merge:
        print("\nMerging published dates into the calendar store:")
        for path in merge_into_store(contracts):
            print(f"  wrote {path}")

    print(f"\nGenerated at {datetime.now(UTC).isoformat()}")
    return 2 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
