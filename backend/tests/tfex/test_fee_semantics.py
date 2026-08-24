"""A published fee cap is not an actual charge (`CLAUDE_TFEX.md` sections 3 and 23).

The specification says *"Maximum of THB 7 per contract per side"*. Every test here exists to
stop that maximum being deducted from P&L as though it were what the account pays.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.tfex.config import (
    DEFAULT_CONFIG_PATH,
    ExchangeFeeConfig,
    TfexConfig,
    default_config,
    load_config,
)
from app.tfex.costs import (
    CostScenario,
    FeeComponent,
    FeeKind,
    FeeProvenanceStatus,
    RoundTripCostEstimate,
)
from app.tfex.costs.commissions import broker_commission
from app.tfex.costs.exchange_fees import actual_exchange_fee, exchange_fee_cap
from app.tfex.errors import FeeSemanticsError


def verified_rate(value: str, *, label: str = "verified broker fee") -> FeeComponent:
    return FeeComponent(
        kind=FeeKind.EXCHANGE_FEE,
        label=label,
        value_thb_per_contract_per_side=Decimal(value),
        status=FeeProvenanceStatus.VERIFIED_BROKER_RATE,
        production_charge=True,
        source="broker statement 2026-08",
    )


# --- the central distinction ----------------------------------------------------------


def test_the_cap_and_the_actual_fee_are_different_things(config: TfexConfig) -> None:
    cap = exchange_fee_cap(config)
    actual = actual_exchange_fee(config)

    assert cap.value_thb_per_contract_per_side == Decimal("7")
    assert cap.status is FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP
    assert cap.is_cap

    assert actual.value_thb_per_contract_per_side is None
    assert actual.status is FeeProvenanceStatus.UNKNOWN
    assert not actual.is_known

    assert cap.value_thb_per_contract_per_side != actual.value_thb_per_contract_per_side


def test_the_cap_is_never_a_production_charge(config: TfexConfig) -> None:
    assert exchange_fee_cap(config).production_charge is False


def test_charging_the_cap_in_production_is_refused(config: TfexConfig) -> None:
    with pytest.raises(FeeSemanticsError, match="maximum"):
        exchange_fee_cap(config).charge_for(CostScenario.PRODUCTION)


def test_the_cap_may_be_applied_in_a_labelled_stress_test(config: TfexConfig) -> None:
    """Section 23 allows a conservative assumption — as long as it is labelled as one."""
    charge = exchange_fee_cap(config).charge_for(CostScenario.CONSERVATIVE_STRESS_TEST)
    assert charge == Decimal("7")


def test_an_unknown_cost_cannot_be_charged_in_any_scenario(config: TfexConfig) -> None:
    unknown = actual_exchange_fee(config)
    for scenario in CostScenario:
        with pytest.raises(FeeSemanticsError, match="UNKNOWN"):
            unknown.charge_for(scenario)


def test_a_component_cannot_claim_production_status_without_a_verified_rate() -> None:
    with pytest.raises(ValueError, match="requires a verified broker rate"):
        FeeComponent(
            kind=FeeKind.EXCHANGE_FEE,
            label="sneaky cap",
            value_thb_per_contract_per_side=Decimal("7"),
            status=FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP,
            production_charge=True,
        )


def test_an_assumption_cannot_be_promoted_to_a_production_charge() -> None:
    with pytest.raises(ValueError, match="requires a verified broker rate"):
        FeeComponent(
            kind=FeeKind.BROKER_COMMISSION,
            label="guessed commission",
            value_thb_per_contract_per_side=Decimal("20"),
            status=FeeProvenanceStatus.USER_ASSUMPTION,
            production_charge=True,
        )


def test_a_known_status_must_carry_a_value() -> None:
    with pytest.raises(ValueError, match="claims knowledge but carries no value"):
        FeeComponent(
            kind=FeeKind.BROKER_COMMISSION,
            label="empty",
            status=FeeProvenanceStatus.VERIFIED_BROKER_RATE,
        )


def test_a_negative_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="may not be negative"):
        FeeComponent(
            kind=FeeKind.OTHER,
            label="rebate pretending to be a cost",
            value_thb_per_contract_per_side=Decimal("-1"),
            status=FeeProvenanceStatus.USER_ASSUMPTION,
        )


# --- configuration ----------------------------------------------------------------------


def test_the_shipped_configuration_knows_the_cap_and_not_the_actual_fee() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)

    assert config.costs.exchange_fee.cap_thb_per_contract_per_side == Decimal("7")
    assert "maximum" in config.costs.exchange_fee.cap_source.lower()
    assert config.costs.exchange_fee.actual_thb_per_contract_per_side is None
    assert config.costs.exchange_fee.actual_status is FeeProvenanceStatus.UNKNOWN


def test_commission_has_no_default_because_it_is_negotiable() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    commission = broker_commission(config)

    assert commission.value_thb_per_contract_per_side is None
    assert commission.status is FeeProvenanceStatus.UNKNOWN
    assert not commission.production_charge


def test_configuration_refuses_to_label_the_actual_fee_as_a_cap() -> None:
    with pytest.raises(ValueError, match="a cap is not an actual charged fee"):
        ExchangeFeeConfig(
            actual_thb_per_contract_per_side=Decimal("7"),
            actual_status=FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP,
        )


def test_configuration_refuses_a_known_actual_fee_with_no_value() -> None:
    with pytest.raises(ValueError, match="claims knowledge but no"):
        ExchangeFeeConfig(actual_status=FeeProvenanceStatus.VERIFIED_BROKER_RATE)


def test_a_verified_broker_rate_becomes_chargeable() -> None:
    config = default_config()
    verified = config.model_copy(
        update={
            "costs": config.costs.model_copy(
                update={
                    "exchange_fee": config.costs.exchange_fee.model_copy(
                        update={
                            "actual_thb_per_contract_per_side": Decimal("5.50"),
                            "actual_status": FeeProvenanceStatus.VERIFIED_BROKER_RATE,
                            "actual_source": "broker schedule 2026-08",
                        }
                    )
                }
            )
        }
    )
    component = actual_exchange_fee(verified)

    assert component.production_charge is True
    assert component.charge_for(CostScenario.PRODUCTION) == Decimal("5.50")


# --- round-trip estimates -----------------------------------------------------------------


def test_a_round_trip_charges_both_sides() -> None:
    estimate = RoundTripCostEstimate(
        scenario=CostScenario.PRODUCTION,
        components=(verified_rate("5.50"),),
        contracts=2,
    )
    assert estimate.total_thb() == Decimal("22.00")  # 5.50 x 2 sides x 2 contracts
    assert estimate.production_ready


def test_an_estimate_containing_the_cap_is_not_production_ready(config: TfexConfig) -> None:
    estimate = RoundTripCostEstimate(
        scenario=CostScenario.CONSERVATIVE_STRESS_TEST,
        components=(exchange_fee_cap(config),),
    )
    assert not estimate.production_ready
    assert estimate.total_thb() == Decimal("14")  # 7 x 2 sides


def test_a_production_estimate_containing_the_cap_refuses_to_total(config: TfexConfig) -> None:
    estimate = RoundTripCostEstimate(
        scenario=CostScenario.PRODUCTION,
        components=(verified_rate("5.50"), exchange_fee_cap(config)),
    )
    with pytest.raises(FeeSemanticsError):
        estimate.total_thb()


def test_an_estimate_containing_an_unknown_cost_refuses_to_total(config: TfexConfig) -> None:
    estimate = RoundTripCostEstimate(
        scenario=CostScenario.BACKTEST,
        components=(broker_commission(config),),
    )
    assert estimate.unknown_components
    with pytest.raises(FeeSemanticsError, match="cannot be charged in any scenario"):
        estimate.total_thb()


def test_the_explanation_says_what_is_not_production_ready(config: TfexConfig) -> None:
    estimate = RoundTripCostEstimate(
        scenario=CostScenario.CONSERVATIVE_STRESS_TEST,
        components=(exchange_fee_cap(config), broker_commission(config)),
    )
    text = "\n".join(estimate.explain())

    assert "VERIFIED_EXCHANGE_CAP" in text
    assert "UNKNOWN" in text
    assert "NOT production-ready" in text
