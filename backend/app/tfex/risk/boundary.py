"""Type-enforced seam between strategies, risk, and future execution.

The boundary is intentionally dormant. It validates shape only and has no broker client or
order-submit method. Future paper/live adapters must accept ``ApprovedTradePlan`` here and
must never accept a strategy proposal directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from app.tfex.errors import RiskBypassError
from app.tfex.risk.models import ApprovedTradePlan, RiskContext, TradeProposal

__all__ = ["ExecutionAdmission", "StrategyProposalSource"]


@runtime_checkable
class StrategyProposalSource(Protocol):
    """A strategy may emit a quantity-free proposal, never an order."""

    def propose(self, context: RiskContext) -> TradeProposal | None: ...


class ExecutionAdmission:
    """Validate the only permitted input to a future execution adapter."""

    @staticmethod
    def require_approved_plan(candidate: object) -> ApprovedTradePlan:
        if not isinstance(candidate, ApprovedTradePlan):
            raise RiskBypassError(
                "execution accepts ApprovedTradePlan only; TradeProposal must pass RiskEngine"
            )
        try:
            # ``model_copy(update=...)`` deliberately skips validation in Pydantic. Rebuild
            # at this trust boundary so a forged copy cannot bypass cross-model invariants.
            return ApprovedTradePlan.model_validate(candidate.model_dump())
        except ValidationError as exc:
            raise RiskBypassError(f"approved plan failed invariant validation: {exc}") from None
