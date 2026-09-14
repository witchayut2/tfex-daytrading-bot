"""Settrade Open API historical candlestick downloader — and the probe that must run first.

**Nothing in this module fabricates a response.** Without credentials it does exactly one
thing: explain what is missing. `docs/tfex_historical_data_sources.md` records why that
matters — the published documentation proves the API has a ``1m`` interval, and proves
nothing about whether SET50 futures *contract* symbols are served or how far back.

So there are three modes:

``--probe``
    One focused read-only stage selected by ``--probe-mode``: SDK authentication only, one
    symbol quote, or one ``get_candlestick`` request. It writes sanitized evidence and
    never touches account or order APIs.

``--symbol/--start/--end``
    Session-windowed acquisition into immutable ``raw/<SYMBOL>/<DATASET_ID>/`` responses
    plus a validation-ready ``normalized/<SYMBOL>/`` CSV and checksum manifest.

``--extend-parent``
    Verify one validated four-day interim dataset and all of its raw-capture checksums,
    acquire one later complete trading day, then atomically publish a new five-day dataset
    with explicit parent and raw-capture lineage. The parent files are never modified.

``--diagnose-session``
    Exactly one continuous-session request. It prints sanitized response shape and timestamp
    boundaries, writes no bar data, and never touches account or order APIs.

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
import re
import shutil
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from importlib import import_module
from inspect import signature
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from typing import Any
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from app.tfex.calendar import HolidayStore, TradingCalendar
from app.tfex.config import load_config
from app.tfex.contracts.metadata import ContractResolver
from app.tfex.marketdata.csv_loader import LoadResult, load_bars
from app.tfex.marketdata.manifest import (
    HISTORICAL_NORMALIZED_ROOT,
    HISTORICAL_RAW_ROOT,
    build_manifest,
    file_sha256,
    load_manifest,
    manifest_path_for,
    save_manifest,
)
from app.tfex.marketdata.models import (
    BarInterval,
    CheckStatus,
    DatasetDateRange,
    DatasetManifest,
    SourceCapture,
    ValidationOutcome,
    ValidationReport,
)
from app.tfex.marketdata.validation import VALIDATOR_VERSION, MarketDataValidator
from app.tfex.sessions.engine import SessionEngine

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

SETTRADE_REAL_DATA_READY = "SETTRADE_REAL_DATA_READY"
SETTRADE_AUTH_REQUIRED = "SETTRADE_AUTH_REQUIRED"
SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING = "SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING"
SETTRADE_1M_HISTORY_NOT_SUPPORTED = "SETTRADE_1M_HISTORY_NOT_SUPPORTED"
SETTRADE_RAW_CONTRACT_NOT_SUPPORTED = "SETTRADE_RAW_CONTRACT_NOT_SUPPORTED"
SETTRADE_SDK_API_INCOMPATIBLE = "SETTRADE_SDK_API_INCOMPATIBLE"
SETTRADE_REQUEST_INVALID = "SETTRADE_REQUEST_INVALID"
SETTRADE_SYMBOL_INVALID = "SETTRADE_SYMBOL_INVALID"
SETTRADE_INTERVAL_INVALID = "SETTRADE_INTERVAL_INVALID"
SETTRADE_DATE_RANGE_INVALID = "SETTRADE_DATE_RANGE_INVALID"
SETTRADE_AUTHENTICATION_CONFIRMED = "SETTRADE_AUTHENTICATION_CONFIRMED"
SETTRADE_SYMBOL_RECOGNIZED = "SETTRADE_SYMBOL_RECOGNIZED"
SETTRADE_PROBE_FAILED = "SETTRADE_PROBE_FAILED"

PROBE_MODES = ("authentication", "quote", "candlestick")
SETTRADE_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
SETTRADE_DATETIME_PATTERN = "YYYY-MM-DDTHH:MM"
MARKET_TIMEZONE = ZoneInfo("Asia/Bangkok")
DOWNLOAD_MIN_TRADING_DAYS = 5
DOWNLOAD_MAX_TRADING_DAYS = 10
DOWNLOAD_REQUEST_LIMIT = 200
DOWNLOAD_REQUEST_DELAY_SECONDS = 1.1
DOWNLOAD_BROKER_NAME = "InnovestX"
DOWNLOAD_LICENSE = "UNVERIFIED_FOR_REPOSITORY_COMMIT_OR_REDISTRIBUTION"
DOWNLOAD_SOURCE = "Settrade Open API production historical candlesticks"
DOWNLOAD_AUTHORITY = "Settrade / Stock Exchange of Thailand"

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|api[-_ ]?key|app[-_ ]?id|"
    r"app[-_ ]?secret|access[-_ ]?token|refresh[-_ ]?token|token|pin|password|"
    r"account[-_ ]?(?:number|no))\b(\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[^\s,;&]+")
_JWT_TOKEN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_SENSITIVE_FIELD_NAME = re.compile(
    r"(?i)(authorization|cookie|api[-_ ]?key|app[-_ ]?(?:id|secret)|"
    r"access[-_ ]?token|refresh[-_ ]?token|token|pin|password|account)"
)


class CredentialsMissing(RuntimeError):
    """The operator has not provided Open API credentials."""


class SdkMissing(RuntimeError):
    """The optional `settrade-v2` package is not installed."""


class SdkCompatibilityError(RuntimeError):
    """The installed SDK does not expose the API shape verified for this probe."""


@dataclass(frozen=True)
class SdkBindings:
    """The small, read-only portion of settrade-v2 used by this script."""

    investor_class: Any
    version: str
    investor_signature: str


@dataclass(frozen=True)
class DownloadWindow:
    """One bounded continuous-session request; no window may cross the midday break."""

    trading_date: date
    session: str
    start: datetime
    end: datetime
    expected_bar_slots: int

    @property
    def filename(self) -> str:
        return f"{self.trading_date.isoformat()}_{self.session}.settrade.json"


@dataclass(frozen=True)
class DownloadResult:
    """Paths and request count produced by one immutable acquisition batch."""

    raw_directory: Path
    normalized_file: Path
    manifest_file: Path
    candlestick_requests: int


class AcquisitionFailure(RuntimeError):
    """A safely reportable failure at one precisely identified acquisition stage."""

    def __init__(
        self,
        *,
        stage: str,
        category: str,
        message: str,
        window: DownloadWindow | None = None,
        requested_limit: int | None = None,
        response: object | None = None,
        destination: Path | None = None,
        cause: Exception | None = None,
        credentials: Mapping[str, str] | None = None,
    ) -> None:
        safe_message = _sanitize_api_diagnostic(message, dict(credentials or {}))
        diagnostic: dict[str, Any] = {
            "decision": "SETTRADE_ACQUISITION_FAILED",
            "acquisition_stage": stage,
            "exception_class": type(cause).__name__ if cause is not None else type(self).__name__,
            "exception_category": category,
            "message": safe_message,
        }
        if window is not None:
            diagnostic.update(
                {
                    "session_date": window.trading_date.isoformat(),
                    "session": window.session,
                    "requested_start": window.start.strftime(SETTRADE_DATETIME_FORMAT),
                    "requested_end": window.end.strftime(SETTRADE_DATETIME_FORMAT),
                    "requested_limit": requested_limit,
                    "expected_half_open_slots": window.expected_bar_slots,
                }
            )
        if response is not None:
            diagnostic["response_schema"] = _response_schema_summary(response)
        if destination is not None:
            diagnostic["destination"] = str(destination)
        if cause is not None and hasattr(cause, "status_code"):
            diagnostic["api_status_code"] = getattr(cause, "status_code", None)
            diagnostic["api_error_code"] = _sanitize_api_diagnostic(
                getattr(cause, "code", None), dict(credentials or {})
            )
            diagnostic["api_error_message"] = _sanitize_api_diagnostic(
                str(cause), dict(credentials or {})
            )
        self.diagnostic = diagnostic
        super().__init__(safe_message)


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


def _load_sdk(environment: str) -> SdkBindings:
    """Load and validate the exact read-only SDK surface before using credentials.

    settrade-v2 2.2.1 does not accept ``environment`` in ``Investor``. Its ``Context`` and
    ``MarketData`` classes read the process-global mapping in ``settrade_v2.config`` instead,
    so the CLI's explicit environment choice is applied there before construction.
    """
    if environment not in {"prod", "uat"}:
        raise SdkCompatibilityError(f"unsupported SDK environment {environment!r}")

    try:
        package = import_module("settrade_v2")
        config_module = import_module("settrade_v2.config")
    except ImportError as exc:  # pragma: no cover - depends on the operator's environment
        raise SdkMissing(
            "the settrade-v2 SDK is not installed. Install it with `uv add --dev settrade-v2`. "
            "It is optional on purpose: this repository must build and test without broker "
            "credentials."
        ) from exc

    investor_class = getattr(package, "Investor", None)
    if not callable(investor_class):
        raise SdkCompatibilityError("settrade_v2 does not export a callable Investor")

    try:
        investor_signature = signature(investor_class)
        investor_signature.bind(
            app_id="<app-id>",
            app_secret="<app-secret>",
            app_code="<app-code>",
            broker_id="<broker-id>",
            is_auto_queue=False,
        )
    except (TypeError, ValueError) as exc:
        raise SdkCompatibilityError(
            "Investor does not support the verified settrade-v2 keyword initialization pattern"
        ) from exc

    sdk_config = getattr(config_module, "config", None)
    if not isinstance(sdk_config, MutableMapping):
        raise SdkCompatibilityError(
            "settrade_v2.config.config is not a mutable environment mapping"
        )
    sdk_config["environment"] = environment

    return SdkBindings(
        investor_class=investor_class,
        version=str(getattr(package, "__version__", "UNKNOWN")),
        investor_signature=str(investor_signature),
    )


def _construct_investor(
    bindings: SdkBindings,
    credentials: dict[str, str],
    *,
    is_auto_queue: bool = False,
) -> Any:
    """Authenticate using the constructor supported by settrade-v2 2.2.1."""
    try:
        return bindings.investor_class(
            app_id=credentials["SETTRADE_APP_ID"],
            app_secret=credentials["SETTRADE_APP_SECRET"],
            app_code=credentials["SETTRADE_APP_CODE"],
            broker_id=credentials["SETTRADE_BROKER_ID"],
            is_auto_queue=is_auto_queue,
        )
    except TypeError as exc:
        # A locally rejected call shape is not evidence about a symbol or entitlement.
        raise SdkCompatibilityError(
            "Investor rejected the verified settrade-v2 keyword initialization pattern"
        ) from exc


def _investor(environment: str) -> Any:
    """Build an authenticated SDK client without touching an order/account surface."""
    bindings = _load_sdk(environment)
    return _construct_investor(bindings, _credentials())


def _candlestick_method(investor: Any) -> Any:
    """Return the generic read-only historical candlestick method, or fail compatibly."""
    market_data_factory = getattr(investor, "MarketData", None)
    if not callable(market_data_factory):
        raise SdkCompatibilityError("Investor does not expose callable MarketData")

    try:
        market_data = market_data_factory()
    except (AttributeError, TypeError) as exc:
        raise SdkCompatibilityError("Investor.MarketData() is incompatible") from exc

    get_candlestick = getattr(market_data, "get_candlestick", None)
    if not callable(get_candlestick):
        raise SdkCompatibilityError("MarketData does not expose callable get_candlestick")

    try:
        signature(get_candlestick).bind(
            symbol="S50Z26",
            interval="1m",
            limit=5,
            start="2026-01-02T09:45",
            end="2026-01-02T09:50",
            normalized=False,
        )
    except (TypeError, ValueError) as exc:
        raise SdkCompatibilityError(
            "MarketData.get_candlestick does not accept the verified SDK v2 parameters"
        ) from exc
    return get_candlestick


def _quote_method(investor: Any) -> Any:
    """Return the generic read-only symbol quote method, or fail compatibly."""
    market_data_factory = getattr(investor, "MarketData", None)
    if not callable(market_data_factory):
        raise SdkCompatibilityError("Investor does not expose callable MarketData")

    try:
        market_data = market_data_factory()
    except (AttributeError, TypeError) as exc:
        raise SdkCompatibilityError("Investor.MarketData() is incompatible") from exc

    get_quote_symbol = getattr(market_data, "get_quote_symbol", None)
    if not callable(get_quote_symbol):
        raise SdkCompatibilityError("MarketData does not expose callable get_quote_symbol")
    try:
        signature(get_quote_symbol).bind(symbol="S50Z26")
    except (TypeError, ValueError) as exc:
        raise SdkCompatibilityError("MarketData.get_quote_symbol does not accept symbol") from exc
    return get_quote_symbol


def _serialize_probe_datetime(value: str) -> str:
    """Validate and canonicalize Settrade's documented ``YYYY-MM-DDTHH:MM`` form."""
    try:
        parsed = datetime.strptime(value, SETTRADE_DATETIME_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"Settrade candlestick datetime must use {SETTRADE_DATETIME_PATTERN}"
        ) from exc
    serialized = parsed.strftime(SETTRADE_DATETIME_FORMAT)
    if serialized != value:
        raise ValueError(f"Settrade candlestick datetime must use {SETTRADE_DATETIME_PATTERN}")
    return serialized


def _candlestick_parameters(
    symbol: str,
    interval: str,
    *,
    start: str,
    end: str,
    limit: int | None,
) -> dict[str, str | int]:
    """Build only the query values documented and forwarded by settrade-v2 2.2.1."""
    serialized_start = _serialize_probe_datetime(start)
    serialized_end = _serialize_probe_datetime(end)
    if datetime.strptime(serialized_end, SETTRADE_DATETIME_FORMAT) <= datetime.strptime(
        serialized_start, SETTRADE_DATETIME_FORMAT
    ):
        raise ValueError("Settrade candlestick end must be later than start")
    if limit is not None and limit <= 0:
        raise ValueError("Settrade candlestick limit must be greater than zero")

    params: dict[str, str | int] = {
        "symbol": symbol,
        "interval": interval,
        "start": serialized_start,
        "end": serialized_end,
    }
    if limit is not None:
        params["limit"] = limit
    return params


def _default_probe_window() -> tuple[str, str]:
    """Return a tiny, correctly formatted window; operators can override it explicitly."""
    end = datetime.now().replace(second=0, microsecond=0)
    start = end - timedelta(minutes=5)
    return start.strftime(SETTRADE_DATETIME_FORMAT), end.strftime(SETTRADE_DATETIME_FORMAT)


def _sanitize_api_diagnostic(value: object, credentials: dict[str, str]) -> str:
    """Return bounded API text with credential, token, and account material removed."""
    text = " ".join(str(value).split())
    for secret in sorted(
        (secret for secret in credentials.values() if secret), key=len, reverse=True
    ):
        text = text.replace(secret, "[REDACTED]")
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    text = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)
    text = _JWT_TOKEN.sub("[REDACTED_JWT]", text)
    return text[:500]


def _safe_response_field_name(value: object) -> str:
    name = str(value)
    if _SENSITIVE_FIELD_NAME.search(name):
        return "[REDACTED_SENSITIVE_FIELD]"
    return name[:100]


def _response_schema_summary(response: object) -> dict[str, Any]:
    """Describe only response shape, never values, headers, or request state."""
    summary: dict[str, Any] = {"response_type": type(response).__name__}
    if isinstance(response, Mapping):
        safe_items = [(_safe_response_field_name(key), value) for key, value in response.items()]
        safe_items.sort(key=lambda item: item[0])
        summary["field_names"] = [name for name, _ in safe_items]
        summary["field_types"] = {name: type(value).__name__ for name, value in safe_items}
        summary["field_lengths"] = {
            name: len(value) for name, value in safe_items if isinstance(value, (list, tuple))
        }
        raw_time = response.get("time")
        summary["returned_bars"] = len(raw_time) if isinstance(raw_time, (list, tuple)) else None
    elif isinstance(response, (list, tuple)):
        summary["item_count"] = len(response)
        if response and isinstance(response[0], Mapping):
            summary["first_item_field_names"] = sorted(
                _safe_response_field_name(key) for key in response[0]
            )
    return summary


def _record_market_request(
    evidence: dict[str, Any], *, endpoint: str, parameters: Mapping[str, object]
) -> None:
    """Persist an allowlisted request description, never a URL, headers, or request object."""
    evidence["api_endpoint"] = endpoint
    evidence["request_parameter_names"] = sorted(parameters)
    evidence["request_parameter_types"] = {
        name: type(value).__name__ for name, value in sorted(parameters.items())
    }
    evidence["requested_start"] = parameters.get("start")
    evidence["requested_end"] = parameters.get("end")
    evidence["requested_limit"] = parameters.get("limit")


def _new_evidence(
    symbol: str, environment: str, interval: str, *, probe_mode: str
) -> dict[str, Any]:
    """Create the non-secret evidence envelope."""
    return {
        "probed_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "symbol": symbol,
        "interval": interval,
        "probe_mode": probe_mode,
        "decision": SETTRADE_PROBE_FAILED,
        "documented_intervals": list(DOCUMENTED_INTERVALS),
        "sdk_import": "settrade_v2",
        "sdk_version": None,
        "sdk_available": False,
        "sdk_compatible": None,
        "sdk_investor_signature": None,
        "sdk_candlestick_signature": None,
        "sdk_environment_source": "settrade_v2.config.config",
        "api_surface": {
            "authentication": "Investor(...) SDK login",
            "quote": "Investor.MarketData().get_quote_symbol",
            "candlestick": "Investor.MarketData().get_candlestick",
        }[probe_mode],
        "credentials_present": all(os.environ.get(name) for name in REQUIRED_ENV),
        "authentication": "NOT_ATTEMPTED",
        "api_request_attempted": False,
        "derivatives_market_data_entitlement": "UNKNOWN",
        "historical_derivatives_candlestick": "UNKNOWN",
        "raw_contract_symbol_supported": "UNKNOWN",
        "one_minute_interval_supported": "UNKNOWN",
        "bars_returned": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "max_bars_per_request": "UNKNOWN_SERVER_LIMIT",
        "pagination": "NO_TOKEN_IN_SDK; WINDOW_WITH_START_END",
        "rate_limits": "SDK_DEFAULT_5_PER_SECOND_60_PER_MINUTE; SERVER_HEADERS_OVERRIDE",
        "api_status_code": None,
        "api_error_code": None,
        "api_error_message": None,
        "api_endpoint": None,
        "request_parameter_names": [],
        "request_parameter_types": {},
        "requested_start": None,
        "requested_end": None,
        "requested_limit": None,
        "error_category": None,
        "error": None,
    }


def _set_sdk_failure(evidence: dict[str, Any], exc: Exception) -> None:
    evidence["decision"] = SETTRADE_SDK_API_INCOMPATIBLE
    evidence["sdk_compatible"] = False
    evidence["error_category"] = "SDK_API_COMPATIBILITY"
    # Never persist arbitrary third-party exception text; it may echo request material.
    evidence["error"] = f"{type(exc).__name__}: installed SDK API is incompatible with probe"


def _api_status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def _api_failure_decision(exc: Exception, *, phase: str) -> str:
    """Use HTTP 400 for request validity, and message text only for narrower causes."""
    status = _api_status_code(exc)
    code = str(getattr(exc, "code", ""))
    diagnostic = f"{code} {exc}".casefold()

    if phase == "authentication" and status in {400, 401, 403}:
        return SETTRADE_AUTH_REQUIRED
    if status == 401:
        return SETTRADE_AUTH_REQUIRED
    if status == 403:
        return SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING
    if status == 400:
        invalid_markers = (
            "invalid",
            "malformed",
            "missing",
            "required",
            "unsupported",
            "not supported",
            "not found",
            "unknown",
            "format",
            "range",
        )
        is_validation_error = any(marker in diagnostic for marker in invalid_markers)
        if is_validation_error and re.search(
            r"\b(start|end|date|datetime|time|range)\b", diagnostic
        ):
            return SETTRADE_DATE_RANGE_INVALID
        if is_validation_error and "symbol" in diagnostic:
            return SETTRADE_SYMBOL_INVALID
        if is_validation_error and "interval" in diagnostic:
            return SETTRADE_INTERVAL_INVALID
        return SETTRADE_REQUEST_INVALID
    return SETTRADE_PROBE_FAILED


def _set_api_failure(
    evidence: dict[str, Any],
    exc: Exception,
    *,
    phase: str,
    credentials: dict[str, str],
) -> None:
    decision = _api_failure_decision(exc, phase=phase)
    evidence["decision"] = decision
    evidence["api_status_code"] = _api_status_code(exc)
    evidence["api_error_code"] = _sanitize_api_diagnostic(
        getattr(exc, "code", "UNKNOWN"), credentials
    )
    evidence["api_error_message"] = _sanitize_api_diagnostic(exc, credentials)
    evidence["error_category"] = decision.removeprefix("SETTRADE_")
    evidence["error"] = f"{type(exc).__name__} during {phase}; sanitized API fields recorded"

    if decision == SETTRADE_AUTH_REQUIRED:
        evidence["authentication"] = "REJECTED"
    elif decision == SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING:
        evidence["derivatives_market_data_entitlement"] = "DENIED"
    elif decision == SETTRADE_INTERVAL_INVALID:
        evidence["one_minute_interval_supported"] = "REJECTED_BY_API"
    elif decision == SETTRADE_SYMBOL_INVALID:
        evidence["raw_contract_symbol_supported"] = "REJECTED_BY_API"


def probe(
    symbol: str,
    *,
    environment: str,
    interval: str = "1m",
    probe_mode: str = "candlestick",
    start: str | None = None,
    end: str | None = None,
    limit: int | None = 5,
) -> dict[str, Any]:
    """Run one focused read-only stage and return secret-sanitized evidence."""
    if probe_mode not in PROBE_MODES:
        raise ValueError(f"unsupported probe mode {probe_mode!r}")
    evidence = _new_evidence(symbol, environment, interval, probe_mode=probe_mode)

    try:
        bindings = _load_sdk(environment)
        evidence["sdk_available"] = True
        evidence["sdk_compatible"] = True
        evidence["sdk_version"] = bindings.version
        evidence["sdk_investor_signature"] = bindings.investor_signature
    except SdkMissing as exc:
        evidence["decision"] = SETTRADE_SDK_API_INCOMPATIBLE
        evidence["sdk_compatible"] = False
        evidence["error_category"] = "SDK_MISSING"
        evidence["error"] = f"{type(exc).__name__}: settrade-v2 is not importable"
        return evidence
    except SdkCompatibilityError as exc:
        evidence["sdk_available"] = True
        _set_sdk_failure(evidence, exc)
        return evidence

    try:
        credentials = _credentials()
    except CredentialsMissing as exc:
        evidence["decision"] = SETTRADE_AUTH_REQUIRED
        evidence["error_category"] = "AUTH_REQUIRED"
        evidence["error"] = str(exc)
        return evidence

    try:
        investor = _construct_investor(bindings, credentials)
    except SdkCompatibilityError as exc:
        _set_sdk_failure(evidence, exc)
        return evidence
    except Exception as exc:  # an SDK login request may fail for several API reasons
        evidence["api_endpoint"] = "authentication"
        _set_api_failure(evidence, exc, phase="authentication", credentials=credentials)
        return evidence

    evidence["authentication"] = "CONFIRMED"

    if probe_mode == "authentication":
        evidence["decision"] = SETTRADE_AUTHENTICATION_CONFIRMED
        return evidence

    if probe_mode == "quote":
        try:
            get_quote_symbol = _quote_method(investor)
        except SdkCompatibilityError as exc:
            _set_sdk_failure(evidence, exc)
            return evidence

        quote_parameters = {"symbol": symbol}
        _record_market_request(
            evidence, endpoint="marketdata.quote_symbol", parameters=quote_parameters
        )
        evidence["api_request_attempted"] = True
        try:
            get_quote_symbol(**quote_parameters)
        except Exception as exc:
            _set_api_failure(evidence, exc, phase="quote request", credentials=credentials)
            return evidence

        evidence["decision"] = SETTRADE_SYMBOL_RECOGNIZED
        evidence["derivatives_market_data_entitlement"] = "CONFIRMED_FOR_QUOTE"
        evidence["raw_contract_symbol_supported"] = "CONFIRMED_FOR_QUOTE"
        return evidence

    try:
        get_candlestick = _candlestick_method(investor)
    except SdkCompatibilityError as exc:
        _set_sdk_failure(evidence, exc)
        return evidence

    evidence["sdk_candlestick_signature"] = str(signature(get_candlestick))
    if start is None and end is None:
        start, end = _default_probe_window()
    elif start is None or end is None:
        evidence["decision"] = SETTRADE_DATE_RANGE_INVALID
        evidence["error_category"] = "DATE_RANGE_INVALID"
        evidence["error"] = "both --start and --end are required when either is supplied"
        return evidence

    try:
        parameters = _candlestick_parameters(
            symbol,
            interval,
            start=start,
            end=end,
            limit=limit,
        )
    except ValueError as exc:
        evidence["decision"] = SETTRADE_DATE_RANGE_INVALID
        evidence["error_category"] = "DATE_RANGE_INVALID"
        evidence["error"] = str(exc)
        return evidence

    _record_market_request(evidence, endpoint="techchart.candlesticks", parameters=parameters)
    evidence["api_request_attempted"] = True
    try:
        response = get_candlestick(**parameters)
    except Exception as exc:
        _set_api_failure(evidence, exc, phase="candlestick request", credentials=credentials)
        return evidence

    if not isinstance(response, dict):
        _set_sdk_failure(evidence, SdkCompatibilityError("non-dictionary response"))
        return evidence
    raw_times = response.get("time")
    if not isinstance(raw_times, list):
        _set_sdk_failure(evidence, SdkCompatibilityError("response has no time array"))
        return evidence

    times: list[Any] = raw_times
    count = len(times)
    evidence["bars_returned"] = count
    evidence["derivatives_market_data_entitlement"] = "CONFIRMED"
    if count:
        evidence["decision"] = SETTRADE_REAL_DATA_READY
        evidence["historical_derivatives_candlestick"] = "CONFIRMED"
        evidence["raw_contract_symbol_supported"] = "CONFIRMED"
        evidence["one_minute_interval_supported"] = "CONFIRMED" if interval == "1m" else "UNKNOWN"
        evidence["first_timestamp"] = str(times[0])
        evidence["last_timestamp"] = str(times[-1])
    else:
        evidence["historical_derivatives_candlestick"] = "NO_DATA_RETURNED"
        evidence["one_minute_interval_supported"] = "ACCEPTED_NO_DATA"
    return evidence


def _rows_from_response(
    response: Mapping[str, Any],
    *,
    window: DownloadWindow | None = None,
    requested_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Transpose the API's column-oriented payload into rows.

    The techchart service returns parallel arrays (``time``, ``open``, ``high``, ``low``,
    ``close``, ``volume``). Anything else is left alone and reported rather than guessed at.
    """
    required = ("time", "open", "high", "low", "close", "volume")
    missing = [key for key in required if key not in response]
    if missing:
        raise AcquisitionFailure(
            stage="response_validation",
            category="RESPONSE_SCHEMA_INVALID",
            message=f"candlestick payload is missing required fields: {', '.join(missing)}",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    columns = {key: response[key] for key in required}
    if not all(isinstance(column, list) for column in columns.values()):
        raise AcquisitionFailure(
            stage="response_validation",
            category="RESPONSE_SCHEMA_INVALID",
            message="candlestick required fields are not arrays",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    lengths = {len(column) for column in columns.values()}
    if len(lengths) != 1:
        raise AcquisitionFailure(
            stage="response_validation",
            category="RESPONSE_FIELD_LENGTH_MISMATCH",
            message="candlestick required arrays have unequal lengths",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    count = lengths.pop()

    # Preserve every additional source array aligned to the bars. Scalar response metadata
    # remains intact in the immutable raw JSON capture rather than being repeated per row.
    for key, value in response.items():
        if key not in columns and isinstance(value, list) and len(value) == count:
            columns[key] = value

    return [{key: column[index] for key, column in columns.items()} for index in range(count)]


def _source_timestamp_to_utc(
    value: object,
    *,
    window: DownloadWindow | None = None,
    requested_limit: int | None = None,
    response: Mapping[str, Any] | None = None,
) -> datetime:
    """Convert Settrade's documented epoch-second candle timestamp without guessing units."""
    if isinstance(value, bool):
        raise AcquisitionFailure(
            stage="normalization",
            category="TIMESTAMP_INVALID",
            message="Settrade source timestamp is not an integer Unix-seconds value",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    try:
        numeric = Decimal(str(value))
    except InvalidOperation as exc:
        raise AcquisitionFailure(
            stage="normalization",
            category="TIMESTAMP_INVALID",
            message="Settrade source timestamp is not numeric",
            window=window,
            requested_limit=requested_limit,
            response=response,
            cause=exc,
        ) from exc
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        raise AcquisitionFailure(
            stage="normalization",
            category="TIMESTAMP_INVALID",
            message="Settrade source timestamp is not an integer Unix-seconds value",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    seconds = int(numeric)
    if not 1_000_000_000 <= seconds <= 4_102_444_800:
        raise AcquisitionFailure(
            stage="normalization",
            category="TIMESTAMP_INVALID",
            message="Settrade source timestamp is outside the supported Unix-seconds range",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    return datetime.fromtimestamp(seconds, UTC)


def _download_windows(
    symbol: str,
    *,
    start: date,
    end: date,
    request_limit: int,
    enforce_initial_range: bool = True,
) -> tuple[DownloadWindow, ...]:
    """Build one request per continuous session from verified calendar/session metadata."""
    if end < start:
        raise ValueError("download end date precedes start date")
    if request_limit <= 0:
        raise ValueError("download request limit must be greater than zero")

    config = load_config()
    calendar = TradingCalendar(config, HolidayStore())
    calendar.preflight(start, end)
    parsed = ContractResolver(config, calendar).parse(symbol, reference_date=start)
    expiry = calendar.contract_expiry(parsed.contract_year, parsed.contract_month)
    if end >= expiry.last_trading_date:
        raise ValueError(
            f"initial acquisition must end before {symbol} LTD "
            f"{expiry.last_trading_date.isoformat()}"
        )

    trading_days = calendar.session_dates_in_range(start, end)
    if enforce_initial_range and not (
        DOWNLOAD_MIN_TRADING_DAYS <= len(trading_days) <= DOWNLOAD_MAX_TRADING_DAYS
    ):
        raise ValueError(
            "initial acquisition requires 5-10 complete TFEX trading days; "
            f"the selected range contains {len(trading_days)}"
        )

    engine = SessionEngine(config, calendar)
    windows: list[DownloadWindow] = []
    for trading_day in trading_days:
        plan = engine.plan_for(trading_day, expiry=expiry)
        boundaries = (
            ("morning", plan.morning_open_at, plan.morning_close_at),
            ("afternoon", plan.afternoon_open_at, plan.afternoon_close_at),
        )
        for session, open_at, close_at in boundaries:
            if open_at is None or close_at is None:
                raise AcquisitionFailure(
                    stage="window_planning",
                    category="INTERNAL_SESSION_INVARIANT",
                    message=f"verified calendar has no {session} boundaries for {trading_day}",
                )
            expected = int((close_at - open_at).total_seconds() // 60)
            if request_limit < expected:
                raise ValueError(
                    f"request limit {request_limit} is smaller than the {expected} possible "
                    f"1-minute bars in the {session} session"
                )
            windows.append(
                DownloadWindow(
                    trading_date=trading_day,
                    session=session,
                    start=open_at,
                    end=close_at,
                    expected_bar_slots=expected,
                )
            )
    return tuple(windows)


def _normalized_rows(
    symbol: str,
    captures: list[tuple[DownloadWindow, Mapping[str, Any], int]],
) -> list[dict[str, Any]]:
    """Transpose SDK payloads while retaining source timestamps and aligned extra fields."""
    normalized: list[dict[str, Any]] = []
    for window, response, requested_limit in captures:
        source_rows = _rows_from_response(
            response,
            window=window,
            requested_limit=requested_limit,
        )
        if not source_rows:
            raise AcquisitionFailure(
                stage="normalization",
                category="SESSION_EMPTY",
                message="Settrade returned no bars for the requested continuous session",
                window=window,
                requested_limit=requested_limit,
                response=response,
            )
        if len(source_rows) > window.expected_bar_slots:
            raise AcquisitionFailure(
                stage="normalization",
                category="SESSION_SLOT_OVERFLOW",
                message="response contains more bars than the half-open session grid",
                window=window,
                requested_limit=requested_limit,
                response=response,
            )

        market_timestamps: list[datetime] = []
        for source_row in source_rows:
            source_timestamp = source_row["time"]
            timestamp = _source_timestamp_to_utc(
                source_timestamp,
                window=window,
                requested_limit=requested_limit,
                response=response,
            )
            market_timestamp = timestamp.astimezone(MARKET_TIMEZONE)
            if not window.start <= market_timestamp < window.end:
                raise AcquisitionFailure(
                    stage="normalization",
                    category="TIMESTAMP_OUTSIDE_SESSION",
                    message="response contains a bar outside the requested half-open session",
                    window=window,
                    requested_limit=requested_limit,
                    response=response,
                )
            market_timestamps.append(market_timestamp)
            row: dict[str, Any] = {
                "symbol": symbol,
                "timestamp": timestamp.isoformat(),
                "source_timestamp": source_timestamp,
                "open": source_row["open"],
                "high": source_row["high"],
                "low": source_row["low"],
                "close": source_row["close"],
                "volume": source_row["volume"],
                "source_session": window.session,
            }
            for key, value in source_row.items():
                if key not in {*row, "time"}:
                    row[key] = value
            normalized.append(row)

        expected_last = window.end - timedelta(minutes=1)
        if len(source_rows) == requested_limit and (
            market_timestamps[0] != window.start or market_timestamps[-1] != expected_last
        ):
            raise AcquisitionFailure(
                stage="normalization",
                category="SESSION_TRUNCATED",
                message="response reached its limit without covering both session boundaries",
                window=window,
                requested_limit=requested_limit,
                response=response,
            )
        if len(source_rows) != window.expected_bar_slots:
            raise AcquisitionFailure(
                stage="normalization",
                category="SESSION_INCOMPLETE",
                message=(
                    "response does not contain every expected one-minute slot for the "
                    "requested continuous session"
                ),
                window=window,
                requested_limit=requested_limit,
                response=response,
            )
        expected_timestamps = [
            window.start + timedelta(minutes=index) for index in range(window.expected_bar_slots)
        ]
        if market_timestamps != expected_timestamps:
            raise AcquisitionFailure(
                stage="normalization",
                category="SESSION_GRID_MISMATCH",
                message="response timestamps do not exactly match the one-minute session grid",
                window=window,
                requested_limit=requested_limit,
                response=response,
            )
    return normalized


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _write_normalized_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    required = [
        "symbol",
        "timestamp",
        "source_timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source_session",
    ]
    extras = sorted({key for row in rows for key in row if key not in required})
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*required, *extras])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


def _manifest_file_reference(path: Path) -> str:
    try:
        return path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _require_acquisition_capability(
    symbol: str,
    *,
    interval: str,
    environment: str,
) -> Mapping[str, Any]:
    """Fail closed unless sanitized probe evidence authorizes this exact acquisition."""
    try:
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "SETTRADE_REAL_DATA_READY evidence is missing or invalid; run the read-only "
            "capability probe first"
        ) from exc
    if not isinstance(evidence, dict):
        raise ValueError("Settrade capability evidence must be a JSON object")

    confirmed_fields = (
        "authentication",
        "derivatives_market_data_entitlement",
        "historical_derivatives_candlestick",
        "raw_contract_symbol_supported",
        "one_minute_interval_supported",
    )
    evidence_matches = (
        evidence.get("decision") == SETTRADE_REAL_DATA_READY
        and evidence.get("symbol") == symbol
        and evidence.get("interval") == interval
        and evidence.get("environment") == environment
        and all(evidence.get(field) == "CONFIRMED" for field in confirmed_fields)
    )
    if not evidence_matches:
        raise ValueError(
            "persisted capability evidence does not confirm this exact symbol, interval, "
            "and environment"
        )
    return evidence


def _acquisition_client(
    symbol: str,
    *,
    interval: str,
    environment: str,
) -> tuple[SdkBindings, Any, dict[str, str]]:
    capability = _require_acquisition_capability(
        symbol,
        interval=interval,
        environment=environment,
    )
    bindings = _load_sdk(environment)
    if capability.get("sdk_version") != bindings.version:
        raise SdkCompatibilityError(
            "installed settrade-v2 version differs from the successfully probed version"
        )
    credentials = _credentials()
    try:
        investor = _construct_investor(bindings, credentials, is_auto_queue=True)
        get_candlestick = _candlestick_method(investor)
    except SdkCompatibilityError:
        raise
    except Exception as exc:
        raise AcquisitionFailure(
            stage="authentication",
            category="SETTRADE_API_ERROR" if hasattr(exc, "status_code") else "SDK_RUNTIME_ERROR",
            message=str(exc),
            cause=exc,
            credentials=credentials,
        ) from exc
    return bindings, get_candlestick, credentials


def _request_window(
    get_candlestick: Any,
    *,
    symbol: str,
    interval: str,
    window: DownloadWindow,
    requested_limit: int,
    credentials: Mapping[str, str],
) -> Mapping[str, Any]:
    try:
        response = get_candlestick(
            symbol=symbol,
            interval=interval,
            limit=requested_limit,
            start=window.start.strftime(SETTRADE_DATETIME_FORMAT),
            end=window.end.strftime(SETTRADE_DATETIME_FORMAT),
            normalized=False,
        )
    except Exception as exc:
        raise AcquisitionFailure(
            stage="api_request",
            category="SETTRADE_API_ERROR" if hasattr(exc, "status_code") else "SDK_RUNTIME_ERROR",
            message=str(exc),
            window=window,
            requested_limit=requested_limit,
            cause=exc,
            credentials=credentials,
        ) from exc
    if not isinstance(response, Mapping):
        raise AcquisitionFailure(
            stage="response_validation",
            category="RESPONSE_SCHEMA_INVALID",
            message="get_candlestick returned a non-dictionary response",
            window=window,
            requested_limit=requested_limit,
            response=response,
        )
    return response


def diagnose_session(
    symbol: str,
    *,
    interval: str,
    trading_date: date,
    session: str,
    environment: str,
    request_limit: int = DOWNLOAD_REQUEST_LIMIT,
) -> dict[str, Any]:
    """Make one read-only request and report schema/boundaries without writing bar data."""
    symbol = symbol.strip().upper()
    if interval != BarInterval.ONE_MINUTE.value:
        raise ValueError("session diagnosis supports only the verified 1m interval")
    windows = _download_windows(
        symbol,
        start=trading_date,
        end=trading_date,
        request_limit=request_limit,
        enforce_initial_range=False,
    )
    try:
        window = next(item for item in windows if item.session == session)
    except StopIteration as exc:
        raise ValueError(f"no {session} session exists on {trading_date.isoformat()}") from exc

    bindings, get_candlestick, credentials = _acquisition_client(
        symbol,
        interval=interval,
        environment=environment,
    )
    response = _request_window(
        get_candlestick,
        symbol=symbol,
        interval=interval,
        window=window,
        requested_limit=request_limit,
        credentials=credentials,
    )
    rows = _rows_from_response(
        response,
        window=window,
        requested_limit=request_limit,
    )
    market_timestamps = [
        _source_timestamp_to_utc(
            row["time"],
            window=window,
            requested_limit=request_limit,
            response=response,
        ).astimezone(MARKET_TIMEZONE)
        for row in rows
    ]
    requested_end_present = window.end in market_timestamps
    expected_last = window.end - timedelta(minutes=1)
    if requested_end_present:
        end_semantics = "RESPONSE_INCLUDES_REQUESTED_END"
    elif market_timestamps and market_timestamps[-1] == expected_last:
        end_semantics = "RESPONSE_EXCLUDES_REQUESTED_END_OR_LIMIT_REMOVED_IT"
    else:
        end_semantics = "INCONCLUSIVE"

    return {
        "decision": "SETTRADE_SESSION_DIAGNOSTIC_OK",
        "sdk_version": bindings.version,
        "symbol": symbol,
        "interval": interval,
        "environment": environment,
        "session_date": trading_date.isoformat(),
        "session": session,
        "requested_start": window.start.strftime(SETTRADE_DATETIME_FORMAT),
        "requested_end": window.end.strftime(SETTRADE_DATETIME_FORMAT),
        "requested_limit": request_limit,
        "expected_half_open_slots": window.expected_bar_slots,
        "response_schema": _response_schema_summary(response),
        "returned_bars": len(rows),
        "first_source_timestamp": str(rows[0]["time"]) if rows else None,
        "last_source_timestamp": str(rows[-1]["time"]) if rows else None,
        "first_market_timestamp": market_timestamps[0].isoformat() if market_timestamps else None,
        "last_market_timestamp": market_timestamps[-1].isoformat() if market_timestamps else None,
        "limit_reached": len(rows) >= request_limit,
        "requested_end_present": requested_end_present,
        "end_semantics_evidence": end_semantics,
        "complete_half_open_boundaries": bool(
            len(rows) == window.expected_bar_slots
            and market_timestamps
            and market_timestamps[0] == window.start
            and market_timestamps[-1] == expected_last
        ),
        "files_written": False,
    }


def _validate_normalized_dataset(
    path: Path,
    manifest: DatasetManifest,
) -> tuple[LoadResult, ValidationReport]:
    """Run the repository validator without changing the dataset or its manifest."""
    loaded = load_bars(
        path,
        source_timezone=manifest.source_timezone,
        symbol=manifest.symbol,
    )
    config = load_config()
    validator = MarketDataValidator(config, TradingCalendar(config, HolidayStore()))
    report = validator.validate(
        loaded.bars,
        symbol=manifest.symbol,
        interval=manifest.interval,
        file_path=str(path),
        sha256=file_sha256(path),
        manifest=manifest,
        load_findings=tuple(loaded.findings),
        row_count=loaded.row_count,
    )
    return loaded, report


def _require_exact_validation_pass(report: ValidationReport, *, label: str) -> None:
    required = {
        "provenance",
        "row_parsing",
        "contract_identity",
        "timestamps",
        "duplicates",
        "ohlc",
        "tick_size",
        "volume",
        "session_boundaries",
        "missing_bars",
        "expiry",
    }
    statuses = {check.name: check.status for check in report.checks}
    not_passed = sorted(name for name in required if statuses.get(name) is not CheckStatus.PASS)
    if report.outcome is not ValidationOutcome.PASS or not_passed:
        raise ValueError(
            f"{label} must have an exact validator PASS; non-PASS checks: {not_passed}"
        )


def _read_normalized_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("normalized parent CSV has no header")
            rows = [dict(row) for row in reader]
    except OSError as exc:
        raise ValueError(f"cannot read normalized parent dataset: {exc}") from exc
    return rows


def _strict_row_timestamps(rows: list[dict[str, Any]], *, label: str) -> tuple[datetime, ...]:
    timestamps: list[datetime] = []
    for index, row in enumerate(rows, start=2):
        raw = row.get("timestamp")
        try:
            timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} row {index} has an invalid timestamp") from exc
        if timestamp.tzinfo is None:
            raise ValueError(f"{label} row {index} timestamp is not timezone-aware")
        timestamps.append(timestamp)
    if any(current <= previous for previous, current in pairwise(timestamps)):
        raise ValueError(f"{label} timestamps are not strictly increasing and unique")
    return tuple(timestamps)


def _capture_file_path(capture: SourceCapture) -> Path:
    path = Path(capture.file)
    candidate = path if path.is_absolute() else BACKEND_ROOT / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(HISTORICAL_RAW_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"source capture is missing or outside the immutable raw-data root: {capture.file}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"source capture is not a file: {capture.file}")
    return resolved


def _verify_raw_capture_checksums(captures: tuple[SourceCapture, ...]) -> tuple[str, ...]:
    hashes: list[str] = []
    for capture in captures:
        actual = file_sha256(_capture_file_path(capture))
        if actual != capture.sha256:
            raise ValueError(
                f"immutable source capture checksum mismatch for {capture.file}; "
                "the dataset lineage is void"
            )
        hashes.append(actual)
    if len(hashes) != len(set(hashes)):
        raise ValueError("source-capture lineage contains duplicate raw payload checksums")
    return tuple(hashes)


def _require_capture_schedule(
    captures: tuple[SourceCapture, ...],
    windows: tuple[DownloadWindow, ...],
    *,
    label: str,
) -> None:
    if len(captures) != len(windows):
        raise ValueError(
            f"{label} has {len(captures)} raw captures for {len(windows)} session windows"
        )
    for capture, window in zip(captures, windows, strict=True):
        expected_start = window.start.strftime(SETTRADE_DATETIME_FORMAT)
        expected_end = window.end.strftime(SETTRADE_DATETIME_FORMAT)
        if (
            capture.endpoint != "techchart.candlesticks"
            or capture.requested_start != expected_start
            or capture.requested_end != expected_end
            or capture.requested_limit != window.expected_bar_slots
            or capture.record_count != window.expected_bar_slots
            or capture.normalized
        ):
            raise ValueError(
                f"{label} raw-capture provenance does not exactly cover "
                f"{window.trading_date.isoformat()} {window.session}"
            )


def _verified_parent_dataset(
    parent_file: Path,
    *,
    expected_sha256: str,
    symbol: str,
    interval: str,
) -> tuple[DatasetManifest, LoadResult, list[dict[str, Any]], tuple[date, ...]]:
    expected_sha256 = expected_sha256.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("parent normalized SHA-256 must be 64 lowercase hexadecimal characters")
    try:
        parent_file.resolve(strict=True).relative_to(
            HISTORICAL_NORMALIZED_ROOT.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise ValueError("parent must be inside the normalized historical-data root") from exc
    manifest = load_manifest(parent_file)
    if manifest.sha256 != expected_sha256 or file_sha256(parent_file) != expected_sha256:
        raise ValueError("parent normalized dataset does not match the required SHA-256")
    if manifest.symbol != symbol or manifest.interval.value != interval:
        raise ValueError("parent symbol and interval must match the requested extension")
    if manifest.source != DOWNLOAD_SOURCE or not manifest.is_real_market_data:
        raise ValueError("parent must be non-synthetic real data from the same Settrade source")
    if manifest.broker != DOWNLOAD_BROKER_NAME:
        raise ValueError("parent broker does not match the Settrade acquisition workflow")
    if manifest.minimum_dataset_requirement_met is not False:
        raise ValueError("extension parent must be an interim dataset below the five-day minimum")
    if manifest.acquired_complete_trading_days != DOWNLOAD_MIN_TRADING_DAYS - 1:
        raise ValueError("extension parent must contain exactly four complete trading days")
    if manifest.acquired_date_range is None or manifest.requested_date_range is None:
        raise ValueError("parent acquisition date-range provenance is incomplete")

    loaded, report = _validate_normalized_dataset(parent_file, manifest)
    _require_exact_validation_pass(report, label="parent normalized dataset")
    parent_rows = _read_normalized_rows(parent_file)
    if len(parent_rows) != len(loaded.bars) or manifest.record_count != len(loaded.bars):
        raise ValueError("parent row count does not agree with its parsed bars and manifest")
    _strict_row_timestamps(parent_rows, label="parent normalized dataset")
    if any(bar.symbol != symbol for bar in loaded.bars):
        raise ValueError("parent normalized dataset contains a different contract symbol")

    trading_dates = tuple(sorted({bar.trading_date for bar in loaded.bars}))
    if len(trading_dates) != DOWNLOAD_MIN_TRADING_DAYS - 1:
        raise ValueError("parent normalized dataset does not contain exactly four trading dates")
    if (
        trading_dates[0] != manifest.acquired_date_range.start
        or trading_dates[-1] != manifest.acquired_date_range.end
    ):
        raise ValueError("parent bars do not match the acquired date-range provenance")
    parent_windows = _download_windows(
        symbol,
        start=trading_dates[0],
        end=trading_dates[-1],
        request_limit=DOWNLOAD_REQUEST_LIMIT,
        enforce_initial_range=False,
    )
    if tuple(dict.fromkeys(window.trading_date for window in parent_windows)) != trading_dates:
        raise ValueError("parent bars do not cover exactly the verified trading-date range")
    _require_capture_schedule(manifest.source_captures, parent_windows, label="parent dataset")
    _verify_raw_capture_checksums(manifest.source_captures)
    return manifest, loaded, parent_rows, trading_dates


def download(
    symbol: str,
    *,
    interval: str,
    start: date,
    end: date,
    environment: str,
    request_limit: int = DOWNLOAD_REQUEST_LIMIT,
    request_delay_seconds: float = DOWNLOAD_REQUEST_DELAY_SECONDS,
    interim_real_dataset: bool = False,
    unavailable_dates: tuple[date, ...] = (),
) -> DownloadResult:
    """Acquire 5-10 days as immutable raw responses plus a normalized validation CSV."""
    symbol = symbol.strip().upper()
    if interval != BarInterval.ONE_MINUTE.value:
        raise ValueError("initial Settrade acquisition supports only the verified 1m interval")
    if environment != "prod":
        raise ValueError("real Settrade acquisition requires the verified prod environment")
    if request_delay_seconds < 1.0:
        raise ValueError("request delay must be at least 1 second to respect 60 requests/minute")

    windows = _download_windows(
        symbol,
        start=start,
        end=end,
        request_limit=request_limit,
        enforce_initial_range=not interim_real_dataset,
    )
    acquired_dates = tuple(dict.fromkeys(window.trading_date for window in windows))
    normalized_unavailable_dates = tuple(sorted(set(unavailable_dates)))
    if interim_real_dataset:
        if not 1 <= len(acquired_dates) < DOWNLOAD_MIN_TRADING_DAYS:
            raise ValueError(
                "interim acquisition requires 1-4 acquired trading days; use standard "
                "acquisition when the five-day minimum is available"
            )
        if not normalized_unavailable_dates:
            raise ValueError(
                "interim acquisition requires at least one explicitly observed unavailable date"
            )
        if any(day in acquired_dates for day in normalized_unavailable_dates):
            raise ValueError("an unavailable date cannot also be in the acquired date range")
    elif normalized_unavailable_dates:
        raise ValueError("--unavailable-date is valid only for an interim real dataset")

    requested_start = min((start, *normalized_unavailable_dates))
    requested_end = max((end, *normalized_unavailable_dates))
    provenance_calendar = TradingCalendar(load_config(), HolidayStore())
    provenance_calendar.preflight(requested_start, requested_end)
    requested_dates = provenance_calendar.session_dates_in_range(requested_start, requested_end)
    if any(day not in requested_dates for day in normalized_unavailable_dates):
        raise ValueError("every unavailable date must be a verified TFEX trading day")
    if interim_real_dataset and len(requested_dates) < DOWNLOAD_MIN_TRADING_DAYS:
        raise ValueError(
            "interim provenance must describe an original request of at least five trading days"
        )

    interim_suffix = "-interim" if interim_real_dataset else ""
    dataset_id = (
        f"{symbol.lower()}-1m-{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
        f"-settrade{interim_suffix}"
    )
    raw_directory = HISTORICAL_RAW_ROOT / symbol / dataset_id
    filename_suffix = "_INTERIM" if interim_real_dataset else ""
    normalized_file = (
        HISTORICAL_NORMALIZED_ROOT
        / symbol
        / f"{symbol}_1m_{start.isoformat()}_{end.isoformat()}{filename_suffix}.csv"
    )
    manifest_file = manifest_path_for(normalized_file)
    existing = [path for path in (raw_directory, normalized_file, manifest_file) if path.exists()]
    if existing:
        raise FileExistsError(
            "immutable acquisition target already exists: "
            + ", ".join(str(path) for path in existing)
        )

    bindings, get_candlestick, credentials = _acquisition_client(
        symbol,
        interval=interval,
        environment=environment,
    )
    captures: list[tuple[DownloadWindow, Mapping[str, Any], int]] = []
    rows: list[dict[str, Any]] = []
    for index, window in enumerate(windows):
        # The CLI limit is a verified upper bound. Request exactly the number of legal
        # half-open bar slots so an inclusive server `end` cannot add a close-boundary bar.
        effective_limit = window.expected_bar_slots
        response = _request_window(
            get_candlestick,
            symbol=symbol,
            interval=interval,
            window=window,
            requested_limit=effective_limit,
            credentials=credentials,
        )
        # Validate and normalize immediately so an empty/unavailable session stops the batch
        # before any additional API request is made.
        rows.extend(
            _normalized_rows(
                symbol,
                [(window, response, effective_limit)],
            )
        )
        captures.append((window, response, effective_limit))
        if index + 1 < len(windows):
            sleep(request_delay_seconds)

    staging_parent = HISTORICAL_RAW_ROOT.parent / ".staging"
    try:
        staging_parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AcquisitionFailure(
            stage="file_write",
            category="LOCAL_FILESYSTEM_ERROR",
            message=str(exc),
            destination=staging_parent,
            cause=exc,
            credentials=credentials,
        ) from exc

    with TemporaryDirectory(prefix="settrade-acquisition-", dir=staging_parent) as temporary:
        staging_directory = Path(temporary)
        staged_raw_directory = staging_directory / raw_directory.name
        staged_normalized_file = staging_directory / normalized_file.name
        try:
            staged_raw_directory.mkdir()
            source_captures: list[SourceCapture] = []
            for window, response, effective_limit in captures:
                staged_raw_file = staged_raw_directory / window.filename
                staged_raw_file.write_text(
                    json.dumps(response, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                final_raw_file = raw_directory / window.filename
                source_captures.append(
                    SourceCapture(
                        file=_manifest_file_reference(final_raw_file),
                        sha256=file_sha256(staged_raw_file),
                        endpoint="techchart.candlesticks",
                        requested_start=window.start.strftime(SETTRADE_DATETIME_FORMAT),
                        requested_end=window.end.strftime(SETTRADE_DATETIME_FORMAT),
                        requested_limit=effective_limit,
                        normalized=False,
                        record_count=len(
                            _rows_from_response(
                                response,
                                window=window,
                                requested_limit=effective_limit,
                            )
                        ),
                    )
                )
            _write_normalized_csv(staged_normalized_file, rows)
        except AcquisitionFailure:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise AcquisitionFailure(
                stage="file_write",
                category="LOCAL_FILESYSTEM_ERROR",
                message=str(exc),
                destination=staging_directory,
                cause=exc,
                credentials=credentials,
            ) from exc

        try:
            loaded = load_bars(
                staged_normalized_file,
                source_timezone="Asia/Bangkok",
                symbol=symbol,
            )
        except Exception as exc:
            raise AcquisitionFailure(
                stage="normalization_validation",
                category="NORMALIZATION_VALIDATION_FAILED",
                message=str(exc),
                destination=staged_normalized_file,
                cause=exc,
                credentials=credentials,
            ) from exc
        if loaded.findings or len(loaded.bars) != len(rows):
            raise AcquisitionFailure(
                stage="normalization_validation",
                category="NORMALIZATION_VALIDATION_FAILED",
                message=(
                    f"normalized acquisition has {len(loaded.findings)} parse finding(s) "
                    f"and {len(loaded.bars)} parsed rows for {len(rows)} source rows"
                ),
                destination=staged_normalized_file,
            )

        try:
            manifest = build_manifest(
                staged_normalized_file,
                dataset_id=dataset_id,
                source=DOWNLOAD_SOURCE,
                authority=DOWNLOAD_AUTHORITY,
                symbol=symbol,
                interval=BarInterval(interval),
                source_timezone="Asia/Bangkok",
                normalized_timezone="UTC",
                bars=loaded.bars,
                license=DOWNLOAD_LICENSE,
                validation_status="PENDING_VALIDATION",
                broker=DOWNLOAD_BROKER_NAME,
                sdk_version=bindings.version,
                source_captures=tuple(source_captures),
                historical_availability_status=(
                    "INTERIM_REAL_DATASET_PARTIAL_HISTORICAL_AVAILABILITY"
                    if interim_real_dataset
                    else "REQUESTED_RANGE_ACQUIRED"
                ),
                requested_date_range=DatasetDateRange(
                    start=requested_start,
                    end=requested_end,
                ),
                acquired_date_range=DatasetDateRange(start=start, end=end),
                requested_trading_days=len(requested_dates),
                acquired_complete_trading_days=len(acquired_dates),
                unavailable_dates=normalized_unavailable_dates,
                retention_boundary_observed=bool(normalized_unavailable_dates),
                minimum_dataset_requirement_met=(len(acquired_dates) >= DOWNLOAD_MIN_TRADING_DAYS),
                source_raw_capture_sha256s=tuple(capture.sha256 for capture in source_captures),
                trading_dates=acquired_dates,
                complete_trading_days=len(acquired_dates),
                synthetic=False,
                note=(
                    f"Downloaded read-only from the {environment} environment. Raw "
                    "SDK-decoded responses are immutable. Do not commit or redistribute "
                    "until terms permit it."
                    + (
                        " An observed availability boundary is not an official provider "
                        "retention policy."
                        if normalized_unavailable_dates
                        else ""
                    )
                ),
            )
            staged_manifest_file = save_manifest(manifest, staged_normalized_file)
        except Exception as exc:
            raise AcquisitionFailure(
                stage="manifest",
                category="MANIFEST_PROVENANCE_FAILED",
                message=str(exc),
                destination=staged_normalized_file,
                cause=exc,
                credentials=credentials,
            ) from exc

        published: list[Path] = []
        try:
            raw_directory.parent.mkdir(parents=True, exist_ok=True)
            normalized_file.parent.mkdir(parents=True, exist_ok=True)
            staged_raw_directory.replace(raw_directory)
            published.append(raw_directory)
            staged_normalized_file.replace(normalized_file)
            published.append(normalized_file)
            staged_manifest_file.replace(manifest_file)
            published.append(manifest_file)
        except OSError as exc:
            for path in reversed(published):
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise AcquisitionFailure(
                stage="publish",
                category="LOCAL_FILESYSTEM_ERROR",
                message=str(exc),
                destination=raw_directory if not published else manifest_file,
                cause=exc,
                credentials=credentials,
            ) from exc

    return DownloadResult(
        raw_directory=raw_directory,
        normalized_file=normalized_file,
        manifest_file=manifest_file,
        candlestick_requests=len(windows),
    )


def extend_download(
    symbol: str,
    *,
    interval: str,
    trading_date: date,
    environment: str,
    parent_file: Path,
    parent_sha256: str,
    request_limit: int = DOWNLOAD_REQUEST_LIMIT,
    request_delay_seconds: float = DOWNLOAD_REQUEST_DELAY_SECONDS,
) -> DownloadResult:
    """Add one immutable complete day to a verified four-day interim dataset.

    Parent bytes and raw captures are verified before the API call and again immediately
    before publication. Only the two new session responses and a new five-day normalized
    dataset are published; a failure removes those new outputs and leaves the parent intact.
    """
    symbol = symbol.strip().upper()
    parent_sha256 = parent_sha256.strip().lower()
    if interval != BarInterval.ONE_MINUTE.value:
        raise ValueError("Settrade dataset extension supports only the verified 1m interval")
    if environment != "prod":
        raise ValueError("real Settrade dataset extension requires the verified prod environment")
    if request_delay_seconds < 1.0:
        raise ValueError("request delay must be at least 1 second to respect 60 requests/minute")

    parent_file = parent_file.resolve()
    parent_manifest, parent_loaded, parent_rows, parent_dates = _verified_parent_dataset(
        parent_file,
        expected_sha256=parent_sha256,
        symbol=symbol,
        interval=interval,
    )
    parent_manifest_file = manifest_path_for(parent_file)
    parent_manifest_file_sha256 = file_sha256(parent_manifest_file)
    if parent_manifest.source_timezone != "Asia/Bangkok":
        raise ValueError("parent source timezone must be Asia/Bangkok")
    if parent_manifest.normalized_timezone != "UTC":
        raise ValueError("parent normalized timezone must be UTC")
    parent_requested_range = parent_manifest.requested_date_range
    if parent_requested_range is None:  # already enforced; keeps this invariant local
        raise ValueError("parent requested date-range provenance is incomplete")
    if trading_date <= parent_dates[-1]:
        raise ValueError("extension trading date must be later than every parent trading date")

    windows = _download_windows(
        symbol,
        start=trading_date,
        end=trading_date,
        request_limit=request_limit,
        enforce_initial_range=False,
    )
    extension_dates = tuple(dict.fromkeys(window.trading_date for window in windows))
    if extension_dates != (trading_date,) or len(windows) != 2:
        raise ValueError("extension date must be one verified complete TFEX trading day")
    final_dates = (*parent_dates, trading_date)
    if len(final_dates) != DOWNLOAD_MIN_TRADING_DAYS or final_dates != tuple(sorted(final_dates)):
        raise ValueError("extension must produce exactly five ordered trading dates")

    extension_id = f"{symbol.lower()}-1m-{trading_date.strftime('%Y%m%d')}-settrade-extension"
    dataset_id = (
        f"{symbol.lower()}-1m-{parent_dates[0].strftime('%Y%m%d')}-"
        f"{trading_date.strftime('%Y%m%d')}-settrade-extended"
    )
    raw_directory = HISTORICAL_RAW_ROOT / symbol / extension_id
    normalized_file = (
        HISTORICAL_NORMALIZED_ROOT
        / symbol
        / f"{symbol}_1m_{parent_dates[0].isoformat()}_{trading_date.isoformat()}.csv"
    )
    manifest_file = manifest_path_for(normalized_file)
    existing = [path for path in (raw_directory, normalized_file, manifest_file) if path.exists()]
    if existing:
        raise FileExistsError(
            "immutable extension target already exists: "
            + ", ".join(str(path) for path in existing)
        )

    bindings, get_candlestick, credentials = _acquisition_client(
        symbol,
        interval=interval,
        environment=environment,
    )
    if parent_manifest.sdk_version != bindings.version:
        raise SdkCompatibilityError(
            "extension SDK version differs from the parent dataset acquisition"
        )

    captures: list[tuple[DownloadWindow, Mapping[str, Any], int]] = []
    new_rows: list[dict[str, Any]] = []
    for index, window in enumerate(windows):
        effective_limit = window.expected_bar_slots
        response = _request_window(
            get_candlestick,
            symbol=symbol,
            interval=interval,
            window=window,
            requested_limit=effective_limit,
            credentials=credentials,
        )
        new_rows.extend(_normalized_rows(symbol, [(window, response, effective_limit)]))
        captures.append((window, response, effective_limit))
        if index + 1 < len(windows):
            sleep(request_delay_seconds)

    parent_timestamps = _strict_row_timestamps(parent_rows, label="parent normalized dataset")
    extension_timestamps = _strict_row_timestamps(new_rows, label="new raw acquisition")
    if not parent_timestamps or not extension_timestamps:
        raise AcquisitionFailure(
            stage="merge_validation",
            category="MERGE_INPUT_EMPTY",
            message="parent and extension must both contain normalized bars",
            credentials=credentials,
        )
    if parent_timestamps[-1] >= extension_timestamps[0]:
        raise AcquisitionFailure(
            stage="merge_validation",
            category="RAW_CAPTURE_OVERLAP",
            message="new raw acquisition overlaps the parent normalized dataset",
            credentials=credentials,
        )
    combined_rows = [*parent_rows, *new_rows]
    combined_timestamps = _strict_row_timestamps(
        combined_rows, label="five-day normalized candidate"
    )
    if len(combined_timestamps) != len(set(combined_timestamps)):
        raise AcquisitionFailure(
            stage="merge_validation",
            category="DUPLICATE_TIMESTAMP",
            message="five-day candidate contains duplicate timestamps",
            credentials=credentials,
        )

    staging_parent = HISTORICAL_RAW_ROOT.parent / ".staging"
    try:
        staging_parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AcquisitionFailure(
            stage="file_write",
            category="LOCAL_FILESYSTEM_ERROR",
            message=str(exc),
            destination=staging_parent,
            cause=exc,
            credentials=credentials,
        ) from exc

    with TemporaryDirectory(prefix="settrade-extension-", dir=staging_parent) as temporary:
        staging_directory = Path(temporary)
        staged_raw_directory = staging_directory / raw_directory.name
        staged_normalized_file = staging_directory / normalized_file.name
        try:
            staged_raw_directory.mkdir()
            new_source_captures: list[SourceCapture] = []
            for window, response, effective_limit in captures:
                staged_raw_file = staged_raw_directory / window.filename
                staged_raw_file.write_text(
                    json.dumps(response, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                final_raw_file = raw_directory / window.filename
                new_source_captures.append(
                    SourceCapture(
                        file=_manifest_file_reference(final_raw_file),
                        sha256=file_sha256(staged_raw_file),
                        endpoint="techchart.candlesticks",
                        requested_start=window.start.strftime(SETTRADE_DATETIME_FORMAT),
                        requested_end=window.end.strftime(SETTRADE_DATETIME_FORMAT),
                        requested_limit=effective_limit,
                        normalized=False,
                        record_count=len(
                            _rows_from_response(
                                response,
                                window=window,
                                requested_limit=effective_limit,
                            )
                        ),
                    )
                )
            _require_capture_schedule(tuple(new_source_captures), windows, label="new acquisition")
            _write_normalized_csv(staged_normalized_file, combined_rows)
        except AcquisitionFailure:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise AcquisitionFailure(
                stage="file_write",
                category="LOCAL_FILESYSTEM_ERROR",
                message=str(exc),
                destination=staging_directory,
                cause=exc,
                credentials=credentials,
            ) from exc

        try:
            loaded = load_bars(
                staged_normalized_file,
                source_timezone=parent_manifest.source_timezone,
                symbol=symbol,
            )
        except Exception as exc:
            raise AcquisitionFailure(
                stage="merge_validation",
                category="NORMALIZATION_VALIDATION_FAILED",
                message=str(exc),
                destination=staged_normalized_file,
                cause=exc,
                credentials=credentials,
            ) from exc
        actual_dates = tuple(sorted({bar.trading_date for bar in loaded.bars}))
        if (
            loaded.findings
            or len(loaded.bars) != len(combined_rows)
            or actual_dates != final_dates
            or len(loaded.bars)
            != len(parent_loaded.bars) + sum(window.expected_bar_slots for window in windows)
        ):
            raise AcquisitionFailure(
                stage="merge_validation",
                category="MERGE_INVARIANT_FAILED",
                message=(
                    "five-day candidate does not preserve exact rows, complete sessions, "
                    "and trading dates"
                ),
                destination=staged_normalized_file,
                credentials=credentials,
            )

        all_source_captures = (
            *parent_manifest.source_captures,
            *tuple(new_source_captures),
        )
        all_windows = _download_windows(
            symbol,
            start=final_dates[0],
            end=final_dates[-1],
            request_limit=request_limit,
            enforce_initial_range=False,
        )
        try:
            _require_capture_schedule(all_source_captures, all_windows, label="five-day dataset")
            requested_start = min(
                parent_requested_range.start,
                final_dates[0],
            )
            requested_end = max(parent_requested_range.end, trading_date)
            provenance_calendar = TradingCalendar(load_config(), HolidayStore())
            provenance_calendar.preflight(requested_start, requested_end)
            requested_dates = provenance_calendar.session_dates_in_range(
                requested_start, requested_end
            )
            all_raw_hashes = tuple(capture.sha256 for capture in all_source_captures)
            new_raw_hashes = tuple(capture.sha256 for capture in new_source_captures)
            manifest = build_manifest(
                staged_normalized_file,
                dataset_id=dataset_id,
                source=parent_manifest.source,
                authority=parent_manifest.authority or DOWNLOAD_AUTHORITY,
                symbol=symbol,
                interval=BarInterval(interval),
                source_timezone=parent_manifest.source_timezone,
                normalized_timezone=parent_manifest.normalized_timezone,
                bars=loaded.bars,
                license=parent_manifest.license or DOWNLOAD_LICENSE,
                validation_status=ValidationOutcome.PASS.value,
                validator_version=VALIDATOR_VERSION,
                broker=parent_manifest.broker,
                sdk_version=bindings.version,
                source_captures=all_source_captures,
                historical_availability_status=("EXTENDED_REAL_DATASET_MINIMUM_HISTORY_MET"),
                requested_date_range=DatasetDateRange(
                    start=requested_start,
                    end=requested_end,
                ),
                acquired_date_range=DatasetDateRange(
                    start=final_dates[0],
                    end=final_dates[-1],
                ),
                requested_trading_days=len(requested_dates),
                acquired_complete_trading_days=len(final_dates),
                unavailable_dates=parent_manifest.unavailable_dates,
                retention_boundary_observed=parent_manifest.retention_boundary_observed,
                minimum_dataset_requirement_met=True,
                parent_dataset_id=parent_manifest.dataset_id,
                parent_normalized_sha256=parent_manifest.sha256,
                source_raw_capture_sha256s=all_raw_hashes,
                new_raw_capture_sha256s=new_raw_hashes,
                trading_dates=final_dates,
                complete_trading_days=len(final_dates),
                synthetic=False,
                note=(
                    f"Atomically extended {parent_manifest.dataset_id} with one immutable "
                    f"read-only {trading_date.isoformat()} raw acquisition from the "
                    f"{environment} environment. Parent files were not modified. Do not "
                    "commit or redistribute raw data until terms permit it. The previously "
                    "observed availability boundary is not an official retention policy."
                ),
            )
            _, report = _validate_normalized_dataset(staged_normalized_file, manifest)
            _require_exact_validation_pass(report, label="five-day normalized candidate")
            staged_manifest_file = save_manifest(manifest, staged_normalized_file)
        except Exception as exc:
            raise AcquisitionFailure(
                stage="merge_validation",
                category="FIVE_DAY_VALIDATION_FAILED",
                message=str(exc),
                destination=staged_normalized_file,
                cause=exc,
                credentials=credentials,
            ) from exc

        # Detect any concurrent or accidental parent mutation before publishing new lineage.
        if file_sha256(parent_file) != parent_sha256:
            raise AcquisitionFailure(
                stage="lineage_reverification",
                category="PARENT_CHECKSUM_CHANGED",
                message="parent normalized dataset changed during extension",
                credentials=credentials,
            )
        if file_sha256(parent_manifest_file) != parent_manifest_file_sha256:
            raise AcquisitionFailure(
                stage="lineage_reverification",
                category="PARENT_MANIFEST_CHANGED",
                message="parent provenance manifest changed during extension",
                credentials=credentials,
            )
        try:
            _verify_raw_capture_checksums(parent_manifest.source_captures)
        except ValueError as exc:
            raise AcquisitionFailure(
                stage="lineage_reverification",
                category="PARENT_RAW_CHECKSUM_CHANGED",
                message=str(exc),
                cause=exc,
                credentials=credentials,
            ) from exc

        published: list[Path] = []
        try:
            raw_directory.parent.mkdir(parents=True, exist_ok=True)
            normalized_file.parent.mkdir(parents=True, exist_ok=True)
            staged_raw_directory.replace(raw_directory)
            published.append(raw_directory)
            staged_normalized_file.replace(normalized_file)
            published.append(normalized_file)
            staged_manifest_file.replace(manifest_file)
            published.append(manifest_file)
        except OSError as exc:
            for path in reversed(published):
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise AcquisitionFailure(
                stage="publish",
                category="LOCAL_FILESYSTEM_ERROR",
                message=str(exc),
                destination=raw_directory if not published else manifest_file,
                cause=exc,
                credentials=credentials,
            ) from exc

    return DownloadResult(
        raw_directory=raw_directory,
        normalized_file=normalized_file,
        manifest_file=manifest_file,
        candlestick_requests=len(windows),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="contract symbol, e.g. S50Z26")
    parser.add_argument("--interval", default="1m", choices=list(DOCUMENTED_INTERVALS))
    parser.add_argument(
        "--start",
        help="probe: YYYY-MM-DDTHH:MM; download: YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        help="probe: YYYY-MM-DDTHH:MM; download: YYYY-MM-DD",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="bar limit per request; defaults to 5 for probe and 200 for acquisition",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=DOWNLOAD_REQUEST_DELAY_SECONDS,
        help="acquisition delay between candlestick requests; minimum 1 second",
    )
    parser.add_argument("--environment", default="prod", choices=("prod", "uat"))
    parser.add_argument(
        "--probe",
        action="store_true",
        help="make one read-only call to establish capability, and write the evidence file",
    )
    parser.add_argument(
        "--probe-mode",
        default="candlestick",
        choices=PROBE_MODES,
        help="stop after authentication, make one quote, or make one candlestick request",
    )
    parser.add_argument(
        "--diagnose-session",
        choices=("morning", "afternoon"),
        help=(
            "make exactly one session request, print only sanitized schema/boundary "
            "diagnostics, and write no market-data file"
        ),
    )
    parser.add_argument(
        "--interim-real-dataset",
        action="store_true",
        help=(
            "explicitly acquire 1-4 available trading days as interim real data; this "
            "never satisfies the five-day minimum"
        ),
    )
    parser.add_argument(
        "--unavailable-date",
        action="append",
        default=[],
        metavar="YYYY-MM-DD",
        help=(
            "verified trading date observed unavailable in the original request; repeatable "
            "and valid only with --interim-real-dataset"
        ),
    )
    parser.add_argument(
        "--extend-parent",
        type=Path,
        help=(
            "validated four-day interim normalized CSV to preserve and extend with exactly "
            "one later complete trading day"
        ),
    )
    parser.add_argument(
        "--parent-normalized-sha256",
        help="required expected SHA-256 of --extend-parent; values are not inferred",
    )
    args = parser.parse_args(argv)

    if args.probe and args.diagnose_session:
        parser.error("--probe and --diagnose-session are mutually exclusive")
    if (args.probe or args.diagnose_session) and (
        args.interim_real_dataset
        or args.unavailable_date
        or args.extend_parent
        or args.parent_normalized_sha256
    ):
        parser.error("acquisition options cannot be combined with probe/session diagnosis")
    if args.extend_parent and (args.interim_real_dataset or args.unavailable_date):
        parser.error("dataset extension cannot be combined with interim acquisition options")
    if bool(args.extend_parent) != bool(args.parent_normalized_sha256):
        parser.error("--extend-parent and --parent-normalized-sha256 are required together")

    if args.probe:
        evidence = probe(
            args.symbol,
            environment=args.environment,
            interval=args.interval,
            probe_mode=args.probe_mode,
            start=args.start,
            end=args.end,
            limit=args.limit if args.limit is not None else 5,
        )
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
        print(f"\nwrote {EVIDENCE_PATH}")
        if evidence["decision"] != SETTRADE_REAL_DATA_READY:
            print(
                "\nThe probe could not confirm capability. Nothing was fabricated in its "
                "place; the persisted data-readiness gate was not changed.",
                file=sys.stderr,
            )
            return 3
        return 0

    if args.diagnose_session:
        if not args.start:
            parser.error("--start YYYY-MM-DD is required with --diagnose-session")
        if args.end:
            parser.error("--end must be omitted with --diagnose-session")
        try:
            diagnostic = diagnose_session(
                args.symbol,
                interval=args.interval,
                trading_date=date.fromisoformat(args.start),
                session=args.diagnose_session,
                environment=args.environment,
                request_limit=args.limit if args.limit is not None else DOWNLOAD_REQUEST_LIMIT,
            )
        except AcquisitionFailure as exc:
            print(json.dumps(exc.diagnostic, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1
        except (
            CredentialsMissing,
            SdkMissing,
            SdkCompatibilityError,
            ValueError,
        ) as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 3
        except Exception as exc:
            fallback = AcquisitionFailure(
                stage="internal",
                category="UNCLASSIFIED_INTERNAL_ERROR",
                message="unexpected internal failure; exception details redacted",
                cause=exc,
            )
            print(json.dumps(fallback.diagnostic, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(diagnostic, indent=2, ensure_ascii=False))
        return 0

    if not args.start or not args.end:
        parser.error("--start and --end are required for acquisition")

    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
        if args.extend_parent:
            if start_date != end_date:
                parser.error("dataset extension requires --start and --end to be the same date")
            result = extend_download(
                args.symbol,
                interval=args.interval,
                trading_date=start_date,
                environment=args.environment,
                parent_file=args.extend_parent,
                parent_sha256=args.parent_normalized_sha256,
                request_limit=args.limit if args.limit is not None else DOWNLOAD_REQUEST_LIMIT,
                request_delay_seconds=args.request_delay_seconds,
            )
        else:
            result = download(
                args.symbol,
                interval=args.interval,
                start=start_date,
                end=end_date,
                environment=args.environment,
                request_limit=args.limit if args.limit is not None else DOWNLOAD_REQUEST_LIMIT,
                request_delay_seconds=args.request_delay_seconds,
                interim_real_dataset=args.interim_real_dataset,
                unavailable_dates=tuple(
                    date.fromisoformat(value) for value in args.unavailable_date
                ),
            )
    except AcquisitionFailure as exc:
        print(json.dumps(exc.diagnostic, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    except (
        CredentialsMissing,
        FileExistsError,
        SdkMissing,
        SdkCompatibilityError,
        ValueError,
    ) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        fallback = AcquisitionFailure(
            stage="internal",
            category="UNCLASSIFIED_INTERNAL_ERROR",
            message="unexpected internal failure; exception details redacted",
            cause=exc,
        )
        print(json.dumps(fallback.diagnostic, indent=2), file=sys.stderr)
        return 1

    print(f"raw responses: {result.raw_directory}")
    print(f"normalized CSV: {result.normalized_file}")
    print(f"manifest: {result.manifest_file}")
    print(f"candlestick requests: {result.candlestick_requests}")
    print(
        "dataset classification: "
        + (
            "EXTENDED_REAL_DATASET"
            if args.extend_parent
            else "INTERIM_REAL_DATASET"
            if args.interim_real_dataset
            else "REAL_DATASET"
        )
    )
    print("minimum dataset requirement met: " + ("false" if args.interim_real_dataset else "true"))
    print(f"normalized SHA-256: {file_sha256(result.normalized_file)}")
    print("Validate it before use:")
    print(
        f"  uv run python scripts/validate_tfex_market_data.py --file "
        f"{result.normalized_file} "
        f"--symbol {args.symbol} --interval {args.interval} --timezone Asia/Bangkok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
