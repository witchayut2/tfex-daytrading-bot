"""Cost components and the provenance that says what each one actually is.

`CLAUDE_TFEX.md` section 3 records the exchange fee as *"maximum exchange fee in the current
summary: THB 7 per contract per side"*. **Maximum** is the operative word. A cap is an upper
bound published by the exchange; the amount a particular account is actually charged is a
broker fact that this platform does not know until someone verifies it.

Conflating the two is not a rounding error. A backtest that deducts the cap reports a worse
result than reality and rejects strategies that would have been viable; a P&L engine that
deducts the cap and calls it "actual" produces reconciliation breaks against the broker
statement. So the distinction is carried in the type system: a cap is a
:class:`FeeComponent` whose ``production_charge`` is ``False``, and asking it for a
production charge raises :class:`~app.tfex.errors.FeeSemanticsError`.

Section 23 also requires gross and net results to be reported separately, and paper trading
and backtesting to use round-trip cost estimates. :class:`RoundTripCostEstimate` is the shape
those estimates take, and it knows whether it is fit for production.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.tfex.errors import FeeSemanticsError

__all__ = [
    "CostScenario",
    "FeeComponent",
    "FeeKind",
    "FeeProvenanceStatus",
    "RoundTripCostEstimate",
]


class FeeProvenanceStatus(StrEnum):
    """How much is actually known about a cost figure."""

    VERIFIED_EXCHANGE_CAP = "VERIFIED_EXCHANGE_CAP"
    """Published by the exchange as an upper bound. **Not** an amount charged."""

    VERIFIED_BROKER_RATE = "VERIFIED_BROKER_RATE"
    """Confirmed against a broker agreement or statement. Chargeable."""

    USER_ASSUMPTION = "USER_ASSUMPTION"
    """An operator supplied it deliberately. Usable in a labelled scenario, not production."""

    ESTIMATED = "ESTIMATED"
    """Derived from observed fills or market data. Usable in a labelled scenario."""

    UNKNOWN = "UNKNOWN"
    """Nothing is known. The honest default, and never chargeable."""


#: Only a confirmed broker rate may be deducted as an actual cost.
_CHARGEABLE = frozenset({FeeProvenanceStatus.VERIFIED_BROKER_RATE})


class FeeKind(StrEnum):
    EXCHANGE_FEE = "EXCHANGE_FEE"
    BROKER_COMMISSION = "BROKER_COMMISSION"
    VAT = "VAT"
    SLIPPAGE = "SLIPPAGE"
    OTHER = "OTHER"


class CostScenario(StrEnum):
    """What a cost estimate is *for*. Section 23: report gross and net separately."""

    PRODUCTION = "PRODUCTION"
    """Real accounting. Every component must be a verified broker rate."""

    BACKTEST = "BACKTEST"
    """Research. Assumptions are allowed but must be labelled."""

    CONSERVATIVE_STRESS_TEST = "CONSERVATIVE_STRESS_TEST"
    """Deliberately pessimistic — this is where the exchange cap legitimately belongs."""


class FeeComponent(BaseModel):
    """One cost line, with the provenance that decides how it may be used."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: FeeKind
    label: str
    value_thb_per_contract_per_side: Decimal | None = None
    status: FeeProvenanceStatus = FeeProvenanceStatus.UNKNOWN
    production_charge: bool = False
    """Whether this may be deducted as a real cost. Derived from ``status``; never set to
    ``True`` for a cap or an assumption."""

    source: str | None = None
    effective_date: date | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _production_charge_matches_status(self) -> Self:
        if self.production_charge and self.status not in _CHARGEABLE:
            raise ValueError(
                f"{self.label}: production_charge=True requires a verified broker rate, but "
                f"status is {self.status}. A cap or an assumption is not an actual charge."
            )
        if self.value_thb_per_contract_per_side is not None:
            if self.value_thb_per_contract_per_side < 0:
                raise ValueError(f"{self.label}: a cost may not be negative")
        elif self.status is not FeeProvenanceStatus.UNKNOWN:
            raise ValueError(
                f"{self.label}: status {self.status} claims knowledge but carries no value"
            )
        return self

    @property
    def is_known(self) -> bool:
        return self.status is not FeeProvenanceStatus.UNKNOWN

    @property
    def is_cap(self) -> bool:
        return self.status is FeeProvenanceStatus.VERIFIED_EXCHANGE_CAP

    def charge_for(self, scenario: CostScenario) -> Decimal:
        """The amount to deduct per contract per side in ``scenario``.

        Raises:
            FeeSemanticsError: this component may not be charged in that scenario — an
                exchange cap or an assumption in ``PRODUCTION``, or an unknown cost anywhere.
        """
        if self.status is FeeProvenanceStatus.UNKNOWN:
            raise FeeSemanticsError(
                f"{self.label} is UNKNOWN and cannot be charged in any scenario; verify the "
                f"rate with the broker before costing trades"
            )
        value = self.value_thb_per_contract_per_side
        assert value is not None  # guaranteed by the validator above

        if scenario is CostScenario.PRODUCTION and not self.production_charge:
            raise FeeSemanticsError(
                f"{self.label} has status {self.status} and is not a production charge. "
                f"The exchange publishes THB 7 per contract per side as a *maximum*, not as "
                f"the amount charged; use CONSERVATIVE_STRESS_TEST to apply it deliberately, "
                f"or verify the broker's actual rate."
            )
        return value


class RoundTripCostEstimate(BaseModel):
    """Round-trip cost for one contract, and whether it may be believed (section 23)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: CostScenario
    components: tuple[FeeComponent, ...]
    contracts: int = 1

    @model_validator(mode="after")
    def _positive_quantity(self) -> Self:
        if self.contracts < 1:
            raise ValueError("a cost estimate needs at least one contract")
        return self

    @property
    def unknown_components(self) -> tuple[FeeComponent, ...]:
        return tuple(c for c in self.components if not c.is_known)

    @property
    def production_ready(self) -> bool:
        """True only when every component is a verified broker rate."""
        return bool(self.components) and all(c.production_charge for c in self.components)

    def total_thb(self) -> Decimal:
        """Round-trip total: every component charged on both the entry and the exit side.

        Raises:
            FeeSemanticsError: any component may not be charged in this scenario.
        """
        per_side = sum((c.charge_for(self.scenario) for c in self.components), start=Decimal(0))
        return per_side * 2 * self.contracts

    def explain(self) -> tuple[str, ...]:
        """Human-readable lines for the audit log and the dashboard's risk panel."""
        lines = [f"scenario={self.scenario}, contracts={self.contracts}"]
        for component in self.components:
            value = (
                f"THB {component.value_thb_per_contract_per_side}/contract/side"
                if component.value_thb_per_contract_per_side is not None
                else "no value"
            )
            lines.append(
                f"  {component.label}: {value} [{component.status}]"
                + ("" if component.production_charge else " (not a production charge)")
            )
        if not self.production_ready:
            lines.append(
                "  NOT production-ready: at least one component is a cap, an assumption, or unknown"
            )
        return tuple(lines)
