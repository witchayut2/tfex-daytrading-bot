"""Deterministic contract-roll policy (`CLAUDE_TFEX.md` section 7).

Section 7 opens with the important part: day trading should use *the most liquid eligible
series*, not blindly the nearest calendar contract. So the roll is a liquidity decision
constrained by an expiry cutoff, not a date arithmetic exercise.

Three properties this implementation holds onto:

* **Confirmation is required for a voluntary roll.** Liquidity flips back and forth around
  the roll; switching on a single session's volume produces a contract that oscillates.
* **A forced roll is immediate.** When the current contract crosses the expiry cutoff there
  is nothing to confirm — waiting would leave the platform trading an ineligible series.
* **Every decision is persisted with the numbers that produced it.** Section 7 requires the
  exact roll decision to be recorded; a decision you cannot reconstruct is not auditable.

Positions are never spliced across contracts (:func:`assert_no_position_splice`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.config import TfexConfig
from app.tfex.contracts.metadata import ContractStatus
from app.tfex.errors import PositionSpliceError

__all__ = [
    "ContractLiquidity",
    "RollComparison",
    "RollDecision",
    "RollOutcome",
    "RollPolicy",
    "RollStateMachine",
    "assert_no_position_splice",
]

POLICY_VERSION = "roll-policy/1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContractLiquidity(_Frozen):
    """Observed liquidity for one contract over one session.

    Optional fields are genuinely optional: not every feed carries open interest or a
    reliable bid-ask spread. A criterion whose input is missing is skipped and recorded as
    skipped — never silently treated as passing.
    """

    symbol: str
    status: ContractStatus
    trading_days_to_expiry: int | None = None
    session_volume: int = Field(ge=0)
    rolling_volume: int | None = Field(default=None, ge=0)
    open_interest: int | None = Field(default=None, ge=0)
    bid_ask_spread_points: Decimal | None = Field(default=None, ge=0)


class RollOutcome(StrEnum):
    INITIAL_SELECTION = "INITIAL_SELECTION"
    """First contract chosen for a series. Not a roll — there was nothing to roll from."""

    HOLD = "HOLD"
    """Keep the current contract."""

    CONFIRMING = "CONFIRMING"
    """The next contract dominates, but not yet for enough consecutive sessions."""

    SWITCH = "SWITCH"
    """Voluntary roll: the next contract dominates and confirmation is complete."""

    FORCED_SWITCH = "FORCED_SWITCH"
    """The current contract is no longer eligible; roll immediately."""

    NO_ELIGIBLE_CONTRACT = "NO_ELIGIBLE_CONTRACT"
    """Neither contract may be traded. The caller must stop, not pick the least bad one."""

    DISABLED = "DISABLED"
    """Roll evaluation is switched off in configuration."""


class RollComparison(_Frozen):
    """Per-criterion verdict for a near-vs-next comparison."""

    volume_ratio: Decimal | None = None
    rolling_volume_ratio: Decimal | None = None
    volume_passes: bool | None = None
    rolling_volume_passes: bool | None = None
    open_interest_passes: bool | None = None
    spread_passes: bool | None = None
    expiry_passes: bool = False
    skipped_criteria: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    """Why a criterion has a verdict but no ratio — e.g. the near contract printed nothing."""

    @property
    def next_dominates(self) -> bool:
        """Session volume must actively pass; other criteria pass unless data contradicts them.

        Volume is mandatory rather than "skippable" because it is the evidence the roll is
        founded on. Without it there is nothing to dominate *with*, and a comparison where
        every criterion was skipped would otherwise vacuously succeed.
        """
        if not self.expiry_passes or self.volume_passes is not True:
            return False
        optional = (self.rolling_volume_passes, self.open_interest_passes, self.spread_passes)
        return all(check for check in optional if check is not None)


class RollDecision(_Frozen):
    """A persisted roll decision, complete with the evidence behind it (section 7.5)."""

    session_date: date
    decided_at: datetime
    outcome: RollOutcome
    current_symbol: str | None
    chosen_symbol: str | None
    near_symbol: str | None
    next_symbol: str | None
    reason: str
    consecutive_confirmations: int = 0
    required_confirmations: int = 1
    comparison: RollComparison | None = None
    near_liquidity: ContractLiquidity | None = None
    next_liquidity: ContractLiquidity | None = None
    policy_version: str = POLICY_VERSION

    @model_validator(mode="after")
    def _decided_at_is_aware(self) -> Self:
        if self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")
        return self

    @property
    def switched(self) -> bool:
        return self.outcome in {RollOutcome.SWITCH, RollOutcome.FORCED_SWITCH}


def assert_no_position_splice(
    previous_symbol: str | None, new_symbol: str | None, *, open_position_quantity: int
) -> None:
    """Refuse to carry a position across a contract change (section 7.6).

    Rolling a *position* is a trade: close one contract, open the other, with its own costs
    and its own audit trail. Silently relabelling the position would corrupt every per-
    contract statistic section 30 requires.
    """
    if open_position_quantity == 0:
        return
    if previous_symbol is None or new_symbol is None or previous_symbol == new_symbol:
        return
    raise PositionSpliceError(
        f"cannot switch the trading contract from {previous_symbol} to {new_symbol} while "
        f"{open_position_quantity} contract(s) remain open; close the position first "
        f"(CLAUDE_TFEX.md section 7)"
    )


class RollPolicy:
    """Stateless eligibility and dominance rules."""

    def __init__(self, config: TfexConfig) -> None:
        self._config = config

    @property
    def minimum_days_before_expiry(self) -> int:
        return self._config.roll.minimum_days_before_expiry

    def eligibility(self, liquidity: ContractLiquidity) -> tuple[bool, tuple[str, ...]]:
        """Section 7.1-7.2: exclude expired contracts and contracts past the expiry cutoff."""
        reasons: list[str] = []
        if liquidity.status in {ContractStatus.EXPIRED, ContractStatus.UNKNOWN}:
            reasons.append(f"{liquidity.symbol} status is {liquidity.status}")
        if liquidity.status is ContractStatus.PRE_LISTED:
            reasons.append(f"{liquidity.symbol} is not listed yet")
        if liquidity.trading_days_to_expiry is None:
            reasons.append(f"{liquidity.symbol} has no resolved time to expiry")
        elif liquidity.trading_days_to_expiry < self.minimum_days_before_expiry:
            reasons.append(
                f"{liquidity.symbol} has {liquidity.trading_days_to_expiry} trading day(s) to "
                f"expiry, below the cutoff of {self.minimum_days_before_expiry}"
            )
        return (not reasons), tuple(reasons)

    def compare(self, near: ContractLiquidity, next_: ContractLiquidity) -> RollComparison:
        """Section 7.3: compare the near and next contracts on the available criteria."""
        threshold = self._config.roll.volume_ratio_threshold
        skipped: list[str] = []
        notes: list[str] = []

        volume_ratio, volume_passes, volume_note = _volume_verdict(
            next_.session_volume, near.session_volume, threshold
        )
        if volume_passes is None:
            skipped.append("session_volume")
        if volume_note:
            notes.append(f"session_volume: {volume_note}")

        rolling_ratio: Decimal | None = None
        rolling_passes: bool | None = None
        if next_.rolling_volume is not None and near.rolling_volume is not None:
            rolling_ratio, rolling_passes, rolling_note = _volume_verdict(
                next_.rolling_volume, near.rolling_volume, threshold
            )
            if rolling_passes is None:
                skipped.append("rolling_volume")
            if rolling_note:
                notes.append(f"rolling_volume: {rolling_note}")
        else:
            skipped.append("rolling_volume")

        open_interest_passes: bool | None = None
        if next_.open_interest is not None and near.open_interest is not None:
            open_interest_passes = next_.open_interest > near.open_interest
        else:
            skipped.append("open_interest")

        spread_passes: bool | None = None
        if next_.bid_ask_spread_points is not None and near.bid_ask_spread_points is not None:
            spread_passes = next_.bid_ask_spread_points <= near.bid_ask_spread_points
        else:
            skipped.append("bid_ask_spread")

        near_eligible, _ = self.eligibility(near)
        next_eligible, _ = self.eligibility(next_)
        expiry_passes = next_eligible and (
            not near_eligible
            or (next_.trading_days_to_expiry or 0) > (near.trading_days_to_expiry or 0)
        )

        return RollComparison(
            volume_ratio=volume_ratio,
            rolling_volume_ratio=rolling_ratio,
            volume_passes=volume_passes,
            rolling_volume_passes=rolling_passes,
            open_interest_passes=open_interest_passes,
            spread_passes=spread_passes,
            expiry_passes=expiry_passes,
            skipped_criteria=tuple(skipped),
            notes=tuple(notes),
        )


def _volume_verdict(
    next_volume: int, near_volume: int, threshold: Decimal
) -> tuple[Decimal | None, bool | None, str | None]:
    """Compare two volumes: ``(ratio, passes, note)``.

    ``passes`` is ``None`` when the criterion cannot be judged at all. A zero near volume
    against real next volume is unambiguous dominance even though the ratio is undefined —
    recorded as a pass with a note rather than as an infinity that no store round-trips.
    """
    if near_volume == 0 and next_volume == 0:
        return None, None, "neither contract printed any volume"
    if near_volume == 0:
        return None, True, "the near contract printed no volume while the next one traded"
    ratio = Decimal(next_volume) / Decimal(near_volume)
    return ratio, ratio >= threshold, None


class RollStateMachine:
    """Tracks the traded contract across sessions and records every decision.

    One instance per traded series. Sessions must be fed in chronological order; feeding the
    same session twice would double-count a confirmation, so repeats are rejected.
    """

    def __init__(self, config: TfexConfig, *, initial_symbol: str | None = None) -> None:
        self._config = config
        self._policy = RollPolicy(config)
        self._current: str | None = initial_symbol
        self._confirmations = 0
        self._pending_target: str | None = None
        self._history: list[RollDecision] = []
        self._last_session: date | None = None

    @property
    def current_symbol(self) -> str | None:
        return self._current

    @property
    def consecutive_confirmations(self) -> int:
        return self._confirmations

    @property
    def history(self) -> Sequence[RollDecision]:
        return tuple(self._history)

    def observe(
        self,
        *,
        session_date: date,
        decided_at: datetime,
        near: ContractLiquidity,
        next_: ContractLiquidity,
        open_position_quantity: int = 0,
    ) -> RollDecision:
        """Evaluate one session and return the decision, recording it in history."""
        if self._last_session is not None and session_date <= self._last_session:
            raise ValueError(
                f"sessions must be observed in chronological order; got {session_date} after "
                f"{self._last_session}"
            )
        self._last_session = session_date

        required = self._config.roll.confirmation_sessions
        if not self._config.roll.enabled:
            return self._record(
                RollDecision(
                    session_date=session_date,
                    decided_at=decided_at,
                    outcome=RollOutcome.DISABLED,
                    current_symbol=self._current,
                    chosen_symbol=self._current,
                    near_symbol=near.symbol,
                    next_symbol=next_.symbol,
                    reason="roll evaluation is disabled in configuration",
                    required_confirmations=required,
                )
            )

        near_eligible, near_reasons = self._policy.eligibility(near)
        next_eligible, next_reasons = self._policy.eligibility(next_)

        if not near_eligible and not next_eligible:
            self._reset_confirmations()
            return self._record(
                RollDecision(
                    session_date=session_date,
                    decided_at=decided_at,
                    outcome=RollOutcome.NO_ELIGIBLE_CONTRACT,
                    current_symbol=self._current,
                    chosen_symbol=None,
                    near_symbol=near.symbol,
                    next_symbol=next_.symbol,
                    reason="; ".join((*near_reasons, *next_reasons)),
                    required_confirmations=required,
                    near_liquidity=near,
                    next_liquidity=next_,
                )
            )

        if self._current is None:
            # Initial selection prefers the near contract when it is eligible: section 7
            # rolls *away* from the near month on evidence, it does not start on the far one.
            chosen = near.symbol if near_eligible else next_.symbol
            chosen_reasons = () if near_eligible else near_reasons
            self._current = chosen
            self._reset_confirmations()
            return self._record(
                RollDecision(
                    session_date=session_date,
                    decided_at=decided_at,
                    outcome=RollOutcome.INITIAL_SELECTION,
                    current_symbol=chosen,
                    chosen_symbol=chosen,
                    near_symbol=near.symbol,
                    next_symbol=next_.symbol,
                    reason=(
                        f"initial contract selection: {chosen}"
                        + (f" ({'; '.join(chosen_reasons)})" if chosen_reasons else "")
                    ),
                    required_confirmations=required,
                    near_liquidity=near,
                    next_liquidity=next_,
                )
            )

        current_is_near = self._current == near.symbol
        current_ineligible = current_is_near and not near_eligible

        if current_ineligible and next_eligible:
            # Forced roll: nothing to confirm, the current series cannot be traded.
            assert_no_position_splice(
                self._current, next_.symbol, open_position_quantity=open_position_quantity
            )
            reason = (
                "; ".join(near_reasons) if near_reasons else "no trading contract was selected yet"
            )
            self._current = next_.symbol
            self._reset_confirmations()
            return self._record(
                RollDecision(
                    session_date=session_date,
                    decided_at=decided_at,
                    outcome=RollOutcome.FORCED_SWITCH,
                    current_symbol=self._current,
                    chosen_symbol=next_.symbol,
                    near_symbol=near.symbol,
                    next_symbol=next_.symbol,
                    reason=f"forced roll to {next_.symbol}: {reason}",
                    required_confirmations=required,
                    near_liquidity=near,
                    next_liquidity=next_,
                )
            )

        comparison = self._policy.compare(near, next_)

        if not (next_eligible and comparison.next_dominates) or self._current == next_.symbol:
            self._reset_confirmations()
            return self._record(
                RollDecision(
                    session_date=session_date,
                    decided_at=decided_at,
                    outcome=RollOutcome.HOLD,
                    current_symbol=self._current,
                    chosen_symbol=self._current,
                    near_symbol=near.symbol,
                    next_symbol=next_.symbol,
                    reason=(
                        f"holding {self._current}: the next contract does not dominate "
                        f"(volume ratio {comparison.volume_ratio})"
                    ),
                    required_confirmations=required,
                    comparison=comparison,
                    near_liquidity=near,
                    next_liquidity=next_,
                )
            )

        if self._pending_target != next_.symbol:
            self._pending_target = next_.symbol
            self._confirmations = 0
        self._confirmations += 1

        if self._confirmations < required:
            return self._record(
                RollDecision(
                    session_date=session_date,
                    decided_at=decided_at,
                    outcome=RollOutcome.CONFIRMING,
                    current_symbol=self._current,
                    chosen_symbol=self._current,
                    near_symbol=near.symbol,
                    next_symbol=next_.symbol,
                    reason=(
                        f"{next_.symbol} dominates for {self._confirmations} of {required} "
                        f"required session(s)"
                    ),
                    consecutive_confirmations=self._confirmations,
                    required_confirmations=required,
                    comparison=comparison,
                    near_liquidity=near,
                    next_liquidity=next_,
                )
            )

        assert_no_position_splice(
            self._current, next_.symbol, open_position_quantity=open_position_quantity
        )
        confirmations = self._confirmations
        self._current = next_.symbol
        self._reset_confirmations()
        return self._record(
            RollDecision(
                session_date=session_date,
                decided_at=decided_at,
                outcome=RollOutcome.SWITCH,
                current_symbol=self._current,
                chosen_symbol=next_.symbol,
                near_symbol=near.symbol,
                next_symbol=next_.symbol,
                reason=(
                    f"rolled to {next_.symbol} after {confirmations} confirming session(s); "
                    f"volume ratio {comparison.volume_ratio}"
                ),
                consecutive_confirmations=confirmations,
                required_confirmations=required,
                comparison=comparison,
                near_liquidity=near,
                next_liquidity=next_,
            )
        )

    def _reset_confirmations(self) -> None:
        self._confirmations = 0
        self._pending_target = None

    def _record(self, decision: RollDecision) -> RollDecision:
        self._history.append(decision)
        return decision
