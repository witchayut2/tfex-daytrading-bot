"""Pure order/position lifecycle and protective-exit invariants.

Nothing in this module talks to a broker. The operations return new immutable state so the
same input event sequence always produces the same audit-reconstructable result.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.errors import InvalidOrderTransitionError, PositionProtectionError
from app.tfex.risk.models import ApprovedTradePlan, DecisionInput, TradeSide

__all__ = [
    "ExitReason",
    "FillRecord",
    "FillRole",
    "LifecycleState",
    "ManagedPosition",
    "PositionManager",
    "ProtectionStatus",
    "RecoveryExposure",
    "RecoveryReason",
    "StopChangeDecision",
    "StopUpdateKind",
    "StopUpdateRequest",
    "validate_lifecycle_transition",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LifecycleState(StrEnum):
    SIGNAL_CANDIDATE = "SIGNAL_CANDIDATE"
    RISK_EVALUATION = "RISK_EVALUATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ENTRY_PENDING = "ENTRY_PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PROTECTED = "PROTECTED"
    MANAGED = "MANAGED"
    EXIT_PENDING = "EXIT_PENDING"
    EMERGENCY_EXIT_PENDING = "EMERGENCY_EXIT_PENDING"
    RECONCILIATION_BLOCKED = "RECONCILIATION_BLOCKED"
    CLOSED = "CLOSED"


_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.SIGNAL_CANDIDATE: frozenset({LifecycleState.RISK_EVALUATION}),
    LifecycleState.RISK_EVALUATION: frozenset({LifecycleState.APPROVED, LifecycleState.REJECTED}),
    LifecycleState.APPROVED: frozenset({LifecycleState.ENTRY_PENDING}),
    LifecycleState.REJECTED: frozenset(),
    LifecycleState.ENTRY_PENDING: frozenset(
        {
            LifecycleState.PARTIALLY_FILLED,
            LifecycleState.FILLED,
            LifecycleState.REJECTED,
            LifecycleState.RECONCILIATION_BLOCKED,
        }
    ),
    LifecycleState.PARTIALLY_FILLED: frozenset(
        {
            LifecycleState.PARTIALLY_FILLED,
            LifecycleState.FILLED,
            LifecycleState.PROTECTED,
            LifecycleState.EXIT_PENDING,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
        }
    ),
    LifecycleState.FILLED: frozenset(
        {
            LifecycleState.PROTECTED,
            LifecycleState.EXIT_PENDING,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
        }
    ),
    LifecycleState.PROTECTED: frozenset(
        {
            LifecycleState.PROTECTED,
            LifecycleState.PARTIALLY_FILLED,
            LifecycleState.FILLED,
            LifecycleState.MANAGED,
            LifecycleState.EXIT_PENDING,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
            LifecycleState.CLOSED,
        }
    ),
    LifecycleState.MANAGED: frozenset(
        {
            LifecycleState.MANAGED,
            LifecycleState.EXIT_PENDING,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
            LifecycleState.CLOSED,
        }
    ),
    LifecycleState.EXIT_PENDING: frozenset(
        {
            LifecycleState.MANAGED,
            LifecycleState.EXIT_PENDING,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
            LifecycleState.CLOSED,
        }
    ),
    LifecycleState.EMERGENCY_EXIT_PENDING: frozenset(
        {
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
            LifecycleState.CLOSED,
        }
    ),
    LifecycleState.RECONCILIATION_BLOCKED: frozenset(
        {
            LifecycleState.RECONCILIATION_BLOCKED,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.CLOSED,
        }
    ),
    LifecycleState.CLOSED: frozenset(),
}


def validate_lifecycle_transition(current: LifecycleState, next_state: LifecycleState) -> None:
    """Reject every transition not present in the locked lifecycle graph."""

    if next_state not in _TRANSITIONS[current]:
        raise InvalidOrderTransitionError(
            f"invalid lifecycle transition: {current} -> {next_state}"
        )


class ProtectionStatus(StrEnum):
    PLANNED = "PLANNED"
    PENDING_ACK = "PENDING_ACK"
    ACTIVE = "ACTIVE"
    REPLACE_PENDING = "REPLACE_PENDING"
    EMERGENCY_FLATTEN_REQUIRED = "EMERGENCY_FLATTEN_REQUIRED"
    EXECUTED = "EXECUTED"


class FillRole(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class ExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    TIME_STOP = "TIME_STOP"
    SESSION_EXIT = "SESSION_EXIT"
    EOD_FLATTEN = "EOD_FLATTEN"
    EMERGENCY_FLATTEN = "EMERGENCY_FLATTEN"


class RecoveryReason(StrEnum):
    PROCESS_RESTART = "PROCESS_RESTART"
    CONNECTION_RESTORED = "CONNECTION_RESTORED"
    UNEXPECTED_BROKER_POSITION = "UNEXPECTED_BROKER_POSITION"
    EXIT_FAILURE = "EXIT_FAILURE"


class FillRecord(_Frozen):
    fill_id: str = Field(min_length=1)
    role: FillRole
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    event_time: datetime
    recorded_at: datetime
    broker_order_id: str | None = None
    broker_fill_id: str | None = None
    exit_reason: ExitReason | None = None

    @model_validator(mode="after")
    def _valid_fill(self) -> Self:
        if self.event_time.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("fill timestamps must be timezone-aware")
        if self.recorded_at < self.event_time:
            raise ValueError("fill recorded_at cannot precede event_time")
        if self.role is FillRole.ENTRY and self.exit_reason is not None:
            raise ValueError("an entry fill cannot carry an exit reason")
        if self.role is FillRole.EXIT and self.exit_reason is None:
            raise ValueError("an exit fill requires an exit reason")
        return self


class StopUpdateKind(StrEnum):
    UNCHANGED = "UNCHANGED"
    TIGHTEN = "TIGHTEN"
    BREAK_EVEN = "BREAK_EVEN"
    LOCK_PROFIT = "LOCK_PROFIT"
    STRUCTURE_TRAIL = "STRUCTURE_TRAIL"
    ATR_TRAIL = "ATR_TRAIL"


class StopUpdateRequest(_Frozen):
    update_id: str = Field(min_length=1)
    kind: StopUpdateKind
    new_stop_price: Decimal = Field(gt=0)
    rule_id: str = Field(min_length=1)
    decided_at: datetime
    inputs: tuple[DecisionInput, ...] = ()

    @model_validator(mode="after")
    def _deterministic_evidence(self) -> Self:
        if self.decided_at.tzinfo is None:
            raise ValueError("stop decision time must be timezone-aware")
        if (
            self.kind in {StopUpdateKind.STRUCTURE_TRAIL, StopUpdateKind.ATR_TRAIL}
            and not self.inputs
        ):
            raise ValueError("structure and ATR trails require serialized decision inputs")
        return self


class StopChangeDecision(_Frozen):
    accepted: bool
    previous_stop_price: Decimal = Field(gt=0)
    requested_stop_price: Decimal = Field(gt=0)
    kind: StopUpdateKind
    reason: str = Field(min_length=1)
    decided_at: datetime
    rule_id: str = Field(min_length=1)
    inputs: tuple[DecisionInput, ...] = ()

    @model_validator(mode="after")
    def _aware_decision_time(self) -> Self:
        if self.decided_at.tzinfo is None:
            raise ValueError("stop-change decision time must be timezone-aware")
        return self


class ManagedPosition(_Frozen):
    """Immutable state with a protection quantity equal to every open contract."""

    position_id: str = Field(min_length=1)
    plan: ApprovedTradePlan
    state: LifecycleState
    planned_entry_quantity: int = Field(gt=0)
    entry_order_open: bool = True
    filled_entry_quantity: int = Field(default=0, ge=0)
    exited_quantity: int = Field(default=0, ge=0)
    average_entry_price: Decimal | None = Field(default=None, gt=0)
    current_stop_price: Decimal = Field(gt=0)
    protective_quantity: int = Field(default=0, ge=0)
    protection_status: ProtectionStatus = ProtectionStatus.PLANNED
    fills: tuple[FillRecord, ...] = ()
    stop_changes: tuple[StopChangeDecision, ...] = ()
    pending_exit_reason: ExitReason | None = None

    @property
    def open_quantity(self) -> int:
        return self.filled_entry_quantity - self.exited_quantity

    @property
    def remaining_entry_quantity(self) -> int:
        return self.planned_entry_quantity - self.filled_entry_quantity

    @model_validator(mode="after")
    def _always_has_a_protective_risk_state(self) -> Self:
        if self.planned_entry_quantity != self.plan.calculation.contracts:
            raise ValueError("planned entry quantity must equal risk-approved quantity")
        if self.filled_entry_quantity > self.planned_entry_quantity:
            raise ValueError("filled entry quantity exceeds the approved plan")
        if self.exited_quantity > self.filled_entry_quantity:
            raise ValueError("exited quantity exceeds filled exposure")
        if self.filled_entry_quantity == self.planned_entry_quantity and self.entry_order_open:
            raise ValueError("fully filled entry order cannot remain open")
        if self.exited_quantity and self.entry_order_open:
            raise ValueError("entry remainder must be closed before any exit")
        if self.open_quantity == 0:
            if self.protective_quantity != 0:
                raise ValueError("flat position cannot retain protective quantity")
            if self.filled_entry_quantity == 0:
                if self.average_entry_price is not None:
                    raise ValueError("unfilled position cannot have an average entry")
                if self.protection_status is not ProtectionStatus.PLANNED:
                    raise ValueError("unfilled entry must retain its planned protection")
                if self.state is not LifecycleState.ENTRY_PENDING or not self.entry_order_open:
                    raise ValueError("unfilled approved position must have an open entry order")
            elif self.state is not LifecycleState.CLOSED:
                raise ValueError("fully exited position must be CLOSED")
            elif self.protection_status is not ProtectionStatus.EXECUTED:
                raise ValueError("closed position protection must be executed")
        else:
            if self.average_entry_price is None:
                raise ValueError("filled exposure requires an average entry")
            if self.protective_quantity != self.open_quantity:
                raise ValueError("protective quantity must equal all open exposure")
            if self.protection_status not in {
                ProtectionStatus.PENDING_ACK,
                ProtectionStatus.ACTIVE,
                ProtectionStatus.REPLACE_PENDING,
                ProtectionStatus.EMERGENCY_FLATTEN_REQUIRED,
            }:
                raise ValueError("filled exposure has no protective risk state")
            if self.state is LifecycleState.CLOSED:
                raise ValueError("a CLOSED position cannot have open exposure")
            if self.state in {
                LifecycleState.SIGNAL_CANDIDATE,
                LifecycleState.RISK_EVALUATION,
                LifecycleState.APPROVED,
                LifecycleState.REJECTED,
                LifecycleState.ENTRY_PENDING,
            }:
                raise ValueError("filled exposure cannot remain in a pre-fill state")
            initial_stop = self.plan.protective_exit.initial_stop_price
            if (
                self.plan.proposal.side is TradeSide.LONG and self.current_stop_price < initial_stop
            ) or (
                self.plan.proposal.side is TradeSide.SHORT
                and self.current_stop_price > initial_stop
            ):
                raise ValueError("current stop may not widen beyond the approved initial stop")
        if self.state is LifecycleState.PARTIALLY_FILLED and not (
            0 < self.filled_entry_quantity < self.planned_entry_quantity
        ):
            raise ValueError("PARTIALLY_FILLED requires a strict partial entry quantity")
        if self.state is LifecycleState.FILLED and (
            self.filled_entry_quantity != self.planned_entry_quantity
        ):
            raise ValueError("FILLED requires all approved entry quantity")
        if self.state is LifecycleState.PROTECTED and (
            self.protection_status is not ProtectionStatus.ACTIVE
        ):
            raise ValueError("PROTECTED state requires active protection")
        if (
            self.state
            in {
                LifecycleState.EXIT_PENDING,
                LifecycleState.EMERGENCY_EXIT_PENDING,
            }
            and self.pending_exit_reason is None
        ):
            raise ValueError("exit-pending state requires a deterministic exit reason")
        fill_ids = tuple(fill.fill_id for fill in self.fills)
        if len(fill_ids) != len(set(fill_ids)):
            raise ValueError("fill IDs must be unique")
        stop_keys = tuple(
            change.rule_id + "|" + change.decided_at.isoformat() for change in self.stop_changes
        )
        if len(stop_keys) != len(set(stop_keys)):
            raise ValueError("stop-change rule/time pairs must be unique")
        expected_stop = self.plan.protective_exit.initial_stop_price
        for change in self.stop_changes:
            if not change.accepted or change.previous_stop_price != expected_stop:
                raise ValueError("stop-change history is not contiguous and accepted")
            if (
                self.plan.proposal.side is TradeSide.LONG
                and change.requested_stop_price < expected_stop
            ) or (
                self.plan.proposal.side is TradeSide.SHORT
                and change.requested_stop_price > expected_stop
            ):
                raise ValueError("stop-change history contains widening")
            expected_stop = change.requested_stop_price
        if expected_stop != self.current_stop_price:
            raise ValueError("current stop does not match stop-change history")
        return self


class RecoveryExposure(_Frozen):
    """Fail-closed representation of broker exposure not trusted as normal local state."""

    recovery_id: str = Field(min_length=1)
    reason: RecoveryReason
    symbol: str = Field(min_length=1)
    side: TradeSide
    observed_quantity: int = Field(gt=0)
    observed_average_entry_price: Decimal = Field(gt=0)
    emergency_stop_price: Decimal = Field(gt=0)
    protective_quantity: int = Field(gt=0)
    protection_status: ProtectionStatus = ProtectionStatus.EMERGENCY_FLATTEN_REQUIRED
    state: LifecycleState = LifecycleState.EMERGENCY_EXIT_PENDING
    observed_at: datetime
    flatten_when_executable: bool = True

    @model_validator(mode="after")
    def _fully_protected_and_fail_closed(self) -> Self:
        if self.protective_quantity != self.observed_quantity:
            raise ValueError("recovery protection must cover all observed exposure")
        if self.protection_status is not ProtectionStatus.EMERGENCY_FLATTEN_REQUIRED:
            raise ValueError("recovered exposure requires emergency protective status")
        if self.state is not LifecycleState.EMERGENCY_EXIT_PENDING:
            raise ValueError("recovered exposure must remain emergency-exit pending")
        if self.observed_at.tzinfo is None:
            raise ValueError("recovery observation time must be timezone-aware")
        if not self.flatten_when_executable:
            raise ValueError("unexpected exposure must flatten when executable")
        if (
            self.side is TradeSide.LONG
            and self.emergency_stop_price >= self.observed_average_entry_price
        ) or (
            self.side is TradeSide.SHORT
            and self.emergency_stop_price <= self.observed_average_entry_price
        ):
            raise ValueError("emergency stop must be on the protective side of observed entry")
        return self


def _replace_position(position: ManagedPosition, **updates: object) -> ManagedPosition:
    """Rebuild state through Pydantic so every transition re-runs protection validators."""

    values = position.model_dump()
    values.update(updates)
    return ManagedPosition.model_validate(values)


class PositionManager:
    """Deterministic reducers for fills, protection, stop changes, and exits."""

    @staticmethod
    def from_approved_plan(plan: ApprovedTradePlan) -> ManagedPosition:
        plan = ApprovedTradePlan.model_validate(plan.model_dump())
        if plan.resulting_total_contracts != plan.calculation.contracts:
            raise PositionProtectionError(
                "pyramid plan requires an explicit existing-position merge reducer"
            )
        return ManagedPosition(
            position_id=f"position:{plan.plan_id}",
            plan=plan,
            state=LifecycleState.ENTRY_PENDING,
            planned_entry_quantity=plan.calculation.contracts,
            current_stop_price=plan.protective_exit.initial_stop_price,
        )

    @staticmethod
    def apply_entry_fill(position: ManagedPosition, fill: FillRecord) -> ManagedPosition:
        if fill.role is not FillRole.ENTRY:
            raise InvalidOrderTransitionError("entry reducer requires an ENTRY fill")
        if position.state not in {
            LifecycleState.ENTRY_PENDING,
            LifecycleState.PARTIALLY_FILLED,
            LifecycleState.PROTECTED,
        }:
            raise InvalidOrderTransitionError(
                f"entry fill is invalid while position is {position.state}"
            )
        if not position.entry_order_open:
            raise InvalidOrderTransitionError("entry fill is invalid after entry order closed")
        if position.exited_quantity:
            raise InvalidOrderTransitionError("cannot resume entry fills after an exit")
        PositionManager._require_new_fill(position, fill)
        new_filled = position.filled_entry_quantity + fill.quantity
        if new_filled > position.planned_entry_quantity:
            raise InvalidOrderTransitionError("entry fill exceeds approved quantity")
        previous_notional = (
            position.average_entry_price or Decimal(0)
        ) * position.filled_entry_quantity
        average = (previous_notional + fill.price * fill.quantity) / new_filled
        next_state = (
            LifecycleState.FILLED
            if new_filled == position.planned_entry_quantity
            else LifecycleState.PARTIALLY_FILLED
        )
        validate_lifecycle_transition(position.state, next_state)
        return _replace_position(
            position,
            state=next_state,
            filled_entry_quantity=new_filled,
            average_entry_price=average,
            protective_quantity=new_filled,
            protection_status=ProtectionStatus.PENDING_ACK,
            entry_order_open=new_filled < position.planned_entry_quantity,
            fills=(*position.fills, fill),
        )

    @staticmethod
    def cancel_remaining_entry(position: ManagedPosition) -> ManagedPosition:
        """Close the unfilled remainder without changing its approved quantity or history."""

        if not position.entry_order_open or position.remaining_entry_quantity <= 0:
            raise InvalidOrderTransitionError("no open entry remainder can be cancelled")
        if position.state not in {
            LifecycleState.PARTIALLY_FILLED,
            LifecycleState.PROTECTED,
        }:
            raise InvalidOrderTransitionError(
                f"entry remainder cannot be cancelled while position is {position.state}"
            )
        validate_lifecycle_transition(position.state, position.state)
        return _replace_position(position, entry_order_open=False)

    @staticmethod
    def acknowledge_protection(position: ManagedPosition) -> ManagedPosition:
        if position.open_quantity <= 0 or position.protection_status not in {
            ProtectionStatus.PENDING_ACK,
            ProtectionStatus.REPLACE_PENDING,
        }:
            raise PositionProtectionError("no pending protection can be acknowledged")
        next_state = (
            LifecycleState.PROTECTED
            if position.state in {LifecycleState.PARTIALLY_FILLED, LifecycleState.FILLED}
            else position.state
        )
        validate_lifecycle_transition(position.state, next_state)
        return _replace_position(
            position,
            state=next_state,
            protection_status=ProtectionStatus.ACTIVE,
        )

    @staticmethod
    def evaluate_stop_change(
        position: ManagedPosition, request: StopUpdateRequest
    ) -> StopChangeDecision:
        old = position.current_stop_price
        new = request.new_stop_price
        widens = new < old if position.plan.proposal.side is TradeSide.LONG else new > old
        if widens:
            return StopChangeDecision(
                accepted=False,
                previous_stop_price=old,
                requested_stop_price=new,
                kind=request.kind,
                reason="stop widening after entry is prohibited",
                decided_at=request.decided_at,
                rule_id=request.rule_id,
                inputs=request.inputs,
            )
        average = position.average_entry_price
        assert average is not None
        if request.kind is StopUpdateKind.UNCHANGED and new != old:
            accepted = False
            reason = "UNCHANGED request must keep the current stop price"
        elif request.kind is not StopUpdateKind.UNCHANGED and new == old:
            accepted = False
            reason = "a non-UNCHANGED request must change the stop price"
        elif request.kind is StopUpdateKind.BREAK_EVEN and new != average:
            accepted = False
            reason = "BREAK_EVEN stop must equal the filled average entry price"
        elif request.kind is StopUpdateKind.LOCK_PROFIT and (
            (position.plan.proposal.side is TradeSide.LONG and new <= average)
            or (position.plan.proposal.side is TradeSide.SHORT and new >= average)
        ):
            accepted = False
            reason = "LOCK_PROFIT stop must be beyond average entry in the profitable direction"
        else:
            accepted = True
            reason = "stop is unchanged or moves only toward lower open risk"
        return StopChangeDecision(
            accepted=accepted,
            previous_stop_price=old,
            requested_stop_price=new,
            kind=request.kind,
            reason=reason,
            decided_at=request.decided_at,
            rule_id=request.rule_id,
            inputs=request.inputs,
        )

    @staticmethod
    def apply_stop_change(
        position: ManagedPosition, decision: StopChangeDecision
    ) -> ManagedPosition:
        if position.open_quantity <= 0:
            raise PositionProtectionError("flat position has no stop to modify")
        if position.state not in {LifecycleState.PROTECTED, LifecycleState.MANAGED}:
            raise InvalidOrderTransitionError(
                f"stop modification is invalid while position is {position.state}"
            )
        if not decision.accepted:
            raise PositionProtectionError(decision.reason)
        if decision.previous_stop_price != position.current_stop_price:
            raise PositionProtectionError("stale stop decision does not match current state")
        if (
            position.plan.proposal.side is TradeSide.LONG
            and decision.requested_stop_price < position.current_stop_price
        ) or (
            position.plan.proposal.side is TradeSide.SHORT
            and decision.requested_stop_price > position.current_stop_price
        ):
            raise PositionProtectionError("stop widening after entry is prohibited")
        validate_lifecycle_transition(position.state, LifecycleState.MANAGED)
        return _replace_position(
            position,
            state=LifecycleState.MANAGED,
            current_stop_price=decision.requested_stop_price,
            protective_quantity=position.open_quantity,
            protection_status=(
                ProtectionStatus.ACTIVE
                if decision.requested_stop_price == decision.previous_stop_price
                else ProtectionStatus.REPLACE_PENDING
            ),
            stop_changes=(*position.stop_changes, decision),
        )

    @staticmethod
    def request_exit(position: ManagedPosition, reason: ExitReason) -> ManagedPosition:
        if position.open_quantity <= 0:
            raise InvalidOrderTransitionError("flat position cannot request an exit")
        validate_lifecycle_transition(position.state, LifecycleState.EXIT_PENDING)
        return _replace_position(
            position,
            state=LifecycleState.EXIT_PENDING,
            entry_order_open=False,
            pending_exit_reason=reason,
        )

    @staticmethod
    def request_eod_flatten(
        position: ManagedPosition, *, session_requires_flatten: bool
    ) -> ManagedPosition:
        if not session_requires_flatten:
            raise InvalidOrderTransitionError("EOD flatten cannot trigger before session policy")
        return PositionManager.request_exit(position, ExitReason.EOD_FLATTEN)

    @staticmethod
    def protection_failed(position: ManagedPosition) -> ManagedPosition:
        if position.open_quantity <= 0:
            raise PositionProtectionError("flat position has no failed protection")
        validate_lifecycle_transition(position.state, LifecycleState.EMERGENCY_EXIT_PENDING)
        return _replace_position(
            position,
            state=LifecycleState.EMERGENCY_EXIT_PENDING,
            protective_quantity=position.open_quantity,
            protection_status=ProtectionStatus.EMERGENCY_FLATTEN_REQUIRED,
            entry_order_open=False,
            pending_exit_reason=ExitReason.EMERGENCY_FLATTEN,
        )

    @staticmethod
    def exit_failed(position: ManagedPosition) -> ManagedPosition:
        """Keep protection and convert a failed normal exit into emergency flatten state."""

        if position.state is not LifecycleState.EXIT_PENDING:
            raise InvalidOrderTransitionError("exit failure requires EXIT_PENDING state")
        return PositionManager.protection_failed(position)

    @staticmethod
    def reconciliation_failed(position: ManagedPosition) -> ManagedPosition:
        if position.open_quantity <= 0:
            raise PositionProtectionError("flat position has no exposure to reconcile")
        validate_lifecycle_transition(position.state, LifecycleState.RECONCILIATION_BLOCKED)
        return _replace_position(
            position,
            state=LifecycleState.RECONCILIATION_BLOCKED,
            entry_order_open=False,
        )

    @staticmethod
    def recover_unexpected_exposure(
        *,
        recovery_id: str,
        reason: RecoveryReason,
        symbol: str,
        side: TradeSide,
        observed_quantity: int,
        observed_average_entry_price: Decimal,
        emergency_stop_price: Decimal,
        observed_at: datetime,
    ) -> RecoveryExposure:
        """Create no normal position; require full protection and emergency flatten."""

        return RecoveryExposure(
            recovery_id=recovery_id,
            reason=reason,
            symbol=symbol,
            side=side,
            observed_quantity=observed_quantity,
            observed_average_entry_price=observed_average_entry_price,
            emergency_stop_price=emergency_stop_price,
            protective_quantity=observed_quantity,
            observed_at=observed_at,
        )

    @staticmethod
    def apply_exit_fill(position: ManagedPosition, fill: FillRecord) -> ManagedPosition:
        if fill.role is not FillRole.EXIT:
            raise InvalidOrderTransitionError("exit reducer requires an EXIT fill")
        if position.open_quantity <= 0:
            raise InvalidOrderTransitionError("flat position cannot receive an exit fill")
        if fill.quantity > position.open_quantity:
            raise InvalidOrderTransitionError("exit fill exceeds open exposure")
        PositionManager._require_new_fill(position, fill)
        if position.state not in {
            LifecycleState.PROTECTED,
            LifecycleState.MANAGED,
            LifecycleState.EXIT_PENDING,
            LifecycleState.EMERGENCY_EXIT_PENDING,
            LifecycleState.RECONCILIATION_BLOCKED,
        }:
            raise InvalidOrderTransitionError(
                f"exit fill is invalid while position is {position.state}"
            )
        new_exited = position.exited_quantity + fill.quantity
        remaining = position.filled_entry_quantity - new_exited
        if remaining == 0:
            next_state = LifecycleState.CLOSED
            protection = ProtectionStatus.EXECUTED
            pending_reason = None
        elif position.state is LifecycleState.EMERGENCY_EXIT_PENDING:
            next_state = LifecycleState.EMERGENCY_EXIT_PENDING
            protection = ProtectionStatus.EMERGENCY_FLATTEN_REQUIRED
            pending_reason = position.pending_exit_reason
        elif position.state is LifecycleState.RECONCILIATION_BLOCKED:
            next_state = LifecycleState.RECONCILIATION_BLOCKED
            protection = ProtectionStatus.REPLACE_PENDING
            pending_reason = position.pending_exit_reason
        elif (
            position.state is LifecycleState.EXIT_PENDING
            and fill.exit_reason is ExitReason.PARTIAL_TAKE_PROFIT
        ):
            next_state = LifecycleState.MANAGED
            protection = ProtectionStatus.REPLACE_PENDING
            pending_reason = None
        elif position.state is LifecycleState.EXIT_PENDING:
            next_state = LifecycleState.EXIT_PENDING
            protection = ProtectionStatus.REPLACE_PENDING
            pending_reason = position.pending_exit_reason
        else:
            next_state = LifecycleState.MANAGED
            protection = ProtectionStatus.REPLACE_PENDING
            pending_reason = position.pending_exit_reason
        validate_lifecycle_transition(position.state, next_state)
        return _replace_position(
            position,
            state=next_state,
            exited_quantity=new_exited,
            entry_order_open=False,
            protective_quantity=remaining,
            protection_status=protection,
            fills=(*position.fills, fill),
            pending_exit_reason=pending_reason,
        )

    @staticmethod
    def _require_new_fill(position: ManagedPosition, fill: FillRecord) -> None:
        if any(existing.fill_id == fill.fill_id for existing in position.fills):
            raise InvalidOrderTransitionError(f"duplicate fill ID: {fill.fill_id}")
        if position.fills and fill.recorded_at < position.fills[-1].recorded_at:
            raise InvalidOrderTransitionError("fill events must be applied in recorded order")
