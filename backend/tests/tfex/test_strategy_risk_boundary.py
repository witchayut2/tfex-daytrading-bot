"""Strategies cannot bypass the dormant risk admission boundary."""

from __future__ import annotations

import inspect

import pytest

import app.tfex.risk.boundary as boundary_module
import app.tfex.risk.engine as engine_module
import app.tfex.risk.position as position_module
from app.tfex.errors import RiskBypassError
from app.tfex.risk.boundary import ExecutionAdmission


@pytest.mark.parametrize(
    "candidate",
    [None, object(), {"symbol": "S50U26"}, "TradeProposal", 1],
)
def test_execution_boundary_rejects_every_non_approved_shape(candidate: object) -> None:
    with pytest.raises(RiskBypassError, match="ApprovedTradePlan only"):
        ExecutionAdmission.require_approved_plan(candidate)


def test_scaffolding_has_no_order_submission_or_settrade_dependency() -> None:
    source = "\n".join(
        inspect.getsource(module) for module in (boundary_module, engine_module, position_module)
    ).lower()
    assert "settrade" not in source
    assert "submit_order" not in source
    assert "place_order" not in source
    assert not hasattr(ExecutionAdmission, "submit")
    assert not hasattr(ExecutionAdmission, "submit_order")
