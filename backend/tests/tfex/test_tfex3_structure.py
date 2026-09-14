"""TFEX-3 causal market-structure and liquidity acceptance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.tfex.analysis.engine import Tfex3Engine, analysis_digest
from app.tfex.analysis.fvg import FvgEngine, FvgStatus
from app.tfex.analysis.models import AnalysisBar
from app.tfex.analysis.pivots import ConfirmedPivot, PivotEngine, PivotRule, PivotType
from app.tfex.analysis.structure import (
    BreakDirection,
    BreakKind,
    MarketStructureEngine,
    StructureBias,
    SwingRelation,
)
from app.tfex.liquidity.engine import LiquidityEngine
from app.tfex.liquidity.levels import LiquidityLevelSource, LiquidityLevelStatus
from app.tfex.liquidity.sweep import apply_interaction
from app.tfex.marketdata.models import Bar, BarInterval
from app.tfex.marketdata.replay import ReplayEngine
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine

BANGKOK = ZoneInfo("Asia/Bangkok")
DAY = date(2026, 9, 8)
SYMBOL = "S50Z26"
RULE = PivotRule(left_bars=1, right_bars=1, rule_id="TEST_STRICT_1X1")


def _analysis_bar(
    sequence: int,
    close: str | int,
    *,
    high: str | int | None = None,
    low: str | int | None = None,
    open_: str | int | None = None,
    timeframe: BarInterval = BarInterval.ONE_MINUTE,
    minute: int | None = None,
) -> AnalysisBar:
    minutes = timeframe.minutes
    offset = sequence - 1 if minute is None else minute
    open_time = datetime.combine(DAY, time(9, 45), tzinfo=BANGKOK) + timedelta(minutes=offset)
    close_value = Decimal(str(close))
    open_value = Decimal(str(open_ if open_ is not None else close))
    high_value = Decimal(str(high if high is not None else max(open_value, close_value)))
    low_value = Decimal(str(low if low is not None else min(open_value, close_value)))
    return AnalysisBar(
        symbol=SYMBOL,
        timeframe=timeframe,
        source_sequence=sequence,
        session=ContinuousSession.MORNING,
        open_time=open_time,
        event_time=open_time + timedelta(minutes=minutes - 1),
        confirmed_at=open_time + timedelta(minutes=minutes),
        open=open_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=1,
    )


def _source_bars(count: int) -> list[Bar]:
    first = datetime.combine(DAY, time(9, 45), tzinfo=BANGKOK)
    pattern = (Decimal("900.0"), Decimal("901.0"), Decimal("899.5"), Decimal("902.0"))
    bars: list[Bar] = []
    for index in range(count):
        close = pattern[index % len(pattern)] + Decimal(index // len(pattern)) / Decimal(10)
        bars.append(
            Bar(
                symbol=SYMBOL,
                timestamp=first + timedelta(minutes=index),
                open=close,
                high=close + Decimal("0.2"),
                low=close - Decimal("0.2"),
                close=close,
                volume=index + 1,
            )
        )
    return bars


@pytest.mark.anti_repaint
def test_high_and_low_pivots_are_delayed_until_right_evidence_closes() -> None:
    high_engine = PivotEngine(
        BarInterval.ONE_MINUTE,
        PivotRule(left_bars=2, right_bars=2, rule_id="DELAY_TEST"),
    )
    high_bars = [_analysis_bar(index, value) for index, value in enumerate((1, 2, 5, 3, 2), 1)]
    for bar in high_bars[:4]:
        assert high_engine.update(bar) == ()
    high = high_engine.update(high_bars[4])
    assert len(high) == 1 and high[0].pivot_type is PivotType.HIGH
    assert high[0].event_time == high_bars[2].event_time
    assert high[0].confirmed_at == high_bars[4].confirmed_at
    assert high[0].confirmed_at > high[0].event_time

    low_engine = PivotEngine(
        BarInterval.ONE_MINUTE,
        PivotRule(left_bars=2, right_bars=2, rule_id="DELAY_TEST"),
    )
    low_bars = [_analysis_bar(index, value) for index, value in enumerate((5, 4, 1, 3, 4), 1)]
    for bar in low_bars[:4]:
        assert low_engine.update(bar) == ()
    low = low_engine.update(low_bars[4])
    assert len(low) == 1 and low[0].pivot_type is PivotType.LOW
    assert low[0].event_time == low_bars[2].event_time
    assert low[0].confirmed_at == low_bars[4].confirmed_at


@pytest.mark.anti_repaint
@pytest.mark.parametrize("timeframe", [BarInterval.FIVE_MINUTE, BarInterval.FIFTEEN_MINUTE])
def test_higher_timeframe_pivots_wait_for_a_later_closed_higher_timeframe_bar(
    timeframe: BarInterval,
) -> None:
    engine = PivotEngine(timeframe, RULE)
    bars = [
        _analysis_bar(
            index,
            value,
            timeframe=timeframe,
            minute=(index - 1) * timeframe.minutes,
        )
        for index, value in enumerate((10, 15, 11), 1)
    ]
    assert engine.update(bars[0]) == ()
    assert engine.update(bars[1]) == ()
    pivot = engine.update(bars[2])
    assert len(pivot) == 1
    assert pivot[0].timeframe is timeframe
    assert pivot[0].event_time == bars[1].event_time
    assert pivot[0].confirmed_at == bars[2].confirmed_at


@pytest.mark.anti_repaint
def test_swing_labels_bos_and_choch_use_only_confirmed_structure() -> None:
    engine = MarketStructureEngine(BarInterval.ONE_MINUTE, RULE)
    updates = [
        engine.update(_analysis_bar(index, value))
        for index, value in enumerate((10, 15, 11, 16, 12, 14, 10, 13, 9, 14), 1)
    ]
    relations = {swing.relation for update in updates for swing in update.new_swings}
    assert {SwingRelation.HH, SwingRelation.HL, SwingRelation.LH, SwingRelation.LL} <= relations
    assert engine.bias is StructureBias.STRUCTURE_BEARISH

    breaks = [event for update in updates for event in update.new_breaks]
    assert any(event.kind is BreakKind.BOS for event in breaks)
    choch = [event for event in breaks if event.kind is BreakKind.CHOCH]
    assert len(choch) == 1
    assert choch[0].direction is BreakDirection.BULLISH
    assert choch[0].prior_structural_regime is StructureBias.STRUCTURE_BEARISH
    assert choch[0].confirmed_at == _analysis_bar(10, 14).confirmed_at
    assert choch[0].event_time < choch[0].confirmed_at


@pytest.mark.anti_repaint
def test_wick_touch_is_not_bos_and_close_break_is_causal() -> None:
    engine = MarketStructureEngine(BarInterval.ONE_MINUTE, RULE)
    engine.update(_analysis_bar(1, 10))
    engine.update(_analysis_bar(2, 14))
    confirmed = engine.update(_analysis_bar(3, 11))
    assert confirmed.new_pivots and confirmed.new_breaks == ()

    wick_only = engine.update(_analysis_bar(4, 13, high=15, low=10))
    assert wick_only.new_breaks == ()
    close_break = engine.update(_analysis_bar(5, 15, high=15, low=12))
    assert len(close_break.new_breaks) == 1
    event = close_break.new_breaks[0]
    assert event.kind is BreakKind.BOS
    assert event.break_basis == "STRICT_CLOSE_BEYOND_CONFIRMED_SWING_V1"
    assert event.broken_level_id == confirmed.new_pivots[0].pivot_id


def _pivot(number: int, price: str, pivot_type: PivotType) -> ConfirmedPivot:
    bar = _analysis_bar(number, price)
    return ConfirmedPivot(
        pivot_id=f"pivot:{number}:{pivot_type.value}",
        symbol=SYMBOL,
        pivot_type=pivot_type,
        timeframe=BarInterval.ONE_MINUTE,
        price=Decimal(price),
        source_bar_id=bar.bar_id,
        source_sequence=number,
        event_time=bar.event_time,
        confirmed_at=bar.confirmed_at,
        left_strength=1,
        right_strength=1,
        rule_id="TEST",
    )


@pytest.mark.anti_repaint
def test_equal_liquidity_and_reclaimed_sweep_are_neutral_and_delayed() -> None:
    liquidity = LiquidityEngine()
    first = _pivot(1, "100", PivotType.HIGH)
    second = _pivot(2, "100", PivotType.HIGH)
    liquidity.register_pivots((first,), created_at=first.confirmed_at)
    new = liquidity.register_pivots((second,), created_at=second.confirmed_at)
    assert any(level.source is LiquidityLevelSource.EQUAL_HIGHS for level in new)

    bar = _analysis_bar(3, 99, high=101, low=98)
    update = liquidity.observe(bar)
    assert update.interactions
    assert all(item.touched and item.exceeded and item.reclaimed for item in update.interactions)
    assert update.sweeps
    assert all(level.status is LiquidityLevelStatus.SWEPT for level in update.changed_levels)
    assert all(item.confirmed_at == bar.confirmed_at for item in update.sweeps)

    fresh = replace(new[0], level_id="wick-without-reclaim", status=LiquidityLevelStatus.ACTIVE)
    invalidating_bar = _analysis_bar(4, 101, high=102, low=99)
    updated, interaction, sweep = apply_interaction(fresh, invalidating_bar)
    assert interaction is not None and interaction.exceeded and not interaction.reclaimed
    assert sweep is None
    assert updated.status is LiquidityLevelStatus.INVALIDATED


@pytest.mark.anti_repaint
def test_fvg_requires_closed_third_bar_and_has_deterministic_lifecycle() -> None:
    engine = FvgEngine(BarInterval.ONE_MINUTE)
    first = _analysis_bar(1, 10, high=10, low=9)
    middle = _analysis_bar(2, 12, high=13, low=11)
    third = _analysis_bar(3, 12, high=12, low=11)
    assert engine.update(first).formed == ()
    assert engine.update(middle).formed == ()
    formed = engine.update(third).formed
    assert len(formed) == 1
    gap = formed[0]
    assert (gap.lower_bound, gap.upper_bound) == (Decimal("10"), Decimal("11"))
    assert gap.confirmed_at == third.confirmed_at
    assert gap.formation_event_time == third.event_time

    partial = engine.update(_analysis_bar(4, "10.8", high=12, low="10.5")).changed
    assert len(partial) == 1 and partial[0].status is FvgStatus.PARTIALLY_FILLED
    filled = engine.update(_analysis_bar(5, "10", high=11, low=10)).changed
    assert len(filled) == 1 and filled[0].status is FvgStatus.FILLED


@pytest.mark.anti_repaint
def test_tfex3_consumes_only_confirmed_5m_and_15m_bars(engine: SessionEngine) -> None:
    tfex2 = ReplayEngine(_source_bars(15), engine).run_to_end()
    tfex3 = Tfex3Engine(RULE).run(tfex2)
    assert [update.timeframe for update in tfex3.frames[3].structure_updates] == [
        BarInterval.ONE_MINUTE
    ]
    assert [update.timeframe for update in tfex3.frames[4].structure_updates] == [
        BarInterval.ONE_MINUTE,
        BarInterval.FIVE_MINUTE,
    ]
    assert [update.timeframe for update in tfex3.frames[14].structure_updates] == [
        BarInterval.ONE_MINUTE,
        BarInterval.FIVE_MINUTE,
        BarInterval.FIFTEEN_MINUTE,
    ]


@pytest.mark.anti_repaint
def test_batch_incremental_prefix_future_mutation_and_restart_are_stable(
    engine: SessionEngine,
) -> None:
    bars = _source_bars(45)
    tfex2 = ReplayEngine(bars, engine).run_to_end()
    processor = Tfex3Engine(RULE)
    batch = processor.run(tfex2)
    restarted = processor.run(tfex2)
    assert restarted == batch

    incremental = Tfex3Engine(RULE)
    for frame in tfex2.frames:
        incremental.update(frame)
    one_at_a_time = incremental.result()
    assert one_at_a_time.frames == batch.frames
    assert analysis_digest(one_at_a_time.frames) == batch.digest

    cutoff = 25
    prefix_engine = Tfex3Engine(RULE)
    for frame in tfex2.frames[:cutoff]:
        prefix_engine.update(frame)
    assert prefix_engine.frames == batch.frames[:cutoff]

    mutated = list(bars)
    future = mutated[35]
    mutated[35] = replace(
        future,
        high=future.high + Decimal("20"),
        close=future.close + Decimal("10"),
    )
    changed_tfex2 = ReplayEngine(mutated, engine).run_to_end()
    changed = Tfex3Engine(RULE).run(changed_tfex2)
    assert changed.frames[:cutoff] == batch.frames[:cutoff]
    assert changed.digest != batch.digest


@pytest.mark.anti_repaint
def test_final_session_levels_do_not_leak_before_session_close(engine: SessionEngine) -> None:
    tfex2 = ReplayEngine(_source_bars(165), engine).run_to_end()
    tfex3 = Tfex3Engine(RULE).run(tfex2)
    before_close = [
        level
        for frame in tfex3.frames[:164]
        for level in frame.new_liquidity_levels
        if level.source in {LiquidityLevelSource.MORNING_HIGH, LiquidityLevelSource.MORNING_LOW}
    ]
    assert before_close == []
    at_close = {
        level.source
        for level in tfex3.frames[164].new_liquidity_levels
        if level.source in {LiquidityLevelSource.MORNING_HIGH, LiquidityLevelSource.MORNING_LOW}
    }
    assert at_close == {LiquidityLevelSource.MORNING_HIGH, LiquidityLevelSource.MORNING_LOW}


@pytest.mark.anti_repaint
def test_opening_range_liquidity_appears_only_at_the_range_close(engine: SessionEngine) -> None:
    tfex2 = ReplayEngine(_source_bars(6), engine).run_to_end()
    tfex3 = Tfex3Engine(RULE).run(tfex2)
    opening_sources = {
        LiquidityLevelSource.OPENING_RANGE_HIGH,
        LiquidityLevelSource.OPENING_RANGE_LOW,
    }
    assert all(
        level.source not in opening_sources
        for frame in tfex3.frames[:4]
        for level in frame.new_liquidity_levels
    )
    at_five_minute_close = {
        level.source
        for level in tfex3.frames[4].new_liquidity_levels
        if level.source in opening_sources
    }
    assert at_five_minute_close == opening_sources


def test_tfex3_preserves_raw_symbol_and_bangkok_timezone_and_has_no_order_surface(
    engine: SessionEngine,
) -> None:
    run = Tfex3Engine(RULE).run(ReplayEngine(_source_bars(20), engine).run_to_end())
    assert run.symbol == SYMBOL
    assert {pivot.symbol for pivot in run.pivots} <= {SYMBOL}
    assert all(frame.confirmed_at.tzinfo == BANGKOK for frame in run.frames)
    forbidden = {"place_order", "change_order", "cancel_order", "submit_order"}
    assert forbidden.isdisjoint(dir(Tfex3Engine))
