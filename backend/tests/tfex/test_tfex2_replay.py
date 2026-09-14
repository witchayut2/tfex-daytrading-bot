"""TFEX-2 deterministic replay, aggregation, and anti-repaint behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.tfex.errors import ReplayError
from app.tfex.feeds.base import MarketEvent, ReplayStatus
from app.tfex.feeds.csv_feed import load_csv_replay_input
from app.tfex.marketdata.manifest import build_manifest, save_manifest
from app.tfex.marketdata.models import Bar, BarInterval
from app.tfex.marketdata.replay import ReplayEngine, process_batch, replay_digest
from app.tfex.marketdata.vwap import VwapEngine
from app.tfex.sessions.boundaries import ContinuousSession, SessionState
from app.tfex.sessions.engine import SessionEngine
from app.tfex.sessions.gaps import GapKind, make_roll_gap
from app.tfex.sessions.opening_range import OpeningRangeEngine

BANGKOK = ZoneInfo("Asia/Bangkok")
DAY = date(2026, 9, 8)
NEXT_DAY = date(2026, 9, 9)
SYMBOL = "S50Z26"


def _bar(
    stamp: datetime,
    *,
    price: Decimal = Decimal("900.0"),
    high: Decimal | None = None,
    low: Decimal | None = None,
    close: Decimal | None = None,
    volume: int = 1,
    symbol: str = SYMBOL,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=stamp,
        open=price,
        high=high if high is not None else price,
        low=low if low is not None else price,
        close=close if close is not None else price,
        volume=volume,
    )


def _minutes(day: date, start: time, count: int, *, base: int = 900) -> list[Bar]:
    first = datetime.combine(day, start, tzinfo=BANGKOK)
    return [
        _bar(
            first + timedelta(minutes=index),
            price=Decimal(base) + Decimal(index % 20) / Decimal(10),
            high=Decimal(base) + Decimal(index % 20) / Decimal(10) + Decimal("0.2"),
            low=Decimal(base) + Decimal(index % 20) / Decimal(10) - Decimal("0.1"),
            close=Decimal(base) + Decimal(index % 20) / Decimal(10) + Decimal("0.1"),
            volume=index + 1,
        )
        for index in range(count)
    ]


def _full_day(day: date, *, base: int = 900) -> list[Bar]:
    return _minutes(day, time(9, 45), 165, base=base) + _minutes(
        day, time(13, 45), 190, base=base + 10
    )


def _event(bar: Bar, sequence: int, session: ContinuousSession) -> MarketEvent:
    return MarketEvent(
        sequence=sequence,
        bar=bar,
        event_time=bar.timestamp,
        confirmed_at=bar.timestamp + timedelta(minutes=1),
        session_state=(
            SessionState.MORNING_OPEN
            if session is ContinuousSession.MORNING
            else SessionState.AFTERNOON_OPEN
        ),
        continuous_session=session,
    )


def test_replay_controls_release_exactly_one_ordered_event_at_a_time(
    engine: SessionEngine,
) -> None:
    bars = _minutes(DAY, time(9, 45), 6)
    replay = ReplayEngine(bars, engine)

    replay.start()
    first = replay.next_event()
    assert first is not None
    assert first.event.sequence == 1
    assert first.event.event_time == bars[0].timestamp
    assert first.event.confirmed_at == bars[0].timestamp + timedelta(minutes=1)
    replay.pause()
    second = replay.step()
    assert second is not None and second.event.bar == bars[1]
    assert replay.cursor == 2

    replay.start()
    run = replay.run_to_end()
    assert replay.status.value == ReplayStatus.END_OF_DATA.value
    assert [frame.event.bar for frame in run.frames] == bars
    with pytest.raises(ReplayError, match="running replay"):
        replay.next_event()


def test_restart_and_reconstructive_seek_are_stable(engine: SessionEngine) -> None:
    bars = _minutes(DAY, time(9, 45), 20)
    replay = ReplayEngine(bars, engine)
    first = replay.run_to_end()

    replay.restart()
    second = replay.run_to_end()
    assert first == second

    reconstructed = ReplayEngine(bars, engine)
    last = reconstructed.seek(13)
    assert last == first.frames[12]
    assert reconstructed.history == first.frames[:13]
    assert reconstructed.status is ReplayStatus.PAUSED


def test_raw_contract_timezone_and_chronology_are_preserved(engine: SessionEngine) -> None:
    bars = _minutes(DAY, time(9, 45), 2)
    run = process_batch(bars, engine)
    assert {frame.event.bar.symbol for frame in run.frames} == {SYMBOL}
    assert all(frame.event.bar.timestamp.tzinfo == BANGKOK for frame in run.frames)

    with pytest.raises(ReplayError, match="raw contract changed"):
        ReplayEngine([bars[0], replace(bars[1], symbol="S50H27")], engine)
    with pytest.raises(ReplayError, match="strictly chronological"):
        ReplayEngine([bars[1], bars[0]], engine)
    with pytest.raises(ReplayError, match="timezone-aware"):
        ReplayEngine([replace(bars[0], timestamp=bars[0].timestamp.replace(tzinfo=None))], engine)


def test_manifest_aware_csv_replay_preserves_dataset_identity(
    tmp_path: Path,
    engine: SessionEngine,
) -> None:
    path = tmp_path / "s50z26.csv"
    path.write_text(
        "symbol,timestamp,open,high,low,close,volume\n"
        "S50Z26,2026-09-08T09:45:00+07:00,900,900.2,899.9,900.1,10\n"
        "S50Z26,2026-09-08T09:46:00+07:00,900.1,900.3,900,900.2,12\n",
        encoding="utf-8",
    )
    bars = [
        _bar(
            datetime(2026, 9, 8, 9, 45 + index, tzinfo=BANGKOK),
            price=Decimal("900") + Decimal(index) / Decimal(10),
            high=Decimal("900.2") + Decimal(index) / Decimal(10),
            low=Decimal("899.9") + Decimal(index) / Decimal(10),
            close=Decimal("900.1") + Decimal(index) / Decimal(10),
            volume=10 + index * 2,
        )
        for index in range(2)
    ]
    manifest = build_manifest(
        path,
        dataset_id="fixture-s50z26-2m",
        source="unit-test fixture",
        symbol=SYMBOL,
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        bars=bars,
        synthetic=True,
    )
    save_manifest(manifest, path)

    loaded = load_csv_replay_input(path)
    run = ReplayEngine.from_csv(path, engine).run_to_end()
    assert loaded.manifest.dataset_id == "fixture-s50z26-2m"
    assert run.dataset_id == loaded.manifest.dataset_id
    assert run.dataset_sha256 == loaded.manifest.sha256
    with pytest.raises(ReplayError, match="verified, non-synthetic"):
        load_csv_replay_input(path, require_real=True)


def test_5m_and_15m_buckets_are_session_aligned_and_never_bridge_lunch(
    engine: SessionEngine,
) -> None:
    run = process_batch(_full_day(DAY), engine)

    assert len(run.confirmed_5m) == 71
    assert len(run.confirmed_15m) == 24
    assert run.confirmed_5m[0].open_time.time() == time(9, 45)
    assert run.confirmed_5m[32].close_time.time() == time(12, 30)
    assert run.confirmed_5m[33].open_time.time() == time(13, 45)
    assert run.confirmed_15m[10].close_time.time() == time(12, 30)
    assert run.confirmed_15m[11].open_time.time() == time(13, 45)

    tail = run.confirmed_15m[-1]
    assert (tail.open_time.time(), tail.close_time.time()) == (time(16, 45), time(16, 55))
    assert tail.source_bar_count == tail.expected_source_bar_count == 10
    assert tail.is_short_session_close_bucket
    assert all(bar.is_closed and bar.confirmed_at == bar.close_time for bar in run.confirmed_15m)
    assert run.frames[164].event.session_state is SessionState.MORNING_OPEN
    assert run.frames[165].event.session_state is SessionState.AFTERNOON_OPEN
    assert run.frames[164].event.confirmed_at.time() == time(12, 30)
    assert run.frames[165].event.event_time.time() == time(13, 45)


@pytest.mark.anti_repaint
def test_forming_higher_timeframes_never_enter_confirmed_history(engine: SessionEngine) -> None:
    bars = _minutes(DAY, time(9, 45), 15)
    replay = ReplayEngine(bars, engine)
    replay.start()
    early = [replay.next_event() for _ in range(4)]
    assert all(frame is not None and frame.confirmed_5m is None for frame in early)
    assert replay.forming_5m is not None and not replay.forming_5m.is_closed
    assert replay.forming_5m.confirmed_at is None

    replay.next_event()
    confirmed_five = replay.confirmed_5m
    assert confirmed_five
    first_5m = confirmed_five[0]
    assert first_5m.confirmed_at == datetime(2026, 9, 8, 9, 50, tzinfo=BANGKOK)
    before_fifteen = [replay.next_event() for _ in range(9)]
    assert all(frame is not None and frame.confirmed_15m is None for frame in before_fifteen)
    fifteenth = replay.next_event()
    assert fifteenth is not None and fifteenth.confirmed_15m is not None
    confirmed_fifteen = replay.confirmed_15m
    assert len(confirmed_fifteen) == 1

    changed_future = list(bars)
    changed_future[8] = replace(changed_future[8], high=Decimal("999.9"))
    changed = process_batch(changed_future, engine)
    assert changed.confirmed_5m[0] == first_5m


def test_ohlcv_aggregation_is_deterministic(engine: SessionEngine) -> None:
    bars = [
        _bar(
            datetime(2026, 9, 8, 9, 45 + index, tzinfo=BANGKOK),
            price=Decimal("900.0") + index,
            high=Decimal("901.0") + index,
            low=Decimal("899.0") + index,
            close=Decimal("900.5") + index,
            volume=index + 1,
        )
        for index in range(5)
    ]
    result = process_batch(bars, engine).confirmed_5m[0]
    assert (result.open, result.high, result.low, result.close) == (
        Decimal("900.0"),
        Decimal("905.0"),
        Decimal("899.0"),
        Decimal("904.5"),
    )
    assert result.volume == 15


def test_missing_one_minute_constituents_fail_instead_of_being_filled(
    engine: SessionEngine,
) -> None:
    bars = _minutes(DAY, time(9, 45), 3)
    with pytest.raises(ReplayError, match="non-contiguous 1m input"):
        process_batch([bars[0], bars[2]], engine)

    complete_first_bucket = _minutes(DAY, time(9, 45), 5)
    after_whole_missing_bucket = _bar(datetime(2026, 9, 8, 9, 55, tzinfo=BANGKOK))
    with pytest.raises(ReplayError, match="non-contiguous 1m input"):
        process_batch([*complete_first_bucket, after_whole_missing_bucket], engine)


def test_vwap_uses_causal_hlc3_and_independent_session_resets(engine: SessionEngine) -> None:
    vwap = VwapEngine(engine)
    morning_1 = _bar(
        datetime(2026, 9, 8, 9, 45, tzinfo=BANGKOK),
        high=Decimal("903"),
        low=Decimal("900"),
        close=Decimal("900"),
        volume=2,
    )
    morning_2 = _bar(
        datetime(2026, 9, 8, 9, 46, tzinfo=BANGKOK),
        high=Decimal("906"),
        low=Decimal("903"),
        close=Decimal("903"),
        volume=1,
    )
    first = vwap.update(_event(morning_1, 1, ContinuousSession.MORNING))
    second = vwap.update(_event(morning_2, 2, ContinuousSession.MORNING))
    assert first.full_day.value == Decimal("901")
    assert second.full_day.value == Decimal("902")
    assert second.morning is not None and second.morning.value == Decimal("902")

    afternoon = _bar(
        datetime(2026, 9, 8, 13, 45, tzinfo=BANGKOK),
        price=Decimal("910"),
        volume=1,
    )
    third = vwap.update(_event(afternoon, 3, ContinuousSession.AFTERNOON))
    assert third.afternoon is not None and third.afternoon.value == Decimal("910")
    assert third.full_day.value == Decimal("904")

    next_day = replace(morning_1, timestamp=datetime(2026, 9, 9, 9, 45, tzinfo=BANGKOK))
    reset = vwap.update(_event(next_day, 4, ContinuousSession.MORNING))
    assert reset.full_day.cumulative_volume == 2
    assert reset.afternoon is None


def test_zero_volume_vwap_is_none_until_observed_volume_arrives(engine: SessionEngine) -> None:
    vwap = VwapEngine(engine)
    zero = _bar(
        datetime(2026, 9, 8, 9, 45, tzinfo=BANGKOK),
        price=Decimal("900"),
        volume=0,
    )
    first = vwap.update(_event(zero, 1, ContinuousSession.MORNING))
    assert first.full_day.value is None
    positive = replace(
        zero,
        timestamp=zero.timestamp + timedelta(minutes=1),
        open=Decimal("901"),
        high=Decimal("901"),
        low=Decimal("901"),
        close=Decimal("901"),
        volume=2,
    )
    second = vwap.update(_event(positive, 2, ContinuousSession.MORNING))
    assert second.full_day.value == Decimal("901")


@pytest.mark.anti_repaint
def test_opening_ranges_are_provisional_until_their_exact_close(engine: SessionEngine) -> None:
    opening = OpeningRangeEngine(engine)
    bars = _minutes(DAY, time(9, 45), 31)
    snapshot = None
    for index, bar in enumerate(bars[:4], start=1):
        snapshot = opening.update(_event(bar, index, ContinuousSession.MORNING))
    assert snapshot is not None
    provisional = snapshot.get(ContinuousSession.MORNING, 5)
    assert provisional is not None
    assert not provisional.is_confirmed
    assert provisional.confirmed_high is None and provisional.confirmed_at is None

    snapshot = opening.update(_event(bars[4], 5, ContinuousSession.MORNING))
    confirmed = snapshot.get(ContinuousSession.MORNING, 5)
    assert confirmed is not None and confirmed.is_confirmed
    assert confirmed.confirmed_at == datetime(2026, 9, 8, 9, 50, tzinfo=BANGKOK)
    fixed = (confirmed.confirmed_high, confirmed.confirmed_low)

    future = replace(bars[30], high=Decimal("999.9"), low=Decimal("800.0"))
    snapshot = opening.update(_event(future, 31, ContinuousSession.MORNING))
    unchanged = snapshot.get(ContinuousSession.MORNING, 5)
    assert unchanged is not None
    assert (unchanged.confirmed_high, unchanged.confirmed_low) == fixed


@pytest.mark.anti_repaint
def test_batch_incremental_prefix_and_future_mutation_are_equivalent(
    engine: SessionEngine,
) -> None:
    bars = _full_day(DAY) + _full_day(NEXT_DAY, base=920)
    batch = process_batch(bars, engine)

    incremental_engine = ReplayEngine(bars, engine)
    incremental_engine.start()
    while incremental_engine.status is ReplayStatus.RUNNING:
        incremental_engine.next_event()
    assert incremental_engine.history == batch.frames
    assert replay_digest(incremental_engine.history) == batch.digest

    prefix_length = 420
    prefix = process_batch(bars[:prefix_length], engine)
    assert prefix.frames == batch.frames[:prefix_length]

    mutated = list(bars)
    mutated[500] = replace(mutated[500], high=Decimal("1200.0"), close=Decimal("1199.9"))
    changed = process_batch(mutated, engine)
    assert changed.frames[:prefix_length] == batch.frames[:prefix_length]
    assert changed.digest != batch.digest


def test_reference_levels_distinguish_current_from_confirmed(engine: SessionEngine) -> None:
    first_day = _full_day(DAY)
    first_day[-1] = replace(first_day[-1], settlement_price=Decimal("911.0"))
    bars = first_day + _minutes(NEXT_DAY, time(9, 45), 1, base=930)
    run = process_batch(bars, engine)

    at_ten = run.frames[14].sessions.references
    assert at_ten.morning_current_high is not None
    assert at_ten.morning_confirmed_high is None
    assert at_ten.previous_day_high is None

    morning_close = run.frames[164].sessions.references
    assert morning_close.morning_confirmed_high is not None
    assert morning_close.confirmed_session_close is not None
    assert run.frames[164].vwap.morning is not None
    assert run.frames[164].vwap.morning.is_final
    assert not run.frames[164].vwap.full_day.is_final

    afternoon_open = run.frames[165].sessions.references
    assert afternoon_open.midday_gap is not None
    assert afternoon_open.morning_confirmed_close is not None
    afternoon_or = run.frames[169].opening_ranges.get(ContinuousSession.AFTERNOON, 5)
    assert afternoon_or is not None and afternoon_or.is_confirmed
    afternoon_or_15 = run.frames[179].opening_ranges.get(ContinuousSession.AFTERNOON, 15)
    afternoon_or_30 = run.frames[194].opening_ranges.get(ContinuousSession.AFTERNOON, 30)
    assert afternoon_or_15 is not None and afternoon_or_15.is_confirmed
    assert afternoon_or_30 is not None and afternoon_or_30.is_confirmed

    day_close = run.frames[354]
    assert day_close.vwap.afternoon is not None and day_close.vwap.afternoon.is_final
    assert day_close.vwap.full_day.is_final
    assert day_close.sessions.full_day.is_final

    next_open = run.frames[-1].sessions.references
    assert next_open.previous_day_open == run.frames[354].sessions.full_day.open
    assert next_open.previous_day_high == run.frames[354].sessions.full_day.high
    assert next_open.previous_day_close == run.frames[354].sessions.full_day.close
    assert next_open.previous_day_settlement == Decimal("911.0")
    assert next_open.previous_day_confirmed_at == datetime(2026, 9, 8, 16, 55, tzinfo=BANGKOK)
    assert next_open.overnight_gap_from_close is not None
    assert next_open.overnight_gap_from_close.points == (
        next_open.session_open - next_open.previous_day_close
    )
    assert next_open.overnight_gap_from_close.confirmed_at == datetime(
        2026, 9, 9, 9, 46, tzinfo=BANGKOK
    )
    assert next_open.overnight_gap_from_settlement is not None
    assert next_open.overnight_gap_from_settlement.points == Decimal("19.0")


def test_roll_gap_is_informational_and_keeps_both_raw_symbols() -> None:
    event_time = datetime(2026, 9, 30, 9, 45, tzinfo=BANGKOK)
    gap = make_roll_gap(
        outgoing_symbol="S50U26",
        outgoing_close=Decimal("930.0"),
        incoming_symbol="S50Z26",
        incoming_open=Decimal("932.5"),
        event_time=event_time,
        confirmed_at=event_time + timedelta(minutes=1),
    )
    assert gap.kind is GapKind.ROLL
    assert (gap.from_symbol, gap.to_symbol, gap.points) == (
        "S50U26",
        "S50Z26",
        Decimal("2.5"),
    )
    with pytest.raises(ReplayError, match="distinct raw contract"):
        make_roll_gap(
            outgoing_symbol="S50U26",
            outgoing_close=Decimal("930.0"),
            incoming_symbol="S50U26",
            incoming_open=Decimal("932.5"),
            event_time=event_time,
            confirmed_at=event_time + timedelta(minutes=1),
        )


def test_last_trading_day_replay_stops_at_the_verified_cessation(engine: SessionEngine) -> None:
    ltd = date(2026, 12, 29)
    allowed = _minutes(ltd, time(13, 45), 165)
    run = process_batch(allowed, engine)
    assert run.frames[-1].event.confirmed_at.time() == time(16, 30)
    assert run.frames[-1].event.session_state is SessionState.LAST_TRADING_DAY_CLOSING_WINDOW

    past_ltd_close = [
        *allowed,
        _bar(datetime(2026, 12, 29, 16, 30, tzinfo=BANGKOK)),
    ]
    with pytest.raises(ReplayError, match="outside TFEX trading"):
        process_batch(past_ltd_close, engine)


def test_replay_has_no_order_or_trading_activation_surface() -> None:
    forbidden = {
        "place_order",
        "change_order",
        "cancel_order",
        "submit_order",
        "enable_live_orders",
    }
    assert forbidden.isdisjoint(dir(ReplayEngine))
