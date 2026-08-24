"""The session state engine (`CLAUDE_TFEX.md` sections 8 and 9).

Joins the trading calendar to the phase layout and answers the two questions the rest of
the platform actually asks:

* *What state is the market in right now?*
* *Am I allowed to open a position right now?*

Section 9 lists five conditions that forbid opening a new position: pre-open, the midday
break, past the entry cutoff, past 16:30 on the last trading day, and *"while the calendar
is unknown or stale"*. That last one is why every gate here is fail-closed — a missing
holiday import produces a denial with a reason, never an optimistic default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from app.tfex.calendar.models import ContractExpiry
from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.errors import (
    CalendarError,
    SessionNotEligibleError,
    StaleMetadataError,
    UnverifiedMetadataError,
)
from app.tfex.sessions.boundaries import (
    DaySessionPlan,
    SessionState,
    build_day_plan,
)

__all__ = ["SessionEngine", "SessionGateDecision"]

_NO_EXPIRY_CONTEXT: Final = (
    "no contract expiry context supplied; section 6 requires the contract to come from the "
    "registry before any trading decision"
)


@dataclass(frozen=True, slots=True)
class SessionGateDecision:
    """An auditable allow/deny with every reason that contributed to it.

    Reasons accumulate rather than short-circuit: an operator reading the audit log should
    see *all* the reasons a trade was blocked, not just the first one hit.
    """

    allowed: bool
    evaluated_at: datetime
    state: SessionState
    reasons: tuple[str, ...] = ()
    plan: DaySessionPlan | None = None

    def __bool__(self) -> bool:
        return self.allowed

    def raise_if_denied(self) -> None:
        if not self.allowed:
            raise SessionNotEligibleError("; ".join(self.reasons) or "session gate denied")


class SessionEngine:
    """Session states and session-level trading gates for a configured market."""

    def __init__(self, config: TfexConfig, calendar: TradingCalendar) -> None:
        self._config = config
        self._calendar = calendar
        self._plan_cache: dict[tuple[date, date | None], DaySessionPlan] = {}

    @property
    def calendar(self) -> TradingCalendar:
        return self._calendar

    # --- plans ------------------------------------------------------------------------

    def plan_for(self, day: date, *, expiry: ContractExpiry | None = None) -> DaySessionPlan:
        """Phase layout for ``day``, in the context of one contract's expiry.

        The plan depends on the contract: the same calendar date is an ordinary session for
        the next-month contract and a 16:30 cessation day for the expiring one. The cache
        key includes the contract's last trading date for exactly that reason.
        """
        key = (day, expiry.last_trading_date if expiry else None)
        cached = self._plan_cache.get(key)
        if cached is not None:
            return cached

        is_trading_day = self._calendar.is_trading_day(day)
        is_last_trading_day = bool(expiry and expiry.last_trading_date == day)
        plan = build_day_plan(
            self._config,
            day,
            is_trading_day=is_trading_day,
            is_last_trading_day=is_last_trading_day,
            cessation_time=expiry.last_trading_time if expiry else None,
            shortened=self._calendar.shortened_session(day) if is_trading_day else None,
        )
        self._plan_cache[key] = plan
        return plan

    def plan_at(self, moment: datetime, *, expiry: ContractExpiry | None = None) -> DaySessionPlan:
        local = self._calendar.to_market_time(moment)
        return self.plan_for(local.date(), expiry=expiry)

    # --- state ------------------------------------------------------------------------

    def state_at(self, moment: datetime, *, expiry: ContractExpiry | None = None) -> SessionState:
        local = self._calendar.to_market_time(moment)
        return self.plan_at(local, expiry=expiry).state_at(local)

    def states_at(
        self, moment: datetime, *, expiry: ContractExpiry | None = None
    ) -> frozenset[SessionState]:
        """Every state active at ``moment`` — the midday break and afternoon pre-open overlap."""
        local = self._calendar.to_market_time(moment)
        return self.plan_at(local, expiry=expiry).states_at(local)

    def is_executable(self, moment: datetime, *, expiry: ContractExpiry | None = None) -> bool:
        """True only during a continuous session. Nothing may simulate a fill outside one."""
        local = self._calendar.to_market_time(moment)
        return self.plan_at(local, expiry=expiry).is_executable(local)

    # --- gates ------------------------------------------------------------------------

    def new_position_decision(
        self,
        moment: datetime,
        *,
        expiry: ContractExpiry | None = None,
        data_quality_ok: bool = True,
        data_quality_reason: str | None = None,
    ) -> SessionGateDecision:
        """May a *new* position be opened at ``moment``?

        Fail-closed on every axis: unknown calendar, stale metadata, missing contract
        context, wrong session, past cutoff. Exits are governed separately by
        :meth:`exit_decision` — being unable to enter must never mean being unable to leave.
        """
        reasons: list[str] = []

        try:
            local = self._calendar.to_market_time(moment)
        except ValueError as exc:
            return SessionGateDecision(False, moment, SessionState.CLOSED, (str(exc),))

        try:
            self._calendar.require_usable(local.date(), as_of=local)
        except (CalendarError, StaleMetadataError, UnverifiedMetadataError) as exc:
            # Section 9: no new positions "while the calendar is unknown or stale".
            return SessionGateDecision(
                False, local, SessionState.CLOSED, (f"calendar data unusable: {exc}",)
            )

        if expiry is None:
            reasons.append(_NO_EXPIRY_CONTEXT)

        plan = self.plan_for(local.date(), expiry=expiry)
        state = plan.state_at(local)
        active = plan.states_at(local)

        if not plan.is_trading_day:
            reasons.append(f"{local.date().isoformat()} is not a TFEX trading day")
        if SessionState.MORNING_PREOPEN in active or SessionState.AFTERNOON_PREOPEN in active:
            reasons.append("pre-open: indicative prices are not executable trades")
        if SessionState.MIDDAY_BREAK in active:
            reasons.append("midday break: the market is not matching trades")
        if plan.is_trading_day and not plan.is_executable(local):
            reasons.append(f"no continuous session is open (state {state})")
        if plan.entry_cutoff_at is not None and local >= plan.entry_cutoff_at:
            label = "last-trading-day entry cutoff" if plan.is_last_trading_day else "entry cutoff"
            reasons.append(f"past the {label} at {plan.entry_cutoff_at.time().isoformat()}")
        if SessionState.LAST_TRADING_DAY_CLOSING_WINDOW in active:
            reasons.append("inside the last-trading-day closing window")
        if plan.flatten_at is not None and local >= plan.flatten_at:
            reasons.append(f"past the end-of-day flatten time {plan.flatten_at.time().isoformat()}")
        if not data_quality_ok:
            reasons.append(data_quality_reason or "data-quality gate failed")

        return SessionGateDecision(not reasons, local, state, tuple(reasons), plan)

    def exit_decision(
        self, moment: datetime, *, expiry: ContractExpiry | None = None
    ) -> SessionGateDecision:
        """May an existing position be closed at ``moment``?

        Section 9 allows configurable exits where the exchange permits them but forbids
        fabricating execution during closed periods, so this permits exactly the continuous
        sessions — including the last-trading-day closing window, where exiting is the
        whole point.
        """
        local = self._calendar.to_market_time(moment)
        plan = self.plan_for(local.date(), expiry=expiry)
        state = plan.state_at(local)
        if plan.is_executable(local):
            return SessionGateDecision(True, local, state, (), plan)
        return SessionGateDecision(
            False,
            local,
            state,
            (f"no continuous session is open (state {state}); an exit cannot be fabricated",),
            plan,
        )

    def should_flatten(self, moment: datetime, *, expiry: ContractExpiry | None = None) -> bool:
        """True once end-of-day (or last-trading-day) flattening must be under way.

        Section 24 enables end-of-day flatten by default and requires the exit to be created
        *sufficiently before* the close, which is what ``flatten_at`` encodes.
        """
        local = self._calendar.to_market_time(moment)
        plan = self.plan_for(local.date(), expiry=expiry)
        if not plan.is_trading_day or plan.flatten_at is None or plan.afternoon_close_at is None:
            return False
        return plan.flatten_at <= local < plan.afternoon_close_at
