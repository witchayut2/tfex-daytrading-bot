"""Locked Order Block, regime, and liquidity-importance definitions for TFEX-3."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.tfex.analysis.engine import Tfex3Engine
from app.tfex.analysis.models import AnalysisBar
from app.tfex.analysis.order_blocks import (
    OrderBlockDirection,
    OrderBlockEngine,
    OrderBlockSelectionOutcome,
    OrderBlockStatus,
    OrderBlockUpdate,
)
from app.tfex.analysis.pivots import ConfirmedPivot, PivotRule, PivotType
from app.tfex.analysis.regime import (
    StructureRegime,
    StructureRegimeEngine,
    VolatilityClassifier,
    VolatilityFeature,
    VolatilityObservation,
    VolatilityRegime,
    VolatilityThresholds,
)
from app.tfex.analysis.structure import (
    BreakDirection,
    BreakKind,
    MarketStructureEngine,
    StructureBias,
    StructureBreak,
    StructureUpdate,
    SwingClassification,
    SwingRelation,
)
from app.tfex.errors import ReplayError
from app.tfex.liquidity.engine import LiquidityEngine
from app.tfex.liquidity.importance import (
    LiquidityImportanceEngine,
    LiquidityImportanceVector,
    PartialOrder,
)
from app.tfex.liquidity.levels import LiquidityLevelSource, LiquidityLevelStatus
from app.tfex.liquidity.sweep import apply_interaction
from app.tfex.marketdata.models import Bar, BarInterval
from app.tfex.marketdata.replay import ReplayEngine
from app.tfex.sessions.boundaries import ContinuousSession
from app.tfex.sessions.engine import SessionEngine

BANGKOK = ZoneInfo("Asia/Bangkok")
DAY = date(2026, 9, 8)
SYMBOL = "S50U26"
RULE = PivotRule(left_bars=1, right_bars=1, rule_id="TFEX3_LOCK_TEST_1X1")


def _bar(
    sequence: int,
    open_: str,
    close: str,
    *,
    high: str | None = None,
    low: str | None = None,
    timeframe: BarInterval = BarInterval.ONE_MINUTE,
) -> AnalysisBar:
    open_time = datetime.combine(DAY, time(9, 45), tzinfo=BANGKOK) + timedelta(
        minutes=(sequence - 1) * timeframe.minutes
    )
    open_value = Decimal(open_)
    close_value = Decimal(close)
    return AnalysisBar(
        symbol=SYMBOL,
        timeframe=timeframe,
        source_sequence=sequence,
        session=ContinuousSession.MORNING,
        open_time=open_time,
        event_time=open_time + timedelta(minutes=timeframe.minutes - 1),
        confirmed_at=open_time + timedelta(minutes=timeframe.minutes),
        open=open_value,
        high=Decimal(high) if high is not None else max(open_value, close_value),
        low=Decimal(low) if low is not None else min(open_value, close_value),
        close=close_value,
        volume=1,
    )


def _bos(
    bar: AnalysisBar,
    anchor: AnalysisBar,
    direction: BreakDirection,
    *,
    kind: BreakKind = BreakKind.BOS,
) -> StructureBreak:
    return StructureBreak(
        break_id=f"break:{direction.value}:{bar.bar_id}",
        kind=kind,
        direction=direction,
        symbol=bar.symbol,
        timeframe=bar.timeframe,
        broken_level_id=f"broken:{direction.value}",
        broken_price=Decimal("100"),
        anchor_pivot_id=f"anchor:{anchor.bar_id}",
        anchor_event_time=anchor.event_time,
        anchor_confirmed_at=anchor.confirmed_at,
        confirming_close=bar.close,
        break_basis="STRICT_CLOSE_BEYOND_CONFIRMED_SWING_V1",
        event_time=bar.event_time,
        confirmed_at=bar.confirmed_at,
        prior_structural_regime=StructureBias.STRUCTURE_RANGE,
    )


@pytest.mark.anti_repaint
def test_bullish_order_block_selects_last_bearish_candle_after_anchor() -> None:
    engine = OrderBlockEngine(BarInterval.ONE_MINUTE)
    anchor = _bar(1, "10", "10")
    first_bearish = _bar(2, "12", "11", high="12.2", low="10.8")
    engine.update(anchor, ())
    engine.update(first_bearish, ())
    engine.update(_bar(3, "11", "12"), ())
    last_bearish = _bar(4, "13", "12", high="13.2", low="11.8")
    engine.update(last_bearish, ())
    bos_bar = _bar(5, "12", "14")

    formed = engine.update(bos_bar, (_bos(bos_bar, anchor, BreakDirection.BULLISH),)).formed

    assert len(formed) == 1
    block = formed[0]
    assert block.direction is OrderBlockDirection.BULLISH
    assert block.source_bar_id == last_bearish.bar_id
    assert (block.lower_bound, block.upper_bound) == (last_bearish.low, last_bearish.high)
    assert block.event_time == last_bearish.event_time
    assert block.confirmed_at == bos_bar.confirmed_at


@pytest.mark.anti_repaint
def test_bearish_order_block_selects_last_bullish_candle_after_anchor() -> None:
    engine = OrderBlockEngine(BarInterval.ONE_MINUTE)
    anchor = _bar(1, "12", "12")
    engine.update(anchor, ())
    engine.update(_bar(2, "10", "11"), ())
    engine.update(_bar(3, "11", "10"), ())
    last_bullish = _bar(4, "10", "12", high="12.2", low="9.8")
    engine.update(last_bullish, ())
    bos_bar = _bar(5, "11", "9")

    formed = engine.update(bos_bar, (_bos(bos_bar, anchor, BreakDirection.BEARISH),)).formed

    assert len(formed) == 1
    assert formed[0].direction is OrderBlockDirection.BEARISH
    assert formed[0].source_bar_id == last_bullish.bar_id


@pytest.mark.anti_repaint
def test_order_block_is_absent_without_an_eligible_opposite_candle() -> None:
    engine = OrderBlockEngine(BarInterval.ONE_MINUTE)
    engine.update(_bar(1, "12", "11"), ())
    anchor = _bar(2, "10", "10")
    engine.update(anchor, ())
    engine.update(_bar(3, "11", "12"), ())
    bos_bar = _bar(4, "12", "13")
    result = engine.update(bos_bar, (_bos(bos_bar, anchor, BreakDirection.BULLISH),))
    assert result.formed == ()
    assert result.selections[0].outcome is OrderBlockSelectionOutcome.NO_ORDER_BLOCK


def test_choch_does_not_create_an_order_block() -> None:
    engine = OrderBlockEngine(BarInterval.ONE_MINUTE)
    anchor = _bar(1, "10", "10")
    source = _bar(2, "12", "11")
    bos_bar = _bar(3, "11", "13")
    engine.update(anchor, ())
    engine.update(source, ())
    assert (
        engine.update(
            bos_bar,
            (_bos(bos_bar, anchor, BreakDirection.BULLISH, kind=BreakKind.CHOCH),),
        ).formed
        == ()
    )


def test_structure_break_records_latest_confirmed_opposite_pivot_anchor() -> None:
    structure = MarketStructureEngine(BarInterval.ONE_MINUTE, RULE)
    bars = [
        _bar(1, "10", "10"),
        _bar(2, "14", "14"),
        _bar(3, "11", "11"),
        _bar(4, "9", "9"),
        _bar(5, "13", "12"),
        _bar(6, "14", "15"),
    ]
    updates = [structure.update(item) for item in bars]
    anchor = next(
        pivot
        for update in updates
        for pivot in update.new_pivots
        if pivot.pivot_type is PivotType.LOW
    )
    bullish_bos = next(
        event
        for update in updates
        for event in update.new_breaks
        if event.direction is BreakDirection.BULLISH
    )
    assert bullish_bos.anchor_pivot_id == anchor.pivot_id
    assert bullish_bos.anchor_event_time == anchor.event_time
    assert bullish_bos.anchor_confirmed_at == anchor.confirmed_at


@pytest.mark.anti_repaint
def test_order_block_is_not_visible_before_bos_and_lifecycle_uses_later_closes() -> None:
    engine = OrderBlockEngine(BarInterval.ONE_MINUTE)
    anchor = _bar(1, "10", "10")
    source = _bar(2, "12", "11", high="12", low="10")
    engine.update(anchor, ())
    before = engine.update(source, ())
    assert before.formed == () and engine.current == ()
    engine.update(_bar(3, "11", "13"), ())
    bos_bar = _bar(4, "13", "14")
    formed = engine.update(bos_bar, (_bos(bos_bar, anchor, BreakDirection.BULLISH),)).formed
    assert formed[0].status is OrderBlockStatus.ACTIVE

    mitigated = engine.update(_bar(5, "12.5", "12.2", low="11.5"), ()).changed
    assert mitigated[0].status is OrderBlockStatus.MITIGATED
    invalidated = engine.update(_bar(6, "10.5", "9.9", high="11", low="9.8"), ()).changed
    assert invalidated[0].status is OrderBlockStatus.INVALIDATED
    assert invalidated[0].mitigated_at == mitigated[0].mitigated_at
    assert invalidated[0].invalidated_at == _bar(6, "10.5", "9.9").confirmed_at


@pytest.mark.anti_repaint
def test_future_bos_and_future_mutation_cannot_change_confirmed_order_block_prefix() -> None:
    def process(bars: list[AnalysisBar]) -> tuple[OrderBlockUpdate, ...]:
        engine = OrderBlockEngine(BarInterval.ONE_MINUTE)
        anchor = bars[0]
        frames = []
        for index, item in enumerate(bars):
            events = (_bos(item, anchor, BreakDirection.BULLISH),) if index == 3 else ()
            frames.append(engine.update(item, events))
        return tuple(frames)

    original = [
        _bar(1, "10", "10"),
        _bar(2, "12", "11"),
        _bar(3, "11", "13"),
        _bar(4, "13", "14"),
        _bar(5, "15", "15"),
    ]
    assert all(not frame.formed for frame in process(original)[:3])
    mutated = [*original[:4], _bar(5, "30", "29", high="31", low="28")]
    assert process(original)[:4] == process(mutated)[:4]


def _swing(pivot_type: PivotType, relation: SwingRelation, sequence: int) -> SwingClassification:
    item = _bar(sequence, "10", "10", timeframe=BarInterval.FIFTEEN_MINUTE)
    return SwingClassification(
        structure_id=f"structure:{sequence}:{pivot_type.value}",
        pivot_id=f"pivot:{sequence}:{pivot_type.value}",
        previous_pivot_id=None,
        symbol=SYMBOL,
        timeframe=BarInterval.FIFTEEN_MINUTE,
        pivot_type=pivot_type,
        relation=relation,
        price=Decimal("10"),
        previous_price=Decimal("9"),
        event_time=item.event_time,
        confirmed_at=item.confirmed_at,
        bias_after=StructureBias.STRUCTURE_RANGE,
    )


def _regime_for(high: SwingRelation, low: SwingRelation) -> StructureRegime:
    engine = StructureRegimeEngine()
    update = StructureUpdate(
        timeframe=BarInterval.FIFTEEN_MINUTE,
        new_pivots=(),
        new_swings=(_swing(PivotType.HIGH, high, 1), _swing(PivotType.LOW, low, 2)),
        new_breaks=(),
        bias=StructureBias.STRUCTURE_RANGE,
    )
    return engine.update(update).regime


@pytest.mark.parametrize(
    ("high", "low", "expected"),
    [
        (SwingRelation.HH, SwingRelation.HL, StructureRegime.BULLISH_STRUCTURE),
        (SwingRelation.LH, SwingRelation.LL, StructureRegime.BEARISH_STRUCTURE),
        (SwingRelation.LH, SwingRelation.HL, StructureRegime.CONTRACTION_STRUCTURE),
        (SwingRelation.HH, SwingRelation.LL, StructureRegime.EXPANSION_STRUCTURE),
        (SwingRelation.EQUAL_HIGH, SwingRelation.HL, StructureRegime.UNRESOLVED),
    ],
)
def test_structure_regime_mapping_is_explicit(
    high: SwingRelation,
    low: SwingRelation,
    expected: StructureRegime,
) -> None:
    assert _regime_for(high, low) is expected


@pytest.mark.anti_repaint
def test_structure_regime_ignores_forming_15m_candles(engine: SessionEngine) -> None:
    first = datetime.combine(DAY, time(9, 45), tzinfo=BANGKOK)
    bars = [
        Bar(
            symbol=SYMBOL,
            timestamp=first + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1,
        )
        for index in range(14)
    ]
    run = Tfex3Engine(RULE).run(ReplayEngine(bars, engine).run_to_end())
    assert all(frame.regime.structure.regime is StructureRegime.UNRESOLVED for frame in run.frames)
    assert all(
        all(
            update.timeframe is not BarInterval.FIFTEEN_MINUTE for update in frame.structure_updates
        )
        for frame in run.frames
    )


def _volatility_evidence(value: str = "2") -> tuple[VolatilityObservation, VolatilityThresholds]:
    observed_at = datetime.combine(DAY, time(10), tzinfo=BANGKOK)
    observation = VolatilityObservation(
        dataset_id="evaluation-data",
        feature=VolatilityFeature.NORMALIZED_ATR,
        value=Decimal(value),
        event_time=observed_at,
        confirmed_at=observed_at + timedelta(minutes=15),
    )
    thresholds = VolatilityThresholds(
        threshold_id="threshold-v1",
        calibration_dataset_id="calibration-data",
        calibrated_at=observed_at - timedelta(days=1),
        feature=VolatilityFeature.NORMALIZED_ATR,
        low_threshold=Decimal("1"),
        high_threshold=Decimal("3"),
        method="DECLARED_CALIBRATION_V1",
    )
    return observation, thresholds


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.9", VolatilityRegime.LOW),
        ("1", VolatilityRegime.NORMAL),
        ("2", VolatilityRegime.NORMAL),
        ("3.1", VolatilityRegime.HIGH),
    ],
)
def test_volatility_regime_uses_explicit_supplied_thresholds(
    value: str,
    expected: VolatilityRegime,
) -> None:
    observation, thresholds = _volatility_evidence(value)
    state = VolatilityClassifier.classify(
        observation,
        thresholds,
        evaluation_dataset_id="evaluation-data",
    )
    assert state.regime is expected
    assert state.threshold_id == thresholds.threshold_id


def test_missing_volatility_thresholds_are_uncalibrated() -> None:
    observation, _ = _volatility_evidence()
    assert VolatilityClassifier.classify(observation, None).regime is VolatilityRegime.UNCALIBRATED


@pytest.mark.anti_repaint
def test_volatility_rejects_evaluation_data_and_future_calibration() -> None:
    observation, thresholds = _volatility_evidence()
    with pytest.raises(ReplayError, match="evaluation data"):
        VolatilityClassifier.classify(
            observation,
            replace(thresholds, calibration_dataset_id="evaluation-data"),
            evaluation_dataset_id="evaluation-data",
        )
    with pytest.raises(ReplayError, match="future-calibrated"):
        VolatilityClassifier.classify(
            observation,
            replace(thresholds, calibrated_at=observation.confirmed_at + timedelta(seconds=1)),
            evaluation_dataset_id="evaluation-data",
        )


def _pivot(sequence: int, price: str, pivot_type: PivotType) -> ConfirmedPivot:
    source = _bar(sequence, price, price)
    return ConfirmedPivot(
        pivot_id=f"pivot:{sequence}:{pivot_type.value}",
        symbol=SYMBOL,
        pivot_type=pivot_type,
        timeframe=BarInterval.ONE_MINUTE,
        price=Decimal(price),
        source_bar_id=source.bar_id,
        source_sequence=sequence,
        event_time=source.event_time,
        confirmed_at=source.confirmed_at,
        left_strength=1,
        right_strength=1,
        rule_id="TEST",
    )


@pytest.mark.anti_repaint
def test_liquidity_features_are_stable_and_exclude_unconfirmed_confluence() -> None:
    liquidity = LiquidityEngine()
    first = liquidity.register_pivots(
        (_pivot(1, "100", PivotType.HIGH),),
        created_at=_bar(1, "100", "100").confirmed_at,
    )[0]
    future = liquidity.register_pivots(
        (_pivot(3, "100", PivotType.HIGH),),
        created_at=_bar(3, "100", "100").confirmed_at,
    )[0]
    extractor = LiquidityImportanceEngine()
    as_of = _bar(2, "99", "99").confirmed_at
    forward = extractor.extract((future, first), as_of=as_of)
    reverse = extractor.extract((first, future), as_of=as_of)

    assert forward == reverse
    assert [item.level_id for item in forward] == sorted(item.level_id for item in forward)
    first_vector = next(item for item in forward if item.level_id == first.level_id)
    future_vector = next(item for item in forward if item.level_id == future.level_id)
    assert first_vector.is_confirmed and first_vector.confluence_count == 1
    assert not future_vector.is_confirmed and future_vector.confluence_count == 0


@pytest.mark.anti_repaint
def test_liquidity_importance_rejects_a_future_touch_or_sweep_revision() -> None:
    liquidity = LiquidityEngine()
    level = liquidity.register_pivots(
        (_pivot(1, "100", PivotType.HIGH),),
        created_at=_bar(1, "100", "100").confirmed_at,
    )[0]
    swept, interaction, _ = apply_interaction(level, _bar(3, "99", "99", high="101"))
    assert interaction is not None and swept.status is LiquidityLevelStatus.SWEPT
    with pytest.raises(ReplayError, match="later liquidity revision"):
        LiquidityImportanceEngine().extract(
            (swept,),
            as_of=_bar(2, "99", "99").confirmed_at,
        )


def test_liquidity_confluence_tolerance_is_explicit() -> None:
    liquidity = LiquidityEngine()
    levels = liquidity.register_pivots(
        (
            _pivot(1, "100.0", PivotType.HIGH),
            _pivot(2, "100.1", PivotType.HIGH),
        ),
        created_at=_bar(2, "100", "100").confirmed_at,
    )
    as_of = _bar(3, "100", "100").confirmed_at
    exact = LiquidityImportanceEngine().extract(levels, as_of=as_of)
    one_tick = LiquidityImportanceEngine(
        price_tolerance_ticks=1,
        tick_size=Decimal("0.1"),
    ).extract(levels, as_of=as_of)
    assert {item.confluence_count for item in exact} == {1}
    assert {item.confluence_count for item in one_tick} == {2}


def test_liquidity_importance_uses_partial_not_magic_total_order() -> None:
    confirmed_at = datetime.combine(DAY, time(10), tzinfo=BANGKOK)
    base = LiquidityImportanceVector(
        level_id="a",
        symbol=SYMBOL,
        is_confirmed=True,
        timeframe=BarInterval.FIVE_MINUTE,
        source_type=LiquidityLevelSource.CONFIRMED_SWING_HIGH,
        confluence_count=2,
        age_seconds=60,
        swept_state=LiquidityLevelStatus.ACTIVE,
        is_unswept=True,
        confirmed_at=confirmed_at,
        as_of=confirmed_at + timedelta(minutes=5),
    )
    weaker = replace(
        base,
        level_id="b",
        confluence_count=1,
        age_seconds=120,
        confirmed_at=confirmed_at - timedelta(minutes=1),
    )
    different_source = replace(
        weaker,
        level_id="c",
        source_type=LiquidityLevelSource.OPENING_RANGE_HIGH,
    )
    conflicting = replace(
        base,
        level_id="d",
        confluence_count=3,
        age_seconds=180,
        confirmed_at=confirmed_at - timedelta(minutes=2),
    )
    assert LiquidityImportanceEngine.compare(base, weaker) is PartialOrder.DOMINATES
    assert LiquidityImportanceEngine.compare(base, different_source) is PartialOrder.INCOMPARABLE
    assert LiquidityImportanceEngine.compare(base, conflicting) is PartialOrder.INCOMPARABLE


@pytest.mark.anti_repaint
def test_tfex3_order_blocks_remain_batch_incremental_and_restart_stable(
    engine: SessionEngine,
) -> None:
    first = datetime.combine(DAY, time(9, 45), tzinfo=BANGKOK)
    pattern = (Decimal("100"), Decimal("103"), Decimal("101"), Decimal("104"))
    bars = [
        Bar(
            symbol=SYMBOL,
            timestamp=first + timedelta(minutes=index),
            open=pattern[index % 4] + (Decimal("0.2") if index % 2 == 0 else Decimal("-0.2")),
            high=pattern[index % 4] + Decimal("0.5"),
            low=pattern[index % 4] - Decimal("0.5"),
            close=pattern[index % 4],
            volume=1,
        )
        for index in range(45)
    ]
    tfex2 = ReplayEngine(bars, engine).run_to_end()
    processor = Tfex3Engine(RULE)
    batch = processor.run(tfex2)
    assert processor.run(tfex2) == batch
    incremental = Tfex3Engine(RULE)
    for frame in tfex2.frames:
        incremental.update(frame)
    assert incremental.result() == batch
