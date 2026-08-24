"""Exchange fees, with the cap and the actual charge kept apart.

`CLAUDE_TFEX.md` section 3 records *"maximum exchange fee in the current summary: THB 7 per
contract per side"*. This module turns that into two distinct objects:

* :func:`exchange_fee_cap` — the published upper bound. Legitimate in a conservative stress
  test, refused in production accounting.
* :func:`actual_exchange_fee` — what the account is really charged. ``UNKNOWN`` until an
  operator verifies it against a broker statement, and an ``UNKNOWN`` cost cannot be charged
  in any scenario.

The full cost model (tiering, VAT treatment, per-broker overrides) arrives with TFEX-5. What
exists here is the part that must be right *before* any P&L code is written, because the
mistake it prevents is silent.
"""

from __future__ import annotations

from app.tfex.config import TfexConfig
from app.tfex.costs.models import FeeComponent, FeeKind, FeeProvenanceStatus

__all__ = ["actual_exchange_fee", "exchange_fee_cap"]


def exchange_fee_cap(config: TfexConfig) -> FeeComponent:
    """The exchange-published maximum fee. Never a production charge."""
    fee = config.costs.exchange_fee
    return FeeComponent(
        kind=FeeKind.EXCHANGE_FEE,
        label="TFEX exchange fee cap",
        value_thb_per_contract_per_side=fee.cap_thb_per_contract_per_side,
        status=FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP,
        production_charge=False,
        source=fee.cap_source,
        note=(
            "Published as a maximum. Applying it as an actual cost overstates expenses and "
            "will not reconcile against a broker statement."
        ),
    )


def actual_exchange_fee(config: TfexConfig) -> FeeComponent:
    """The fee actually charged, if it has been verified. ``UNKNOWN`` otherwise."""
    fee = config.costs.exchange_fee
    if fee.actual_thb_per_contract_per_side is None:
        return FeeComponent(
            kind=FeeKind.EXCHANGE_FEE,
            label="TFEX exchange fee (actual)",
            value_thb_per_contract_per_side=None,
            status=FeeProvenanceStatus.UNKNOWN,
            production_charge=False,
            note=(
                "Not verified for this account. Configure costs.exchange_fee.actual_* from a "
                "broker statement before costing production trades."
            ),
        )
    return FeeComponent(
        kind=FeeKind.EXCHANGE_FEE,
        label="TFEX exchange fee (actual)",
        value_thb_per_contract_per_side=fee.actual_thb_per_contract_per_side,
        status=fee.actual_status,
        production_charge=fee.actual_status is FeeProvenanceStatus.VERIFIED_BROKER_RATE,
        source=fee.actual_source,
    )
