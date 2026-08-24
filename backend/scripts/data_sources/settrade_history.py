"""Settrade Open API historical candlestick downloader — and the probe that must run first.

**Nothing in this module fabricates a response.** Without credentials it does exactly one
thing: explain what is missing. `docs/tfex_historical_data_sources.md` records why that
matters — the published documentation proves the API has a ``1m`` interval, and proves
nothing about whether SET50 futures *contract* symbols are served or how far back.

So there are two modes:

``--probe``
    One read-only ``get_candlestick`` call for a small window, whose purpose is to answer
    the open questions and write the answers to an evidence file. It places no orders.

``--symbol/--start/--end``
    Windowed download into ``data/tfex/historical/raw/<SYMBOL>/``, with a dataset manifest.

Credentials come from the environment and are never logged, printed, or written to disk::

    SETTRADE_APP_ID
    SETTRADE_APP_SECRET
    SETTRADE_BROKER_ID
    SETTRADE_APP_CODE

Add the SDK when you are ready to use it — it is deliberately not a project dependency::

    uv add --dev settrade-v2
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from app.tfex.marketdata.manifest import (
    HISTORICAL_RAW_ROOT,
    build_manifest,
    save_manifest,
)
from app.tfex.marketdata.models import BarInterval

REQUIRED_ENV = ("SETTRADE_APP_ID", "SETTRADE_APP_SECRET", "SETTRADE_BROKER_ID", "SETTRADE_APP_CODE")

EVIDENCE_PATH = BACKEND_ROOT / "data" / "tfex" / "official" / "settrade_capability.json"

#: Documented in the SDK's `subscribe_candlestick` docstring (settrade-v2 2.2.1).
DOCUMENTED_INTERVALS = (
    "1m",
    "3m",
    "5m",
    "10m",
    "15m",
    "30m",
    "60m",
    "120m",
    "240m",
    "1d",
    "1w",
    "1M",
)


class CredentialsMissing(RuntimeError):
    """The operator has not provided Open API credentials."""


class SdkMissing(RuntimeError):
    """The optional `settrade-v2` package is not installed."""


def _credentials() -> dict[str, str]:
    """Read credentials from the environment. Never logs or returns them for printing."""
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise CredentialsMissing(
            "missing environment variable(s): "
            + ", ".join(missing)
            + ". Export them in your shell; do not put them in a file in this repository."
        )
    return {name: os.environ[name] for name in REQUIRED_ENV}


def _investor(environment: str) -> Any:
    """Build an authenticated SDK client. Imported lazily so the script runs without the SDK."""
    try:
        from settrade_v2 import Investor  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on the operator's environment
        raise SdkMissing(
            "the settrade-v2 SDK is not installed. Install it with `uv add --dev settrade-v2`. "
            "It is optional on purpose: this repository must build and test without broker "
            "credentials."
        ) from exc

    credentials = _credentials()
    return Investor(
        app_id=credentials["SETTRADE_APP_ID"],
        app_secret=credentials["SETTRADE_APP_SECRET"],
        broker_id=credentials["SETTRADE_BROKER_ID"],
        app_code=credentials["SETTRADE_APP_CODE"],
        is_auto_queue=False,
        environment=environment,
    )


def probe(symbol: str, *, environment: str, interval: str = "1m") -> dict[str, Any]:
    """Answer the open capability questions with one read-only call.

    Returns an evidence dictionary. Raises nothing on an API error — a refusal *is* the
    evidence, and recording "the API rejected S50Z26" is more useful than a traceback.
    """
    evidence: dict[str, Any] = {
        "probed_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "symbol": symbol,
        "interval": interval,
        "documented_intervals": list(DOCUMENTED_INTERVALS),
        "sdk_available": False,
        "credentials_present": all(os.environ.get(n) for n in REQUIRED_ENV),
        "historical_derivatives_candlestick": "UNKNOWN",
        "raw_contract_symbol_supported": "UNKNOWN",
        "one_minute_interval_supported": "UNKNOWN",
        "bars_returned": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "error": None,
    }

    end = date.today()
    start = end - timedelta(days=7)

    try:
        investor = _investor(environment)
        evidence["sdk_available"] = True
        market = investor.MarketData()
        response = market.get_candlestick(
            symbol=symbol,
            interval=interval,
            start=start.isoformat(),
            end=end.isoformat(),
        )
    except (CredentialsMissing, SdkMissing) as exc:
        evidence["error"] = str(exc)
        return evidence
    except Exception as exc:  # broad on purpose: an API refusal is the finding
        evidence["sdk_available"] = True
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["raw_contract_symbol_supported"] = "NOT_SUPPORTED_OR_UNENTITLED"
        return evidence

    raw_times = response.get("time") if isinstance(response, dict) else None
    times: list[Any] = raw_times if isinstance(raw_times, list) else []
    count = len(times)
    evidence["bars_returned"] = count
    if count:
        evidence["historical_derivatives_candlestick"] = "CONFIRMED"
        evidence["raw_contract_symbol_supported"] = "CONFIRMED"
        evidence["one_minute_interval_supported"] = "CONFIRMED" if interval == "1m" else "UNKNOWN"
        evidence["first_timestamp"] = str(times[0])
        evidence["last_timestamp"] = str(times[-1])
        evidence["response_keys"] = sorted(response)
    else:
        evidence["historical_derivatives_candlestick"] = "NO_DATA_RETURNED"
    return evidence


def _rows_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Transpose the API's column-oriented payload into rows.

    The techchart service returns parallel arrays (``time``, ``open``, ``high``, ``low``,
    ``close``, ``volume``). Anything else is left alone and reported rather than guessed at.
    """
    required = ("time", "open", "high", "low", "close", "volume")
    missing = [key for key in required if key not in response]
    if missing:
        raise RuntimeError(
            f"unexpected candlestick payload: missing {missing}; keys were {sorted(response)}"
        )
    columns = [response[key] for key in required]
    lengths = {len(column) for column in columns}
    if len(lengths) != 1:
        raise RuntimeError(f"candlestick columns have mismatched lengths: {lengths}")
    return [dict(zip(required, values, strict=True)) for values in zip(*columns, strict=True)]


def download(
    symbol: str,
    *,
    interval: str,
    start: date,
    end: date,
    environment: str,
) -> Path:
    """Download a window into the immutable raw directory, with a manifest beside it."""
    investor = _investor(environment)
    market = investor.MarketData()
    response = market.get_candlestick(
        symbol=symbol, interval=interval, start=start.isoformat(), end=end.isoformat()
    )
    rows = _rows_from_response(response)
    if not rows:
        raise RuntimeError(
            f"the API returned no bars for {symbol} {interval} {start}..{end}; refusing to "
            f"write an empty dataset"
        )

    directory = HISTORICAL_RAW_ROOT / symbol.upper()
    directory.mkdir(parents=True, exist_ok=True)
    destination = (
        directory / f"{symbol.upper()}_{interval}_{start.isoformat()}_{end.isoformat()}.csv"
    )

    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row["time"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
            )

    manifest = build_manifest(
        destination,
        dataset_id=f"{symbol.lower()}-{interval}-{start.isoformat()}-{end.isoformat()}",
        source="Settrade Open API (techchart candlesticks)",
        authority="Settrade / Stock Exchange of Thailand",
        symbol=symbol,
        interval=BarInterval(interval),
        source_timezone="Asia/Bangkok",
        license="Settrade Open API terms of use - confirm redistribution rights before sharing",
        synthetic=False,
        note=f"Downloaded from the {environment} environment.",
    )
    save_manifest(manifest, destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="contract symbol, e.g. S50Z26")
    parser.add_argument("--interval", default="1m", choices=list(DOCUMENTED_INTERVALS))
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--environment", default="prod", choices=("prod", "uat"))
    parser.add_argument(
        "--probe",
        action="store_true",
        help="make one read-only call to establish capability, and write the evidence file",
    )
    args = parser.parse_args(argv)

    if args.probe:
        evidence = probe(args.symbol, environment=args.environment, interval=args.interval)
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
        print(f"\nwrote {EVIDENCE_PATH}")
        if evidence["error"]:
            print(
                "\nThe probe could not confirm capability. Nothing was fabricated in its "
                "place; docs/tfex_historical_data_sources.md still reads REAL_1M_DATA_BLOCKED.",
                file=sys.stderr,
            )
            return 3
        return 0

    if not args.start or not args.end:
        parser.error("--start and --end are required unless --probe is given")

    try:
        destination = download(
            args.symbol,
            interval=args.interval,
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            environment=args.environment,
        )
    except (CredentialsMissing, SdkMissing) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # broad on purpose: report, never write a partial dataset
        print(f"DOWNLOAD FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {destination}")
    print("Validate it before use:")
    print(
        f"  uv run python scripts/validate_tfex_market_data.py --file {destination} "
        f"--symbol {args.symbol} --interval {args.interval} --timezone Asia/Bangkok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
