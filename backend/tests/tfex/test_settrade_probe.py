"""Safety and SDK-compatibility tests for the read-only Settrade capability probe."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from importlib import import_module
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.tfex.marketdata.manifest import file_sha256, load_manifest
from scripts.data_sources import settrade_history as probe_module

SECRET_VALUES = {
    "SETTRADE_APP_ID": "private-app-id",
    "SETTRADE_APP_SECRET": "private-app-secret",
    "SETTRADE_BROKER_ID": "private-broker-id",
    "SETTRADE_APP_CODE": "private-app-code",
}


class FakeApiError(RuntimeError):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def _set_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in SECRET_VALUES.items():
        monkeypatch.setenv(name, value)


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in probe_module.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch, investor_class: type[Any]
) -> tuple[dict[str, Any], list[str]]:
    sdk_config: dict[str, Any] = {"environment": "prod"}
    package = SimpleNamespace(Investor=investor_class, __version__="2.2.1")
    config_module = SimpleNamespace(config=sdk_config)
    imported: list[str] = []

    def fake_import(name: str) -> Any:
        imported.append(name)
        if name == "settrade_v2":
            return package
        if name == "settrade_v2.config":
            return config_module
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr(probe_module, "import_module", fake_import)
    return sdk_config, imported


def _successful_investor(
    events: list[str], received_requests: list[dict[str, Any]] | None = None
) -> type[Any]:
    class MarketData:
        def get_candlestick(
            self,
            symbol: str,
            interval: str,
            limit: int | None = None,
            start: str | None = None,
            end: str | None = None,
            normalized: bool | None = None,
        ) -> dict[str, list[int]]:
            if received_requests is not None:
                received_requests.append(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "limit": limit,
                        "start": start,
                        "end": end,
                        "normalized": normalized,
                    }
                )
            events.append("get_candlestick")
            return {"time": [1, 2]}

        def get_quote_symbol(self, symbol: str) -> dict[str, str]:
            if received_requests is not None:
                received_requests.append({"symbol": symbol})
            events.append("get_quote_symbol")
            return {"symbol": symbol}

    class Investor:
        def __init__(
            self,
            app_id: str,
            app_secret: str,
            app_code: str,
            broker_id: str,
            is_auto_queue: bool = False,
        ) -> None:
            del app_id, app_secret, app_code, broker_id, is_auto_queue
            events.append("Investor")

        def MarketData(self) -> MarketData:
            events.append("MarketData")
            return MarketData()

        def Derivatives(self, account_no: str) -> None:
            del account_no
            raise AssertionError("the read-only probe must not access derivatives orders")

    return Investor


def _failing_market_investor(error: Exception) -> type[Any]:
    class MarketData:
        def get_candlestick(
            self,
            symbol: str,
            interval: str,
            limit: int | None = None,
            start: str | None = None,
            end: str | None = None,
            normalized: bool | None = None,
        ) -> dict[str, Any]:
            del symbol, interval, limit, start, end, normalized
            raise error

    class Investor:
        def __init__(
            self,
            app_id: str,
            app_secret: str,
            app_code: str,
            broker_id: str,
            is_auto_queue: bool = False,
        ) -> None:
            del app_id, app_secret, app_code, broker_id, is_auto_queue

        def MarketData(self) -> MarketData:
            return MarketData()

    return Investor


def _download_investor(
    events: list[str],
    received_requests: list[dict[str, Any]],
    auto_queue_values: list[bool],
    *,
    fail_on_request: int | None = None,
    empty_on_dates: set[str] | None = None,
) -> type[Any]:
    class MarketData:
        def get_candlestick(
            self,
            symbol: str,
            interval: str,
            limit: int | None = None,
            start: str | None = None,
            end: str | None = None,
            normalized: bool | None = None,
        ) -> dict[str, Any]:
            assert start is not None
            requested = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "start": start,
                "end": end,
                "normalized": normalized,
            }
            received_requests.append(requested)
            events.append("get_candlestick")
            if fail_on_request == len(received_requests):
                raise FakeApiError(
                    status_code=500,
                    code="SERVER_ERROR",
                    message="temporary market-data failure",
                )
            market_time = datetime.strptime(start, "%Y-%m-%dT%H:%M").replace(
                tzinfo=ZoneInfo("Asia/Bangkok")
            )
            count = 0 if empty_on_dates and start[:10] in empty_on_dates else int(limit or 0)
            return _candlestick_response(market_time, count)

    class Investor:
        def __init__(
            self,
            app_id: str,
            app_secret: str,
            app_code: str,
            broker_id: str,
            is_auto_queue: bool = False,
        ) -> None:
            del app_id, app_secret, app_code, broker_id
            auto_queue_values.append(is_auto_queue)
            events.append("Investor")

        def MarketData(self) -> MarketData:
            events.append("MarketData")
            return MarketData()

        def Derivatives(self, account_no: str) -> None:
            del account_no
            raise AssertionError("download must never access derivatives order APIs")

    return Investor


def _set_ready_acquisition_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    evidence_path = tmp_path / "settrade_capability.json"
    evidence_path.write_text(
        json.dumps(
            {
                "decision": probe_module.SETTRADE_REAL_DATA_READY,
                "environment": "prod",
                "symbol": "S50U26",
                "interval": "1m",
                "sdk_version": "2.2.1",
                "authentication": "CONFIRMED",
                "derivatives_market_data_entitlement": "CONFIRMED",
                "historical_derivatives_candlestick": "CONFIRMED",
                "raw_contract_symbol_supported": "CONFIRMED",
                "one_minute_interval_supported": "CONFIRMED",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe_module, "EVIDENCE_PATH", evidence_path)
    return evidence_path


def test_loads_settrade_v2_and_configures_environment_outside_investor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    sdk_config, imported = _install_fake_sdk(monkeypatch, _successful_investor(events))

    bindings = probe_module._load_sdk("uat")

    assert imported == ["settrade_v2", "settrade_v2.config"]
    assert "settrade" not in imported
    assert sdk_config["environment"] == "uat"
    assert bindings.version == "2.2.1"
    assert "environment" not in bindings.investor_signature


def test_constructs_investor_with_verified_221_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    class Investor:
        def __init__(
            self,
            app_id: str,
            app_secret: str,
            app_code: str,
            broker_id: str,
            is_auto_queue: bool = False,
        ) -> None:
            received.update(
                app_id=app_id,
                app_secret=app_secret,
                app_code=app_code,
                broker_id=broker_id,
                is_auto_queue=is_auto_queue,
            )

    sdk_config, _ = _install_fake_sdk(monkeypatch, Investor)
    _set_credentials(monkeypatch)

    probe_module._investor("prod")

    assert sdk_config["environment"] == "prod"
    assert received == {
        "app_id": SECRET_VALUES["SETTRADE_APP_ID"],
        "app_secret": SECRET_VALUES["SETTRADE_APP_SECRET"],
        "app_code": SECRET_VALUES["SETTRADE_APP_CODE"],
        "broker_id": SECRET_VALUES["SETTRADE_BROKER_ID"],
        "is_auto_queue": False,
    }
    assert "environment" not in received


def test_installed_settrade_221_candlestick_signature() -> None:
    sdk = pytest.importorskip("settrade_v2", reason="settrade-v2 is an optional dependency")
    market_module = import_module("settrade_v2.market")

    assert sdk.__version__ == "2.2.1"
    assert str(signature(sdk.Investor.MarketData)) == "(self)"
    assert str(signature(market_module.MarketData.get_candlestick)) == (
        "(self, symbol: str, interval: str, limit: Optional[int] = None, "
        "start: Optional[str] = None, end: Optional[str] = None, "
        "normalized: Optional[bool] = None)"
    )


def test_candlestick_parameters_use_documented_datetime_strings() -> None:
    parameters = probe_module._candlestick_parameters(
        "S50U26",
        "1m",
        start="2026-09-11T09:45",
        end="2026-09-11T09:50",
        limit=5,
    )

    assert parameters == {
        "symbol": "S50U26",
        "interval": "1m",
        "start": "2026-09-11T09:45",
        "end": "2026-09-11T09:50",
        "limit": 5,
    }
    assert {name: type(value).__name__ for name, value in parameters.items()} == {
        "symbol": "str",
        "interval": "str",
        "start": "str",
        "end": "str",
        "limit": "int",
    }


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-09-11", "2026-09-12"),
        ("2026-09-11T09:45:00", "2026-09-11T09:50:00"),
        ("2026-09-11T09:50", "2026-09-11T09:45"),
    ],
)
def test_candlestick_parameters_reject_invalid_date_ranges(start: str, end: str) -> None:
    with pytest.raises(ValueError):
        probe_module._candlestick_parameters("S50U26", "1m", start=start, end=end, limit=5)


@pytest.mark.parametrize(
    ("probe_mode", "expected_decision", "expected_events", "request_attempted"),
    [
        (
            "authentication",
            probe_module.SETTRADE_AUTHENTICATION_CONFIRMED,
            ["Investor"],
            False,
        ),
        (
            "quote",
            probe_module.SETTRADE_SYMBOL_RECOGNIZED,
            ["Investor", "MarketData", "get_quote_symbol"],
            True,
        ),
    ],
)
def test_focused_probe_modes_make_at_most_one_market_request(
    monkeypatch: pytest.MonkeyPatch,
    probe_mode: str,
    expected_decision: str,
    expected_events: list[str],
    request_attempted: bool,
) -> None:
    events: list[str] = []
    _install_fake_sdk(monkeypatch, _successful_investor(events))
    _set_credentials(monkeypatch)

    evidence = probe_module.probe("S50U26", environment="prod", probe_mode=probe_mode)

    assert evidence["decision"] == expected_decision
    assert evidence["api_request_attempted"] is request_attempted
    assert events == expected_events


def test_successful_probe_uses_only_market_data_and_never_outputs_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    received_requests: list[dict[str, Any]] = []
    _install_fake_sdk(monkeypatch, _successful_investor(events, received_requests))
    _set_credentials(monkeypatch)
    evidence_path = tmp_path / "settrade_capability.json"
    monkeypatch.setattr(probe_module, "EVIDENCE_PATH", evidence_path)

    exit_code = probe_module.main(
        [
            "--probe",
            "--symbol",
            "S50U26",
            "--start",
            "2026-09-11T09:45",
            "--end",
            "2026-09-11T09:50",
            "--limit",
            "5",
        ]
    )

    output = capsys.readouterr()
    persisted = evidence_path.read_text(encoding="utf-8")
    combined = output.out + output.err + persisted
    assert exit_code == 0
    assert events == ["Investor", "MarketData", "get_candlestick"]
    assert received_requests == [
        {
            "symbol": "S50U26",
            "interval": "1m",
            "limit": 5,
            "start": "2026-09-11T09:45",
            "end": "2026-09-11T09:50",
            "normalized": None,
        }
    ]
    assert all(secret not in combined for secret in SECRET_VALUES.values())
    evidence = json.loads(persisted)
    assert evidence["decision"] == probe_module.SETTRADE_REAL_DATA_READY
    assert evidence["authentication"] == "CONFIRMED"
    assert evidence["api_request_attempted"] is True
    assert evidence["api_endpoint"] == "techchart.candlesticks"
    assert evidence["request_parameter_names"] == [
        "end",
        "interval",
        "limit",
        "start",
        "symbol",
    ]
    assert evidence["request_parameter_types"] == {
        "end": "str",
        "interval": "str",
        "limit": "int",
        "start": "str",
        "symbol": "str",
    }


def test_download_is_session_windowed_immutable_and_provenanced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    investor = _download_investor(events, requests, auto_queue_values)
    _install_fake_sdk(monkeypatch, investor)
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    delays: list[float] = []
    monkeypatch.setattr(probe_module, "sleep", delays.append)

    result = probe_module.download(
        "S50U26",
        interval="1m",
        start=date(2026, 9, 7),
        end=date(2026, 9, 11),
        environment="prod",
        request_limit=200,
        request_delay_seconds=1.0,
    )

    assert result.candlestick_requests == 10
    assert events == ["Investor", "MarketData", *("get_candlestick" for _ in range(10))]
    assert auto_queue_values == [True]
    assert delays == [1.0] * 9
    assert [(request["start"], request["end"]) for request in requests[:2]] == [
        ("2026-09-07T09:45", "2026-09-07T12:30"),
        ("2026-09-07T13:45", "2026-09-07T16:55"),
    ]
    assert (requests[-1]["start"], requests[-1]["end"]) == (
        "2026-09-11T13:45",
        "2026-09-11T16:55",
    )
    assert [request["limit"] for request in requests[:2]] == [165, 190]
    assert {request["limit"] for request in requests} == {165, 190}
    assert all(request["normalized"] is False for request in requests)

    raw_files = sorted(result.raw_directory.glob("*.settrade.json"))
    assert len(raw_files) == 10
    assert result.normalized_file.is_file()
    normalized_text = result.normalized_file.read_text(encoding="utf-8")
    assert "symbol,timestamp,source_timestamp,open,high,low,close,volume" in normalized_text
    assert "S50U26,2026-09-07T02:45:00+00:00" in normalized_text
    assert "value" in normalized_text

    manifest = load_manifest(result.normalized_file)
    assert result.manifest_file.is_file()
    assert manifest.dataset_id == "s50u26-1m-20260907-20260911-settrade"
    assert manifest.symbol == "S50U26"
    assert manifest.record_count == 1775
    assert manifest.trading_days == 5
    assert manifest.broker == "InnovestX"
    assert manifest.sdk_version == "2.2.1"
    assert manifest.normalized_timezone == "UTC"
    assert manifest.validation_status == "PENDING_VALIDATION"
    assert manifest.historical_availability_status == "REQUESTED_RANGE_ACQUIRED"
    assert manifest.requested_trading_days == 5
    assert manifest.acquired_complete_trading_days == 5
    assert manifest.unavailable_dates == ()
    assert manifest.retention_boundary_observed is False
    assert manifest.minimum_dataset_requirement_met is True
    assert manifest.sha256 == file_sha256(result.normalized_file)
    assert len(manifest.source_captures) == 10
    assert all(capture.normalized is False for capture in manifest.source_captures)
    assert all(
        capture.sha256 == file_sha256(probe_module.BACKEND_ROOT / capture.file)
        for capture in manifest.source_captures
    )

    persisted = normalized_text + result.manifest_file.read_text(encoding="utf-8")
    persisted += "".join(path.read_text(encoding="utf-8") for path in raw_files)
    assert all(secret not in persisted for secret in SECRET_VALUES.values())

    with pytest.raises(FileExistsError, match="immutable acquisition target"):
        probe_module.download(
            "S50U26",
            interval="1m",
            start=date(2026, 9, 7),
            end=date(2026, 9, 11),
            environment="prod",
            request_limit=200,
            request_delay_seconds=1.0,
        )
    assert len(requests) == 10


def test_download_failure_writes_no_partial_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    investor = _download_investor(
        events,
        requests,
        auto_queue_values,
        fail_on_request=2,
    )
    _install_fake_sdk(monkeypatch, investor)
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)

    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module.download(
            "S50U26",
            interval="1m",
            start=date(2026, 9, 7),
            end=date(2026, 9, 11),
            environment="prod",
            request_limit=200,
            request_delay_seconds=1.0,
        )

    assert caught.value.diagnostic["acquisition_stage"] == "api_request"
    assert caught.value.diagnostic["exception_category"] == "SETTRADE_API_ERROR"
    assert caught.value.diagnostic["session_date"] == "2026-09-07"
    assert caught.value.diagnostic["session"] == "afternoon"
    assert len(requests) == 2
    assert not raw_root.exists()
    assert not normalized_root.exists()


def test_explicit_unavailable_day_fails_without_skipping_or_more_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    investor = _download_investor(
        events,
        requests,
        auto_queue_values,
        empty_on_dates={"2026-09-07"},
    )
    _install_fake_sdk(monkeypatch, investor)
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)

    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module.download(
            "S50U26",
            interval="1m",
            start=date(2026, 9, 7),
            end=date(2026, 9, 11),
            environment="prod",
        )

    assert caught.value.diagnostic["exception_category"] == "SESSION_EMPTY"
    assert caught.value.diagnostic["session_date"] == "2026-09-07"
    assert caught.value.diagnostic["response_schema"]["returned_bars"] == 0
    assert len(requests) == 1
    assert not raw_root.exists()
    assert not normalized_root.exists()


def test_four_day_interim_dataset_records_availability_and_never_meets_minimum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)

    result = probe_module.download(
        "S50U26",
        interval="1m",
        start=date(2026, 9, 8),
        end=date(2026, 9, 11),
        environment="prod",
        interim_real_dataset=True,
        unavailable_dates=(date(2026, 9, 7),),
    )

    manifest = load_manifest(result.normalized_file)
    assert result.candlestick_requests == 8
    assert len(requests) == 8
    assert manifest.dataset_id == "s50u26-1m-20260908-20260911-settrade-interim"
    assert result.normalized_file.name.endswith("_INTERIM.csv")
    assert manifest.record_count == 1420
    assert manifest.trading_days == 4
    assert manifest.historical_availability_status == (
        "INTERIM_REAL_DATASET_PARTIAL_HISTORICAL_AVAILABILITY"
    )
    assert manifest.requested_date_range is not None
    assert manifest.requested_date_range.start == date(2026, 9, 7)
    assert manifest.requested_date_range.end == date(2026, 9, 11)
    assert manifest.acquired_date_range is not None
    assert manifest.acquired_date_range.start == date(2026, 9, 8)
    assert manifest.acquired_date_range.end == date(2026, 9, 11)
    assert manifest.requested_trading_days == 5
    assert manifest.acquired_complete_trading_days == 4
    assert manifest.unavailable_dates == (date(2026, 9, 7),)
    assert manifest.retention_boundary_observed is True
    assert manifest.minimum_dataset_requirement_met is False
    assert manifest.trading_dates == (
        date(2026, 9, 8),
        date(2026, 9, 9),
        date(2026, 9, 10),
        date(2026, 9, 11),
    )
    assert manifest.complete_trading_days == 4
    assert {capture.requested_limit for capture in manifest.source_captures} == {165, 190}


def test_extension_preserves_parent_and_atomically_publishes_five_day_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)

    parent = probe_module.download(
        "S50U26",
        interval="1m",
        start=date(2026, 9, 8),
        end=date(2026, 9, 11),
        environment="prod",
        interim_real_dataset=True,
        unavailable_dates=(date(2026, 9, 7),),
    )
    parent_sha256 = file_sha256(parent.normalized_file)
    parent_bytes = parent.normalized_file.read_bytes()
    parent_manifest_bytes = parent.manifest_file.read_bytes()
    parent_raw_hashes = {
        path: file_sha256(path) for path in parent.raw_directory.glob("*.settrade.json")
    }

    result = probe_module.extend_download(
        "S50U26",
        interval="1m",
        trading_date=date(2026, 9, 14),
        environment="prod",
        parent_file=parent.normalized_file,
        parent_sha256=parent_sha256,
    )

    assert result.candlestick_requests == 2
    assert len(requests) == 10
    assert [(request["start"], request["end"]) for request in requests[-2:]] == [
        ("2026-09-14T09:45", "2026-09-14T12:30"),
        ("2026-09-14T13:45", "2026-09-14T16:55"),
    ]
    assert [request["limit"] for request in requests[-2:]] == [165, 190]
    assert all(request["normalized"] is False for request in requests[-2:])
    assert auto_queue_values == [True, True]
    assert parent.normalized_file.read_bytes() == parent_bytes
    assert parent.manifest_file.read_bytes() == parent_manifest_bytes
    assert file_sha256(parent.normalized_file) == parent_sha256
    assert {path: file_sha256(path) for path in parent_raw_hashes} == parent_raw_hashes

    manifest = load_manifest(result.normalized_file)
    assert result.normalized_file.name == "S50U26_1m_2026-09-08_2026-09-14.csv"
    assert result.raw_directory.name == "s50u26-1m-20260914-settrade-extension"
    assert len(list(result.raw_directory.glob("*.settrade.json"))) == 2
    assert manifest.dataset_id == "s50u26-1m-20260908-20260914-settrade-extended"
    assert manifest.parent_dataset_id == "s50u26-1m-20260908-20260911-settrade-interim"
    assert manifest.parent_normalized_sha256 == parent_sha256
    assert manifest.record_count == 1775
    assert manifest.trading_dates == (
        date(2026, 9, 8),
        date(2026, 9, 9),
        date(2026, 9, 10),
        date(2026, 9, 11),
        date(2026, 9, 14),
    )
    assert manifest.trading_days == 5
    assert manifest.complete_trading_days == 5
    assert manifest.acquired_complete_trading_days == 5
    assert manifest.minimum_dataset_requirement_met is True
    assert manifest.requested_trading_days == 6
    assert manifest.unavailable_dates == (date(2026, 9, 7),)
    assert manifest.retention_boundary_observed is True
    assert manifest.validation_status == "PASS"
    assert manifest.validator_version == "tfex-market-data-validator/1"
    assert len(manifest.source_captures) == 10
    assert manifest.source_raw_capture_sha256s == tuple(
        capture.sha256 for capture in manifest.source_captures
    )
    assert manifest.new_raw_capture_sha256s == tuple(
        capture.sha256 for capture in manifest.source_captures[-2:]
    )
    assert set(manifest.new_raw_capture_sha256s).isdisjoint(
        manifest.source_raw_capture_sha256s[:-2]
    )

    loaded, report = probe_module._validate_normalized_dataset(result.normalized_file, manifest)
    assert len(loaded.bars) == 1775
    assert report.outcome.value == "PASS"
    assert {bar.trading_date for bar in loaded.bars} == set(manifest.trading_dates)


def test_extension_failure_leaves_validated_parent_and_all_new_targets_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)

    parent = probe_module.download(
        "S50U26",
        interval="1m",
        start=date(2026, 9, 8),
        end=date(2026, 9, 11),
        environment="prod",
        interim_real_dataset=True,
        unavailable_dates=(date(2026, 9, 7),),
    )
    parent_sha256 = file_sha256(parent.normalized_file)
    parent_files = {
        path: file_sha256(path)
        for path in (
            parent.normalized_file,
            parent.manifest_file,
            *parent.raw_directory.glob("*.settrade.json"),
        )
    }

    def fail_merged_write(path: Path, rows: list[dict[str, Any]]) -> None:
        del path, rows
        raise OSError("simulated atomic merge failure")

    monkeypatch.setattr(probe_module, "_write_normalized_csv", fail_merged_write)
    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module.extend_download(
            "S50U26",
            interval="1m",
            trading_date=date(2026, 9, 14),
            environment="prod",
            parent_file=parent.normalized_file,
            parent_sha256=parent_sha256,
        )

    assert caught.value.diagnostic["acquisition_stage"] == "file_write"
    assert len(requests) == 10
    assert {path: file_sha256(path) for path in parent_files} == parent_files
    assert not (normalized_root / "S50U26" / "S50U26_1m_2026-09-08_2026-09-14.csv").exists()
    assert not (raw_root / "S50U26" / "s50u26-1m-20260914-settrade-extension").exists()


def test_extension_rejects_parent_checksum_before_sdk_or_api_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", tmp_path / "normalized")
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)
    parent = probe_module.download(
        "S50U26",
        interval="1m",
        start=date(2026, 9, 8),
        end=date(2026, 9, 11),
        environment="prod",
        interim_real_dataset=True,
        unavailable_dates=(date(2026, 9, 7),),
    )
    api_calls_before = len(requests)

    with pytest.raises(ValueError, match="required SHA-256"):
        probe_module.extend_download(
            "S50U26",
            interval="1m",
            trading_date=date(2026, 9, 14),
            environment="prod",
            parent_file=parent.normalized_file,
            parent_sha256="0" * 64,
        )

    assert len(requests) == api_calls_before


def test_four_day_range_requires_explicit_interim_mode_before_any_api_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="5-10 complete TFEX trading days"):
        probe_module.download(
            "S50U26",
            interval="1m",
            start=date(2026, 9, 8),
            end=date(2026, 9, 11),
            environment="prod",
        )

    assert events == []
    assert requests == []


def test_download_requires_matching_ready_probe_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    evidence_path = _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["decision"] = probe_module.SETTRADE_PROBE_FAILED
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", tmp_path / "normalized")

    with pytest.raises(ValueError, match="does not confirm"):
        probe_module.download(
            "S50U26",
            interval="1m",
            start=date(2026, 9, 7),
            end=date(2026, 9, 11),
            environment="prod",
        )

    assert events == []
    assert requests == []


def _candlestick_response(start: datetime, count: int) -> dict[str, Any]:
    times = [int((start + timedelta(minutes=index)).timestamp()) for index in range(count)]
    return {
        "time": times,
        "open": [1000.0] * count,
        "high": [1000.2] * count,
        "low": [999.8] * count,
        "close": [1000.1] * count,
        "volume": [10] * count,
        "value": [10001.0] * count,
        "lastSequence": 123,
    }


def test_official_candlestick_parallel_array_shape_and_optional_fields() -> None:
    response = _candlestick_response(
        datetime(2026, 9, 11, 9, 45, tzinfo=ZoneInfo("Asia/Bangkok")),
        2,
    )
    response["partialOptional"] = [1]

    rows = probe_module._rows_from_response(response)
    minimal_rows = probe_module._rows_from_response(
        {key: response[key] for key in ("time", "open", "high", "low", "close", "volume")}
    )
    schema = probe_module._response_schema_summary(response)

    assert len(rows) == 2
    assert rows[0]["value"] == 10001.0
    assert "lastSequence" not in rows[0]
    assert "partialOptional" not in rows[0]
    assert len(minimal_rows) == 2
    assert schema["field_lengths"] == {
        "close": 2,
        "high": 2,
        "low": 2,
        "open": 2,
        "partialOptional": 1,
        "time": 2,
        "value": 2,
        "volume": 2,
    }
    assert schema["field_types"]["lastSequence"] == "int"
    assert schema["returned_bars"] == 2


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (
            {"time": [], "open": [], "high": [], "low": [], "close": []},
            "RESPONSE_SCHEMA_INVALID",
        ),
        (
            {
                "time": [1],
                "open": [1],
                "high": [1],
                "low": [1],
                "close": [1],
                "volume": 1,
            },
            "RESPONSE_SCHEMA_INVALID",
        ),
        (
            {
                "time": [1, 2],
                "open": [1],
                "high": [1],
                "low": [1],
                "close": [1],
                "volume": [1],
            },
            "RESPONSE_FIELD_LENGTH_MISMATCH",
        ),
    ],
)
def test_invalid_response_schemas_are_distinguished(
    response: dict[str, Any],
    category: str,
) -> None:
    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module._rows_from_response(response)

    assert caught.value.diagnostic["acquisition_stage"] == "response_validation"
    assert caught.value.diagnostic["exception_category"] == category
    assert "response_schema" in caught.value.diagnostic


def test_complete_and_truncated_session_detection() -> None:
    window = probe_module._download_windows(
        "S50U26",
        start=date(2026, 9, 11),
        end=date(2026, 9, 11),
        request_limit=200,
        enforce_initial_range=False,
    )[0]
    complete = _candlestick_response(window.start, window.expected_bar_slots)

    rows = probe_module._normalized_rows(
        "S50U26",
        [(window, complete, window.expected_bar_slots)],
    )

    assert len(rows) == 165
    truncated = _candlestick_response(window.start, 100)
    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module._normalized_rows("S50U26", [(window, truncated, 100)])
    assert caught.value.diagnostic["exception_category"] == "SESSION_TRUNCATED"

    off_grid = _candlestick_response(window.start, window.expected_bar_slots)
    off_grid["time"][50] += 30
    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module._normalized_rows("S50U26", [(window, off_grid, window.expected_bar_slots)])
    assert caught.value.diagnostic["exception_category"] == "SESSION_GRID_MISMATCH"


def test_close_boundary_bar_is_rejected_as_session_overflow() -> None:
    window = probe_module._download_windows(
        "S50U26",
        start=date(2026, 9, 11),
        end=date(2026, 9, 11),
        request_limit=200,
        enforce_initial_range=False,
    )[0]
    inclusive = _candlestick_response(window.start, window.expected_bar_slots + 1)

    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module._normalized_rows("S50U26", [(window, inclusive, 200)])

    assert caught.value.diagnostic["exception_category"] == "SESSION_SLOT_OVERFLOW"
    assert caught.value.diagnostic["response_schema"]["returned_bars"] == 166


@pytest.mark.parametrize(
    ("response_kind", "expected_category"),
    [
        ("empty", "SESSION_EMPTY"),
        ("invalid_timestamp", "TIMESTAMP_INVALID"),
        ("outside_session", "TIMESTAMP_OUTSIDE_SESSION"),
    ],
)
def test_session_response_invariants_have_distinct_diagnostics(
    response_kind: str,
    expected_category: str,
) -> None:
    window = probe_module._download_windows(
        "S50U26",
        start=date(2026, 9, 11),
        end=date(2026, 9, 11),
        request_limit=200,
        enforce_initial_range=False,
    )[0]
    if response_kind == "empty":
        response = _candlestick_response(window.start, 0)
    elif response_kind == "invalid_timestamp":
        response = _candlestick_response(window.start, 1)
        response["time"] = ["not-a-timestamp"]
    else:
        response = _candlestick_response(window.start - timedelta(minutes=1), 1)

    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module._normalized_rows("S50U26", [(window, response, 200)])

    assert caught.value.diagnostic["exception_category"] == expected_category
    assert caught.value.diagnostic["session"] == "morning"
    assert caught.value.diagnostic["response_schema"]["returned_bars"] in {0, 1}


def test_one_session_diagnostic_makes_one_request_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requests: list[dict[str, Any]] = []

    def get_candlestick(**parameters: Any) -> dict[str, Any]:
        requests.append(parameters)
        start = datetime.strptime(parameters["start"], "%Y-%m-%dT%H:%M").replace(
            tzinfo=ZoneInfo("Asia/Bangkok")
        )
        return _candlestick_response(start, 165)

    monkeypatch.setattr(
        probe_module,
        "_acquisition_client",
        lambda *args, **kwargs: (
            SimpleNamespace(version="2.2.1"),
            get_candlestick,
            dict(SECRET_VALUES),
        ),
    )
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", tmp_path / "normalized")

    diagnostic = probe_module.diagnose_session(
        "S50U26",
        interval="1m",
        trading_date=date(2026, 9, 11),
        session="morning",
        environment="prod",
        request_limit=200,
    )

    assert len(requests) == 1
    assert requests[0]["start"] == "2026-09-11T09:45"
    assert requests[0]["end"] == "2026-09-11T12:30"
    assert requests[0]["limit"] == 200
    assert diagnostic["returned_bars"] == 165
    assert diagnostic["complete_half_open_boundaries"] is True
    assert diagnostic["files_written"] is False
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "normalized").exists()


def test_session_diagnostic_redacts_api_credentials_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    extra_secrets = ("live-access-token", "session-cookie", "1234567890")
    error = FakeApiError(
        status_code=500,
        code=f"SERVER_ERROR app_id={SECRET_VALUES['SETTRADE_APP_ID']}",
        message=(
            f"Authorization: Bearer {extra_secrets[0]} Cookie={extra_secrets[1]} "
            f"accountNo={extra_secrets[2]} " + " ".join(SECRET_VALUES.values())
        ),
    )
    _install_fake_sdk(monkeypatch, _failing_market_investor(error))
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)

    exit_code = probe_module.main(
        [
            "--symbol",
            "S50U26",
            "--start",
            "2026-09-11",
            "--diagnose-session",
            "morning",
            "--limit",
            "200",
        ]
    )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert exit_code == 1
    assert all(secret not in output for secret in SECRET_VALUES.values())
    assert all(secret not in output for secret in extra_secrets)
    assert "SETTRADE_API_ERROR" in output
    assert "api_status_code" in output
    assert "[REDACTED]" in output


@pytest.mark.parametrize(
    ("failure_stage", "expected_stage", "expected_category"),
    [
        ("file_write", "file_write", "LOCAL_FILESYSTEM_ERROR"),
        (
            "normalization_validation",
            "normalization_validation",
            "NORMALIZATION_VALIDATION_FAILED",
        ),
        ("manifest", "manifest", "MANIFEST_PROVENANCE_FAILED"),
    ],
)
def test_local_failures_leave_no_publishable_partial_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
    expected_stage: str,
    expected_category: str,
) -> None:
    events: list[str] = []
    requests: list[dict[str, Any]] = []
    auto_queue_values: list[bool] = []
    _install_fake_sdk(
        monkeypatch,
        _download_investor(events, requests, auto_queue_values),
    )
    _set_credentials(monkeypatch)
    _set_ready_acquisition_evidence(monkeypatch, tmp_path)
    raw_root = tmp_path / "raw"
    normalized_root = tmp_path / "normalized"
    monkeypatch.setattr(probe_module, "HISTORICAL_RAW_ROOT", raw_root)
    monkeypatch.setattr(probe_module, "HISTORICAL_NORMALIZED_ROOT", normalized_root)
    monkeypatch.setattr(probe_module, "sleep", lambda _: None)

    if failure_stage == "file_write":

        def fail_write(path: Path, rows: list[dict[str, Any]]) -> None:
            del path, rows
            raise OSError("diagnostic filesystem failure")

        monkeypatch.setattr(probe_module, "_write_normalized_csv", fail_write)
    elif failure_stage == "normalization_validation":

        def fail_load(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise RuntimeError("diagnostic normalization failure")

        monkeypatch.setattr(probe_module, "load_bars", fail_load)
    else:

        def fail_manifest(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise RuntimeError("diagnostic manifest failure")

        monkeypatch.setattr(probe_module, "build_manifest", fail_manifest)

    with pytest.raises(probe_module.AcquisitionFailure) as caught:
        probe_module.download(
            "S50U26",
            interval="1m",
            start=date(2026, 9, 7),
            end=date(2026, 9, 11),
            environment="prod",
            request_limit=200,
            request_delay_seconds=1.0,
        )

    assert caught.value.diagnostic["acquisition_stage"] == expected_stage
    assert caught.value.diagnostic["exception_category"] == expected_category
    assert not raw_root.exists()
    assert not normalized_root.exists()


def test_response_schema_summary_redacts_sensitive_field_names() -> None:
    schema = probe_module._response_schema_summary(
        {
            "time": [1],
            "Authorization": [SECRET_VALUES["SETTRADE_APP_SECRET"]],
            "access_token": SECRET_VALUES["SETTRADE_APP_ID"],
        }
    )
    serialized = json.dumps(schema)

    assert "Authorization" not in serialized
    assert "access_token" not in serialized
    assert all(secret not in serialized for secret in SECRET_VALUES.values())
    assert "[REDACTED_SENSITIVE_FIELD]" in serialized


def test_missing_credentials_stop_before_investor_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_fake_sdk(monkeypatch, _successful_investor(events))
    _clear_credentials(monkeypatch)

    evidence = probe_module.probe("S50U26", environment="prod")

    assert evidence["decision"] == probe_module.SETTRADE_AUTH_REQUIRED
    assert evidence["api_request_attempted"] is False
    assert events == []


def test_incompatible_investor_signature_is_not_a_symbol_or_entitlement_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IncompatibleInvestor:
        def __init__(self, app_id: str) -> None:
            del app_id

    _install_fake_sdk(monkeypatch, IncompatibleInvestor)
    _set_credentials(monkeypatch)

    evidence = probe_module.probe("S50U26", environment="prod")

    assert evidence["decision"] == probe_module.SETTRADE_SDK_API_INCOMPATIBLE
    assert evidence["sdk_compatible"] is False
    assert evidence["raw_contract_symbol_supported"] == "UNKNOWN"
    assert evidence["derivatives_market_data_entitlement"] == "UNKNOWN"
    assert evidence["api_request_attempted"] is False


def test_constructor_type_error_is_an_sdk_failure_not_market_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenInvestor:
        def __init__(
            self,
            app_id: str,
            app_secret: str,
            app_code: str,
            broker_id: str,
            is_auto_queue: bool = False,
        ) -> None:
            del app_id, app_secret, app_code, broker_id, is_auto_queue
            raise TypeError("local constructor failure")

    _install_fake_sdk(monkeypatch, BrokenInvestor)
    _set_credentials(monkeypatch)

    evidence = probe_module.probe("S50U26", environment="prod")

    assert evidence["decision"] == probe_module.SETTRADE_SDK_API_INCOMPATIBLE
    assert evidence["raw_contract_symbol_supported"] == "UNKNOWN"
    assert evidence["derivatives_market_data_entitlement"] == "UNKNOWN"
    assert evidence["authentication"] == "NOT_ATTEMPTED"


@pytest.mark.parametrize(
    ("error", "expected_decision", "field", "value", "expected_authentication"),
    [
        (
            FakeApiError(status_code=401, code="UNAUTHORIZED", message="authentication failed"),
            probe_module.SETTRADE_AUTH_REQUIRED,
            "authentication",
            "REJECTED",
            "REJECTED",
        ),
        (
            FakeApiError(status_code=403, code="FORBIDDEN", message="access denied"),
            probe_module.SETTRADE_DERIVATIVES_ENTITLEMENT_MISSING,
            "derivatives_market_data_entitlement",
            "DENIED",
            "CONFIRMED",
        ),
        (
            FakeApiError(status_code=400, code="INVALID_SYMBOL", message="invalid symbol"),
            probe_module.SETTRADE_SYMBOL_INVALID,
            "raw_contract_symbol_supported",
            "REJECTED_BY_API",
            "CONFIRMED",
        ),
        (
            FakeApiError(status_code=400, code="INVALID_INTERVAL", message="invalid interval"),
            probe_module.SETTRADE_INTERVAL_INVALID,
            "one_minute_interval_supported",
            "REJECTED_BY_API",
            "CONFIRMED",
        ),
        (
            FakeApiError(
                status_code=400,
                code="INVALID_DATE_RANGE",
                message="invalid start datetime format",
            ),
            probe_module.SETTRADE_DATE_RANGE_INVALID,
            "raw_contract_symbol_supported",
            "UNKNOWN",
            "CONFIRMED",
        ),
        (
            FakeApiError(status_code=400, code="BAD_REQUEST", message="bad request"),
            probe_module.SETTRADE_REQUEST_INVALID,
            "raw_contract_symbol_supported",
            "UNKNOWN",
            "CONFIRMED",
        ),
        (
            FakeApiError(status_code=500, code="SERVER_ERROR", message="server unavailable"),
            probe_module.SETTRADE_PROBE_FAILED,
            "raw_contract_symbol_supported",
            "UNKNOWN",
            "CONFIRMED",
        ),
    ],
)
def test_api_failures_remain_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
    error: FakeApiError,
    expected_decision: str,
    field: str,
    value: str,
    expected_authentication: str,
) -> None:
    _install_fake_sdk(monkeypatch, _failing_market_investor(error))
    _set_credentials(monkeypatch)

    evidence = probe_module.probe(
        "S50U26",
        environment="prod",
        start="2026-09-11T09:45",
        end="2026-09-11T09:50",
    )

    assert evidence["decision"] == expected_decision
    assert evidence[field] == value
    assert evidence["sdk_compatible"] is True
    assert evidence["authentication"] == expected_authentication
    assert evidence["api_request_attempted"] is True
    assert evidence["api_error_code"] == error.code
    assert evidence["api_error_message"] == str(error)


def test_third_party_error_text_is_redacted_from_output_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    extra_secrets = ("live-access-token", "session-cookie", "1234567890")
    secret_message = (
        f"Authorization: Bearer {extra_secrets[0]} Cookie={extra_secrets[1]} "
        f"accountNo={extra_secrets[2]} " + " ".join(SECRET_VALUES.values())
    )
    error = FakeApiError(
        status_code=500,
        code=f"SERVER_ERROR app_id={SECRET_VALUES['SETTRADE_APP_ID']}",
        message=secret_message,
    )
    _install_fake_sdk(monkeypatch, _failing_market_investor(error))
    _set_credentials(monkeypatch)
    evidence_path = tmp_path / "settrade_capability.json"
    monkeypatch.setattr(probe_module, "EVIDENCE_PATH", evidence_path)

    exit_code = probe_module.main(["--probe", "--symbol", "S50U26"])

    output = capsys.readouterr()
    combined = output.out + output.err + evidence_path.read_text(encoding="utf-8")
    assert exit_code == 3
    assert all(secret not in combined for secret in SECRET_VALUES.values())
    assert all(secret not in combined for secret in extra_secrets)
    assert "sanitized API fields recorded" in combined
    assert "[REDACTED]" in combined
