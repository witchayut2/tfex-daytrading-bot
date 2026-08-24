"""Contract roll policy and state machine (`CLAUDE_TFEX.md` section 7)."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app.tfex.config import TfexConfig
from app.tfex.contracts.metadata import ContractStatus
from app.tfex.contracts.registry import ContractRegistry
from app.tfex.contracts.roll import (
    ContractLiquidity,
    RollOutcome,
    RollPolicy,
    RollStateMachine,
    assert_no_position_splice,
)
from app.tfex.errors import PositionSpliceError
from tests.tfex.conftest import bkk

NEAR = "S50Z26"
NEXT = "S50H27"
SESSION = date(2026, 12, 21)
AT = bkk(SESSION, time(16, 55))


def liquidity(
    symbol: str,
    *,
    volume: int,
    days: int | None = 10,
    status: ContractStatus = ContractStatus.ACTIVE,
    rolling: int | None = None,
    open_interest: int | None = None,
    spread: str | None = None,
) -> ContractLiquidity:
    return ContractLiquidity(
        symbol=symbol,
        status=status,
        trading_days_to_expiry=days,
        session_volume=volume,
        rolling_volume=rolling,
        open_interest=open_interest,
        bid_ask_spread_points=Decimal(spread) if spread is not None else None,
    )


def machine(config: TfexConfig, *, confirmations: int = 1, **overrides: object) -> RollStateMachine:
    rolled = config.model_copy(
        update={
            "roll": config.roll.model_copy(
                update={"confirmation_sessions": confirmations, **overrides}
            )
        }
    )
    return RollStateMachine(rolled)


# --- eligibility ---------------------------------------------------------------------------


def test_an_expired_contract_is_never_eligible(config: TfexConfig) -> None:
    eligible, reasons = RollPolicy(config).eligibility(
        liquidity(NEAR, volume=100, status=ContractStatus.EXPIRED)
    )
    assert not eligible
    assert any("status is EXPIRED" in reason for reason in reasons)


def test_a_contract_inside_the_expiry_cutoff_is_not_eligible(config: TfexConfig) -> None:
    eligible, reasons = RollPolicy(config).eligibility(liquidity(NEAR, volume=100, days=1))
    assert not eligible
    assert any("below the cutoff of 2" in reason for reason in reasons)


def test_a_contract_with_unresolved_expiry_is_not_eligible(config: TfexConfig) -> None:
    eligible, reasons = RollPolicy(config).eligibility(liquidity(NEAR, volume=100, days=None))
    assert not eligible
    assert any("no resolved time to expiry" in reason for reason in reasons)


# --- dominance -----------------------------------------------------------------------------


def test_the_next_contract_must_clear_the_volume_ratio_threshold(config: TfexConfig) -> None:
    policy = RollPolicy(config)  # threshold 1.20

    below = policy.compare(liquidity(NEAR, volume=100), liquidity(NEXT, volume=119, days=100))
    at_threshold = policy.compare(
        liquidity(NEAR, volume=100), liquidity(NEXT, volume=120, days=100)
    )

    assert not below.volume_passes
    assert at_threshold.volume_passes
    assert at_threshold.volume_ratio == Decimal("1.2")


def test_criteria_without_data_are_recorded_as_skipped_not_passed(config: TfexConfig) -> None:
    comparison = RollPolicy(config).compare(
        liquidity(NEAR, volume=100), liquidity(NEXT, volume=200, days=100)
    )
    assert set(comparison.skipped_criteria) == {"rolling_volume", "open_interest", "bid_ask_spread"}
    assert comparison.open_interest_passes is None
    assert comparison.next_dominates


def test_a_failing_available_criterion_blocks_dominance(config: TfexConfig) -> None:
    comparison = RollPolicy(config).compare(
        liquidity(NEAR, volume=100, open_interest=90_000),
        liquidity(NEXT, volume=200, days=100, open_interest=10_000),
    )
    assert comparison.volume_passes
    assert comparison.open_interest_passes is False
    assert not comparison.next_dominates


def test_a_wider_spread_on_the_next_contract_blocks_the_roll(config: TfexConfig) -> None:
    comparison = RollPolicy(config).compare(
        liquidity(NEAR, volume=100, spread="0.1"),
        liquidity(NEXT, volume=500, days=100, spread="0.5"),
    )
    assert comparison.spread_passes is False
    assert not comparison.next_dominates


def test_a_dead_near_contract_counts_as_dominated_without_a_ratio(config: TfexConfig) -> None:
    """An undefined ratio must not become an infinity that no store round-trips."""
    comparison = RollPolicy(config).compare(
        liquidity(NEAR, volume=0), liquidity(NEXT, volume=5_000, days=100)
    )
    assert comparison.volume_ratio is None
    assert comparison.volume_passes is True
    assert comparison.next_dominates
    assert any("printed no volume" in note for note in comparison.notes)


def test_two_silent_contracts_produce_no_verdict_at_all(config: TfexConfig) -> None:
    comparison = RollPolicy(config).compare(
        liquidity(NEAR, volume=0), liquidity(NEXT, volume=0, days=100)
    )
    assert comparison.volume_ratio is None
    assert comparison.volume_passes is None
    assert "session_volume" in comparison.skipped_criteria
    assert not comparison.next_dominates


def test_a_comparison_with_no_volume_evidence_never_dominates(config: TfexConfig) -> None:
    """Every criterion skipped must not vacuously succeed."""
    comparison = RollPolicy(config).compare(
        liquidity(NEAR, volume=0), liquidity(NEXT, volume=0, days=100)
    )
    assert comparison.expiry_passes
    assert not comparison.next_dominates


# --- state machine -------------------------------------------------------------------------


def test_the_first_session_selects_the_near_contract_when_it_is_eligible(
    config: TfexConfig,
) -> None:
    """Section 7 rolls away from the near month on evidence; it does not start on the far one."""
    decision = machine(config).observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=500_000, days=100),
    )
    assert decision.outcome is RollOutcome.INITIAL_SELECTION
    assert decision.chosen_symbol == NEAR
    assert not decision.switched


def test_the_first_session_skips_an_ineligible_near_contract(config: TfexConfig) -> None:
    decision = machine(config).observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100, days=1),
        next_=liquidity(NEXT, volume=500, days=100),
    )
    assert decision.chosen_symbol == NEXT


def test_a_contract_is_held_while_the_next_one_does_not_dominate(config: TfexConfig) -> None:
    state = machine(config)
    state.observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    decision = state.observe(
        session_date=date(2026, 12, 22),
        decided_at=bkk(date(2026, 12, 22), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )

    assert decision.outcome is RollOutcome.HOLD
    assert state.current_symbol == NEAR


def test_a_single_confirming_session_is_enough_by_default(config: TfexConfig) -> None:
    state = machine(config, confirmations=1)
    state.observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    decision = state.observe(
        session_date=date(2026, 12, 22),
        decided_at=bkk(date(2026, 12, 22), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=200_000, days=100),
    )

    assert decision.outcome is RollOutcome.SWITCH
    assert decision.switched
    assert state.current_symbol == NEXT


def test_a_two_session_confirmation_requirement_delays_the_switch(config: TfexConfig) -> None:
    """Liquidity flips back and forth around the roll; one session is not evidence."""
    state = machine(config, confirmations=2)
    state.observe(
        session_date=date(2026, 12, 21),
        decided_at=bkk(date(2026, 12, 21), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )

    first = state.observe(
        session_date=date(2026, 12, 22),
        decided_at=bkk(date(2026, 12, 22), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=200_000, days=100),
    )
    assert first.outcome is RollOutcome.CONFIRMING
    assert first.consecutive_confirmations == 1
    assert state.current_symbol == NEAR

    second = state.observe(
        session_date=date(2026, 12, 23),
        decided_at=bkk(date(2026, 12, 23), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=200_000, days=100),
    )
    assert second.outcome is RollOutcome.SWITCH
    assert state.current_symbol == NEXT


def test_a_broken_run_of_dominance_resets_the_confirmation_count(config: TfexConfig) -> None:
    state = machine(config, confirmations=2)
    state.observe(
        session_date=date(2026, 12, 21),
        decided_at=bkk(date(2026, 12, 21), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    state.observe(
        session_date=date(2026, 12, 22),
        decided_at=bkk(date(2026, 12, 22), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=200_000, days=100),
    )
    assert state.consecutive_confirmations == 1

    state.observe(  # dominance lost
        session_date=date(2026, 12, 23),
        decided_at=bkk(date(2026, 12, 23), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    assert state.consecutive_confirmations == 0

    resumed = state.observe(
        session_date=date(2026, 12, 24),
        decided_at=bkk(date(2026, 12, 24), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=200_000, days=100),
    )
    assert resumed.outcome is RollOutcome.CONFIRMING
    assert state.current_symbol == NEAR


def test_an_ineligible_current_contract_forces_an_immediate_roll(config: TfexConfig) -> None:
    """Waiting for confirmation would leave the platform on a contract it may not trade."""
    state = machine(config, confirmations=3)
    state.observe(
        session_date=date(2026, 12, 21),
        decided_at=bkk(date(2026, 12, 21), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=1_000, days=100),
    )

    decision = state.observe(
        session_date=date(2026, 12, 28),
        decided_at=bkk(date(2026, 12, 28), time(16, 55)),
        near=liquidity(NEAR, volume=100_000, days=1),
        next_=liquidity(NEXT, volume=1_000, days=100),
    )

    assert decision.outcome is RollOutcome.FORCED_SWITCH
    assert decision.switched
    assert state.current_symbol == NEXT
    assert "below the cutoff" in decision.reason


def test_when_nothing_is_eligible_the_caller_is_told_to_stop(config: TfexConfig) -> None:
    decision = machine(config).observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=1, days=0),
        next_=liquidity(NEXT, volume=1, status=ContractStatus.EXPIRED),
    )
    assert decision.outcome is RollOutcome.NO_ELIGIBLE_CONTRACT
    assert decision.chosen_symbol is None


def test_disabling_the_roll_stops_evaluation(config: TfexConfig) -> None:
    disabled = config.model_copy(update={"roll": config.roll.model_copy(update={"enabled": False})})
    decision = RollStateMachine(disabled).observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100),
        next_=liquidity(NEXT, volume=100_000, days=100),
    )
    assert decision.outcome is RollOutcome.DISABLED


# --- audit and safety -------------------------------------------------------------------------


def test_every_decision_is_persisted_with_the_numbers_behind_it(config: TfexConfig) -> None:
    """Section 7.5: persist the exact roll decision."""
    state = machine(config)
    state.observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    state.observe(
        session_date=date(2026, 12, 22),
        decided_at=bkk(date(2026, 12, 22), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=200_000, days=100),
    )

    history = state.history
    assert [d.outcome for d in history] == [RollOutcome.INITIAL_SELECTION, RollOutcome.SWITCH]
    switch = history[-1]
    assert switch.comparison is not None
    assert switch.comparison.volume_ratio == Decimal(2)
    assert switch.near_liquidity is not None and switch.near_liquidity.session_volume == 100_000
    assert switch.next_liquidity is not None and switch.next_liquidity.session_volume == 200_000
    assert switch.policy_version == "roll-policy/1"
    assert switch.decided_at.tzinfo is not None


def test_rolling_with_an_open_position_is_refused(config: TfexConfig) -> None:
    """Section 7.6: do not splice positions across contracts."""
    state = machine(config)
    state.observe(
        session_date=SESSION,
        decided_at=AT,
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    with pytest.raises(PositionSpliceError, match="close the position first"):
        state.observe(
            session_date=date(2026, 12, 22),
            decided_at=bkk(date(2026, 12, 22), time(16, 55)),
            near=liquidity(NEAR, volume=100_000),
            next_=liquidity(NEXT, volume=200_000, days=100),
            open_position_quantity=2,
        )


def test_a_flat_book_may_roll_freely(config: TfexConfig) -> None:
    assert_no_position_splice(NEAR, NEXT, open_position_quantity=0)
    assert_no_position_splice(NEAR, NEAR, open_position_quantity=5)


def test_sessions_must_be_observed_in_order(config: TfexConfig) -> None:
    """Replaying a session twice would double-count a confirmation."""
    state = machine(config)
    state.observe(
        session_date=date(2026, 12, 22),
        decided_at=bkk(date(2026, 12, 22), time(16, 55)),
        near=liquidity(NEAR, volume=100_000),
        next_=liquidity(NEXT, volume=10_000, days=100),
    )
    with pytest.raises(ValueError, match="chronological order"):
        state.observe(
            session_date=date(2026, 12, 22),
            decided_at=bkk(date(2026, 12, 22), time(16, 55)),
            near=liquidity(NEAR, volume=100_000),
            next_=liquidity(NEXT, volume=10_000, days=100),
        )


def test_the_registry_records_roll_decisions_it_makes(registry: ContractRegistry) -> None:
    decision = registry.observe_roll_session(
        session_date=date(2026, 12, 1),
        as_of=bkk(date(2026, 12, 1), time(16, 55)),
    )
    assert decision.outcome is RollOutcome.INITIAL_SELECTION
    assert decision.chosen_symbol == "S50Z26"
    assert registry.rolled_symbol == "S50Z26"
    assert len(registry.roll_history) == 1


def test_the_registry_keeps_trading_the_rolled_contract(registry: ContractRegistry) -> None:
    registry.observe_roll_session(
        session_date=date(2026, 12, 1), as_of=bkk(date(2026, 12, 1), time(16, 55))
    )
    contract = registry.request_eligible_contract(as_of=bkk(date(2026, 12, 2), time(10, 0)))
    assert contract.normalized_symbol == "S50Z26"


def test_a_naive_decision_timestamp_is_rejected(config: TfexConfig) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        machine(config).observe(
            session_date=SESSION,
            decided_at=datetime(2026, 12, 21, 16, 55),
            near=liquidity(NEAR, volume=100),
            next_=liquidity(NEXT, volume=100, days=100),
        )
