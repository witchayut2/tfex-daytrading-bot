"""Aggregate audit contract for one strategy proposal and its complete lifecycle."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.risk.models import (
    AuditEvent,
    AuditEventType,
    CostAssumptions,
    KillSwitchDecision,
    RiskDecision,
    RiskDecisionStatus,
    TradeProposal,
)
from app.tfex.risk.position import ManagedPosition

__all__ = ["TradeAuditRecord"]


class TradeAuditRecord(BaseModel):
    """JSON-serializable record sufficient to reconstruct a decision and state changes.

    Storage is deliberately outside this task. This schema is the contract a future
    append-only audit repository must persist without dropping fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str = Field(min_length=1)
    proposal: TradeProposal
    risk_decision: RiskDecision
    cost_assumptions: CostAssumptions
    kill_switch_history: tuple[KillSwitchDecision, ...] = Field(min_length=1)
    lifecycle_events: tuple[AuditEvent, ...] = Field(min_length=2)
    position: ManagedPosition | None = None

    @model_validator(mode="after")
    def _is_reconstructable(self) -> Self:
        if self.risk_decision.proposal_id != self.proposal.proposal_id:
            raise ValueError("audit proposal and risk decision identifiers differ")
        if self.kill_switch_history[0] != self.risk_decision.kill_switch:
            raise ValueError("audit kill-switch history must begin with the risk decision state")
        if any(event.trade_id != self.trade_id for event in self.lifecycle_events):
            raise ValueError("all lifecycle events must use the audit trade identifier")
        sequences = tuple(event.sequence for event in self.lifecycle_events)
        if sequences != tuple(range(sequences[0], sequences[0] + len(sequences))):
            raise ValueError("audit event sequences must be ordered and contiguous")
        event_types = {event.event_type for event in self.lifecycle_events}
        if AuditEventType.PROPOSAL_CREATED not in event_types:
            raise ValueError("audit requires a proposal-created event")
        required_decision_event = (
            AuditEventType.RISK_APPROVED
            if self.risk_decision.status is RiskDecisionStatus.APPROVED
            else AuditEventType.RISK_REJECTED
        )
        if required_decision_event not in event_types:
            raise ValueError("audit requires an event matching the risk decision")
        plan = self.risk_decision.approved_plan
        if plan is not None and plan.cost_assumptions_id != self.cost_assumptions.assumptions_id:
            raise ValueError("audit cost assumptions do not match the approved plan")
        if self.position is not None:
            if plan is None:
                raise ValueError("a rejected proposal cannot have a normal managed position")
            if self.position.plan != plan:
                raise ValueError("audit position does not derive from its approved plan")
        return self
