"""SET50 futures symbol parsing (`CLAUDE_TFEX.md` section 5)."""

from __future__ import annotations

from datetime import date

import pytest

from app.tfex.config import TfexConfig, default_config
from app.tfex.contracts.symbol_parser import (
    MONTH_CODES,
    ParsedContractSymbol,
    format_symbol,
    month_code_for,
    parse_symbol,
    resolve_two_digit_year,
)
from app.tfex.errors import SymbolParseError

REFERENCE = date(2026, 8, 23)


def parse(raw: str, config: TfexConfig, *, reference: date = REFERENCE) -> ParsedContractSymbol:
    return parse_symbol(raw, config=config, reference_date=reference)


def test_a_well_formed_symbol_parses(config: TfexConfig) -> None:
    parsed = parse("S50Z26", config)

    assert parsed.raw == "S50Z26"
    assert parsed.normalized == "S50Z26"
    assert parsed.root == "S50"
    assert parsed.month_code == "Z"
    assert parsed.year_2digit == 26
    assert parsed.contract_year == 2026
    assert parsed.contract_month == 12
    assert parsed.reference_date == REFERENCE
    assert str(parsed) == "S50Z26"


def test_the_raw_symbol_is_preserved_exactly(config: TfexConfig) -> None:
    """Section 30 requires datasets to preserve contract identity, raw symbol included."""
    parsed = parse("  s50z26 ", config)
    assert parsed.raw == "  s50z26 "
    assert parsed.normalized == "S50Z26"


@pytest.mark.parametrize(("code", "month"), sorted(MONTH_CODES.items()))
def test_all_twelve_month_codes_are_valid(config: TfexConfig, code: str, month: int) -> None:
    """Section 5: SET50 futures list consecutive months, so quarterly-only is wrong."""
    parsed = parse(f"S50{code}26", config)
    assert parsed.contract_month == month


def test_non_quarterly_months_are_accepted(config: TfexConfig) -> None:
    for symbol, month in (("S50F26", 1), ("S50G26", 2), ("S50J26", 4), ("S50K26", 5)):
        assert parse(symbol, config).contract_month == month


@pytest.mark.parametrize(
    ("symbol", "problem"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("S50", "month code"),
        ("S50Z", "month code"),
        ("S50Z2026", "month code"),
        ("S50Z2", "month code"),
        ("S50I26", "not a futures month code"),
        ("S50A26", "not a futures month code"),
        ("S50ZX6", "non-numeric"),
        ("SET50Z26", "does not start with"),
        ("S51Z26", "does not start with"),
        ("XYZZ26", "does not start with"),
        ("S50 Z26", "whitespace"),
    ],
)
def test_malformed_symbols_are_rejected(config: TfexConfig, symbol: str, problem: str) -> None:
    with pytest.raises(SymbolParseError, match=problem):
        parse(symbol, config)


def test_a_contract_year_before_the_earliest_listing_is_rejected(config: TfexConfig) -> None:
    with pytest.raises(SymbolParseError, match="before the configured earliest listed year"):
        parse("S50Z05", config, reference=date(2006, 6, 1))


def test_a_contract_year_too_far_ahead_is_rejected(config: TfexConfig) -> None:
    with pytest.raises(SymbolParseError, match="more than 3 year"):
        parse("S50Z30", config, reference=date(2026, 8, 23))


# --- two-digit year resolution ---------------------------------------------------------


def test_two_digit_years_resolve_against_the_reference_not_today() -> None:
    """A 2019 symbol must still parse as 2019 when replayed in 2031."""
    assert resolve_two_digit_year(19, 2019) == 2019
    assert resolve_two_digit_year(19, 2031) == 2019
    assert resolve_two_digit_year(19, 2065) == 2019


def test_the_pivot_window_is_centred_on_the_reference_year() -> None:
    assert resolve_two_digit_year(99, 2026) == 1999
    assert resolve_two_digit_year(1, 1999) == 2001
    assert resolve_two_digit_year(26, 2026) == 2026


def test_parsing_the_same_symbol_at_different_reference_dates_is_stable(
    config: TfexConfig,
) -> None:
    first = parse("S50H24", config, reference=date(2024, 1, 15))
    second = parse("S50H24", config, reference=date(2026, 8, 23))
    assert first.contract_year == second.contract_year == 2024
    assert first.contract_month_key == second.contract_month_key


def test_an_out_of_range_two_digit_year_is_rejected() -> None:
    with pytest.raises(SymbolParseError, match="out of range"):
        resolve_two_digit_year(100, 2026)


# --- formatting ------------------------------------------------------------------------


def test_format_symbol_round_trips(config: TfexConfig) -> None:
    for month in range(1, 13):
        symbol = format_symbol("S50", 2026, month)
        parsed = parse(symbol, config)
        assert (parsed.contract_year, parsed.contract_month) == (2026, month)


def test_month_code_for_rejects_a_non_month() -> None:
    with pytest.raises(SymbolParseError, match="not a calendar month"):
        month_code_for(13)


# --- the parser stays out of the calendar's job -----------------------------------------


def test_parsing_says_nothing_about_expiry_or_status(config: TfexConfig) -> None:
    """Section 5: never guess the active contract without registry data."""
    parsed = parse("S50Z26", config)
    assert not hasattr(parsed, "status")
    assert not hasattr(parsed, "expiry_date")
    assert not hasattr(parsed, "days_to_expiry")


def test_the_configured_root_is_enforced() -> None:
    config = default_config()
    with pytest.raises(SymbolParseError, match="SET50 index futures only"):
        parse_symbol("S5Z26", config=config, reference_date=REFERENCE)
