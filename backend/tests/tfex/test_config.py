"""Configuration validation (`CLAUDE_TFEX.md` sections 3, 9 and 32)."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path

import pytest

from app.tfex.config import (
    DEFAULT_CONFIG_PATH,
    ContractConfig,
    SessionsConfig,
    TfexConfig,
    TimeWindow,
    TradingConfig,
    default_config,
    load_config,
)
from app.tfex.errors import ConfigurationError, LiveTradingDisabledError


def test_shipped_yaml_loads_and_matches_the_contract_specification() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)

    assert config.market.exchange == "TFEX"
    assert config.market.timezone == "Asia/Bangkok"
    assert config.market.symbol_root == "S50"
    assert config.contract.point_value_thb == Decimal("200")
    assert config.contract.tick_size_points == Decimal("0.1")
    assert config.contract.tick_value_thb == Decimal("20")
    assert config.contract.price_limit_percent == Decimal("30")


def test_tick_size_is_read_as_an_exact_decimal_not_a_float() -> None:
    """YAML 0.1 must not become 0.1000000000000000055; position sizing depends on it."""
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.contract.tick_size_points == Decimal("0.1")
    assert config.contract.tick_size_points * config.contract.point_value_thb == Decimal("20")


def test_inconsistent_tick_arithmetic_is_rejected() -> None:
    with pytest.raises(ValueError, match="contradicts tick_value_thb"):
        ContractConfig(tick_value_thb=Decimal("25"))


def test_default_session_boundaries_match_section_9() -> None:
    sessions = default_config().sessions
    assert (sessions.morning_preopen.start, sessions.morning_preopen.end) == (
        time(9, 15),
        time(9, 45),
    )
    assert (sessions.morning.start, sessions.morning.end) == (time(9, 45), time(12, 30))
    assert (sessions.midday_break.start, sessions.midday_break.end) == (time(12, 30), time(13, 45))
    assert (sessions.afternoon_preopen.start, sessions.afternoon_preopen.end) == (
        time(13, 15),
        time(13, 45),
    )
    assert (sessions.afternoon.start, sessions.afternoon.end) == (time(13, 45), time(16, 55))


def test_midday_break_and_afternoon_preopen_overlap_is_required_not_tolerated() -> None:
    """Section 9 calls the overlap intentional, so a non-overlapping config is the error."""
    with pytest.raises(ValueError, match="must begin inside the midday break"):
        SessionsConfig(
            morning_preopen=TimeWindow(start=time(9, 15), end=time(9, 45)),
            morning=TimeWindow(start=time(9, 45), end=time(12, 30)),
            midday_break=TimeWindow(start=time(12, 30), end=time(13, 45)),
            afternoon_preopen=TimeWindow(start=time(12, 0), end=time(13, 45)),
            afternoon=TimeWindow(start=time(13, 45), end=time(16, 55)),
        )


def test_session_phases_must_chain_without_gaps() -> None:
    with pytest.raises(ValueError, match="midday break must start exactly"):
        SessionsConfig(
            morning_preopen=TimeWindow(start=time(9, 15), end=time(9, 45)),
            morning=TimeWindow(start=time(9, 45), end=time(12, 0)),
            midday_break=TimeWindow(start=time(12, 30), end=time(13, 45)),
            afternoon_preopen=TimeWindow(start=time(13, 15), end=time(13, 45)),
            afternoon=TimeWindow(start=time(13, 45), end=time(16, 55)),
        )


def test_time_window_rejects_a_reversed_interval() -> None:
    with pytest.raises(ValueError, match="must be before end"):
        TimeWindow(start=time(13, 0), end=time(12, 0))


def test_enabling_live_orders_is_refused() -> None:
    """CLAUDE.md mandates paper by default; section 32 forbids real orders in this build."""
    with pytest.raises(LiveTradingDisabledError):
        TradingConfig(live_orders_enabled=True)


def test_live_orders_cannot_be_enabled_through_the_yaml_file(tmp_path: Path) -> None:
    source = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    tampered = source.replace("live_orders_enabled: false", "live_orders_enabled: true")
    assert tampered != source

    path = tmp_path / "tfex.yaml"
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(LiveTradingDisabledError):
        load_config(path)


def test_last_trading_day_cutoff_must_precede_cessation() -> None:
    base = default_config()
    with pytest.raises(ValueError, match="must be before cessation"):
        TfexConfig(
            sessions=base.sessions,
            roll=base.roll.model_copy(
                update={"prevent_new_positions_on_last_trading_day_after": time(16, 45)}
            ),
        )


def test_unknown_configuration_keys_are_rejected(tmp_path: Path) -> None:
    """A misspelt key must fail loudly rather than silently keeping the default."""
    path = tmp_path / "tfex.yaml"
    path.write_text(
        DEFAULT_CONFIG_PATH.read_text(encoding="utf-8") + "\nunexpected_section:\n  a: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_missing_configuration_file_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot read TFEX configuration"):
        load_config(tmp_path / "absent.yaml")


def test_configuration_is_immutable() -> None:
    config = default_config()
    with pytest.raises(ValueError, match="frozen"):
        config.contract.point_value_thb = Decimal("100")  # type: ignore[misc]
