"""Dormant, deterministic risk and position contracts for future TFEX-4/TFEX-5.

These exports are architecture and unit-test scaffolding only. No broker dependency, order
submission, or runtime strategy activation exists here.
"""

from app.tfex.risk.audit import TradeAuditRecord
from app.tfex.risk.boundary import ExecutionAdmission, StrategyProposalSource
from app.tfex.risk.engine import KillSwitchEvaluator, RiskEngine
from app.tfex.risk.models import (
    ApprovedTradePlan,
    CostAssumptions,
    ExitPlanProposal,
    RiskContext,
    RiskDecision,
    StrategyRiskRule,
    TradeProposal,
)
from app.tfex.risk.position import ManagedPosition, PositionManager

__all__ = [
    "ApprovedTradePlan",
    "CostAssumptions",
    "ExecutionAdmission",
    "ExitPlanProposal",
    "KillSwitchEvaluator",
    "ManagedPosition",
    "PositionManager",
    "RiskContext",
    "RiskDecision",
    "RiskEngine",
    "StrategyProposalSource",
    "StrategyRiskRule",
    "TradeAuditRecord",
    "TradeProposal",
]
