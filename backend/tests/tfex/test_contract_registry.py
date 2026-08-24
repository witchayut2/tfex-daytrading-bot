"""The contract registry (`CLAUDE_TFEX.md` sections 5 and 6)."""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.contracts.metadata import ContractStatus
from app.tfex.contracts.registry import ContractMarketState, ContractRegistry
from app.tfex.errors import (
    ContractNotEligibleError,
    ContractNotFoundError,
    NoEligibleContractError,
    SymbolParseError,
)
from app.tfex.provenance import Provenance
from tests.tfex.conftest import BANGKOK, bkk

# S50Z26 last trades on Tue 29 Dec 2026 (31 Dec is a fixture holiday).
DEC_1 = bkk(date(2026, 12, 1), time(10, 0))
DEC_24 = bkk(date(2026, 12, 24), time(10, 0))
DEC_25 = bkk(date(2026, 12, 25), time(10, 0))
DEC_28 = bkk(date(2026, 12, 28), time(10, 0))
LTD_MORNING = bkk(date(2026, 12, 29), time(10, 0))
LTD_AFTER_CESSATION = bkk(date(2026, 12, 29), time(16, 30))
AFTER_EXPIRY = bkk(date(2026, 12, 30), time(10, 0))


def test_registering_a_symbol_parses_and_stores_it(registry: ContractRegistry) -> None:
    assert len(registry) == 2
    assert "S50Z26" in registry
    record = registry.record("s50z26")
    assert record.normalized_symbol == "S50Z26"
    assert record.parsed.contract_month_key == (2026, 12)


def test_registering_a_malformed_symbol_is_refused(
    config: TfexConfig, calendar: TradingCalendar, provenance: Provenance
) -> None:
    registry = ContractRegistry(config, calendar)
    with pytest.raises(SymbolParseError):
        registry.register_symbol("S50Q", reference_date=date(2026, 12, 1), provenance=provenance)
    assert len(registry) == 0


def test_an_unregistered_symbol_raises_rather_than_being_invented(
    registry: ContractRegistry,
) -> None:
    with pytest.raises(ContractNotFoundError, match="no contract registered"):
        registry.record("S50M27")


def test_resolution_fills_in_expiry_from_the_calendar(registry: ContractRegistry) -> None:
    contract = registry.resolve("S50Z26", as_of=DEC_1)

    assert contract.last_trading_date == date(2026, 12, 29)
    assert contract.last_trading_timestamp == datetime(2026, 12, 29, 16, 30, tzinfo=BANGKOK)
    assert contract.expiry_date == date(2026, 12, 29)
    assert contract.status is ContractStatus.ACTIVE
    assert contract.normalized_symbol == "S50Z26"
    assert contract.raw_symbol == "S50Z26"


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (DEC_1, ContractStatus.ACTIVE),
        (DEC_24, ContractStatus.ACTIVE),  # 25, 28, 29 remain -> 3 trading days
        (DEC_25, ContractStatus.ROLL_CANDIDATE),  # 28, 29 remain -> at the cutoff
        (DEC_28, ContractStatus.ROLL_CANDIDATE),
        (LTD_MORNING, ContractStatus.LAST_TRADING_DAY),
        (LTD_AFTER_CESSATION, ContractStatus.EXPIRED),
        (AFTER_EXPIRY, ContractStatus.EXPIRED),
    ],
)
def test_status_tracks_the_instant_it_is_asked_about(
    registry: ContractRegistry, as_of: datetime, expected: ContractStatus
) -> None:
    assert registry.resolve("S50Z26", as_of=as_of).status is expected


@pytest.mark.anti_repaint
def test_status_is_never_cached_across_instants(registry: ContractRegistry) -> None:
    """A cached ACTIVE would let a replay see a contract as tradable on a day it was not."""
    early = registry.resolve("S50Z26", as_of=DEC_1)
    late = registry.resolve("S50Z26", as_of=AFTER_EXPIRY)
    again = registry.resolve("S50Z26", as_of=DEC_1)

    assert early.status is ContractStatus.ACTIVE
    assert late.status is ContractStatus.EXPIRED
    assert again.status is ContractStatus.ACTIVE


def test_a_contract_before_its_listing_date_is_pre_listed(registry: ContractRegistry) -> None:
    contract = registry.resolve("S50H27", as_of=bkk(date(2026, 2, 2), time(10, 0)))
    assert contract.status is ContractStatus.PRE_LISTED


def test_days_to_expiry_is_reported_in_both_units(registry: ContractRegistry) -> None:
    contract = registry.resolve("S50Z26", as_of=DEC_24)
    assert contract.days_to_expiry == 5
    assert contract.trading_days_to_expiry == 3


# --- eligibility --------------------------------------------------------------------------


def test_a_contract_inside_the_expiry_cutoff_is_not_eligible(registry: ContractRegistry) -> None:
    result = registry.eligibility("S50Z26", as_of=DEC_28)

    assert not result.eligible
    assert any("below the cutoff" in reason for reason in result.reasons)


def test_an_expired_contract_is_not_eligible(registry: ContractRegistry) -> None:
    result = registry.eligibility("S50Z26", as_of=AFTER_EXPIRY)
    assert not result.eligible
    assert any("status is EXPIRED" in reason for reason in result.reasons)


def test_validate_order_symbol_refuses_an_expired_contract(registry: ContractRegistry) -> None:
    with pytest.raises(ContractNotEligibleError, match="not eligible for orders"):
        registry.validate_order_symbol("S50Z26", as_of=AFTER_EXPIRY)


def test_validate_order_symbol_accepts_an_active_contract(registry: ContractRegistry) -> None:
    contract = registry.validate_order_symbol("S50Z26", as_of=DEC_1)
    assert contract.status is ContractStatus.ACTIVE


def test_stale_contract_metadata_makes_a_contract_ineligible(
    config: TfexConfig, calendar: TradingCalendar
) -> None:
    registry = ContractRegistry(config, calendar)
    registry.register_symbol(
        "S50Z26",
        reference_date=date(2026, 12, 1),
        provenance=Provenance(
            source_name="fixture",
            retrieved_at=datetime(2020, 1, 1, tzinfo=BANGKOK),
            stale_after=datetime(2020, 7, 1, tzinfo=BANGKOK),
        ),
    )
    result = registry.eligibility("S50Z26", as_of=DEC_1)

    assert not result.eligible
    assert any("metadata unusable" in reason for reason in result.reasons)


def test_requiring_published_expiry_dates_makes_derived_ones_ineligible(
    calendar: TradingCalendar, config: TfexConfig, provenance: Provenance
) -> None:
    strict = config.model_copy(
        update={
            "expiry": config.expiry.model_copy(update={"require_published_last_trading_day": False})
        }
    )
    registry = ContractRegistry(strict, calendar)
    registry.register_symbol("S50Z26", reference_date=date(2026, 12, 1), provenance=provenance)

    # Flip the requirement on a second registry sharing the same calendar cache.
    stricter = strict.model_copy(
        update={
            "expiry": strict.expiry.model_copy(update={"require_published_last_trading_day": True})
        }
    )
    strict_registry = ContractRegistry(stricter, calendar)
    strict_registry.register_symbol(
        "S50Z26", reference_date=date(2026, 12, 1), provenance=provenance
    )

    assert registry.eligibility("S50Z26", as_of=DEC_1).eligible
    result = strict_registry.eligibility("S50Z26", as_of=DEC_1)
    assert not result.eligible
    assert any("published dates are required" in reason for reason in result.reasons)


# --- selection ----------------------------------------------------------------------------


def test_the_registry_hands_out_the_near_month_while_it_is_eligible(
    registry: ContractRegistry,
) -> None:
    contract = registry.request_eligible_contract(as_of=DEC_1)
    assert contract.normalized_symbol == "S50Z26"
    assert contract.is_near_month


def test_the_registry_falls_through_to_the_next_contract_past_the_cutoff(
    registry: ContractRegistry,
) -> None:
    contract = registry.request_eligible_contract(as_of=DEC_28)
    assert contract.normalized_symbol == "S50H27"


def test_no_eligible_contract_is_an_error_not_a_best_guess(registry: ContractRegistry) -> None:
    with pytest.raises(NoEligibleContractError, match="no eligible SET50 futures contract"):
        registry.request_eligible_contract(as_of=bkk(date(2027, 4, 1), time(10, 0)))


def test_the_rejection_message_explains_every_contract(registry: ContractRegistry) -> None:
    with pytest.raises(NoEligibleContractError) as excinfo:
        registry.request_eligible_contract(as_of=bkk(date(2027, 4, 1), time(10, 0)))
    message = str(excinfo.value)
    assert "S50Z26" in message
    assert "S50H27" in message


def test_an_empty_registry_says_so(config: TfexConfig, calendar: TradingCalendar) -> None:
    with pytest.raises(NoEligibleContractError, match="registry is empty"):
        ContractRegistry(config, calendar).request_eligible_contract(as_of=DEC_1)


def test_near_and_next_are_ordered_by_expiry_and_include_ineligible_contracts(
    registry: ContractRegistry,
) -> None:
    """The roll machine must see the near contract become ineligible to react to it."""
    near, next_ = registry.near_and_next(as_of=DEC_28)
    assert (near.normalized_symbol, next_.normalized_symbol) == ("S50Z26", "S50H27")
    assert not registry.eligibility("S50Z26", as_of=DEC_28).eligible


def test_eligible_contracts_are_sorted_nearest_expiry_first(registry: ContractRegistry) -> None:
    symbols = [c.normalized_symbol for c in registry.eligible_contracts(as_of=DEC_1)]
    assert symbols == ["S50Z26", "S50H27"]


# --- market state and reporting --------------------------------------------------------------


def test_market_state_can_be_updated_without_touching_contract_identity(
    registry: ContractRegistry,
) -> None:
    registry.update_market_state(
        "S50Z26",
        ContractMarketState(daily_volume=1, open_interest=2, session_date=date(2026, 12, 1)),
    )
    record = registry.record("S50Z26")

    assert record.market_state.daily_volume == 1
    assert record.parsed.contract_month_key == (2026, 12)


def test_liquidity_snapshot_reflects_stored_market_state(registry: ContractRegistry) -> None:
    contract = registry.resolve("S50Z26", as_of=DEC_1)
    liquidity = registry.liquidity_for(contract)

    assert liquidity.symbol == "S50Z26"
    assert liquidity.session_volume == 100_000
    assert liquidity.open_interest == 50_000
    assert liquidity.status is ContractStatus.ACTIVE


def test_status_report_covers_every_registered_contract(registry: ContractRegistry) -> None:
    rows = registry.status_report(as_of=DEC_28)
    by_symbol = {row["symbol"]: row for row in rows}

    assert set(by_symbol) == {"S50Z26", "S50H27"}
    assert by_symbol["S50Z26"]["eligible"] is False
    assert by_symbol["S50H27"]["eligible"] is True
    assert by_symbol["S50Z26"]["reasons"]
