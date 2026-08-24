"""Broker commission.

Section 3: *"brokerage commission: negotiable"*. There is therefore no correct default, and
this module supplies none. Until an operator configures a rate from a real agreement the
commission is ``UNKNOWN``, and an unknown cost cannot be charged in any scenario — which is
what stops a backtest from quietly reporting gross results as if they were net.

Tiering, minimum-fee handling and per-broker overrides arrive with TFEX-5 (section 23).
"""

from __future__ import annotations

from app.tfex.config import TfexConfig
from app.tfex.costs.models import FeeComponent, FeeKind, FeeProvenanceStatus

__all__ = ["broker_commission"]


def broker_commission(config: TfexConfig) -> FeeComponent:
    """The configured commission, or ``UNKNOWN`` when none has been verified."""
    commission = config.costs.commission
    if commission.thb_per_contract_per_side is None:
        return FeeComponent(
            kind=FeeKind.BROKER_COMMISSION,
            label="Broker commission",
            value_thb_per_contract_per_side=None,
            status=FeeProvenanceStatus.UNKNOWN,
            production_charge=False,
            note=(
                "Commission is negotiable per account and none is configured. Set "
                "costs.commission.* from the broker agreement; there is no safe default."
            ),
        )
    return FeeComponent(
        kind=FeeKind.BROKER_COMMISSION,
        label="Broker commission",
        value_thb_per_contract_per_side=commission.thb_per_contract_per_side,
        status=commission.status,
        production_charge=commission.status is FeeProvenanceStatus.VERIFIED_BROKER_RATE,
        source=commission.source,
        note=(
            f"VAT {commission.vat_percent}% applies as configured; minimum per order "
            f"{commission.minimum_thb_per_order}"
        ),
    )
