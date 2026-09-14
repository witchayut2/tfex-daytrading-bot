"""Causal structure and externally calibrated volatility regimes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.tfex.analysis.pivots import PivotType
from app.tfex.analysis.structure import StructureUpdate, SwingClassification, SwingRelation
from app.tfex.errors import ReplayError
from app.tfex.marketdata.models import BarInterval

__all__ = [
    "CompositeRegime",
    "StructureRegime",
    "StructureRegimeEngine",
    "StructureRegimeState",
    "VolatilityClassifier",
    "VolatilityFeature",
    "VolatilityObservation",
    "VolatilityRegime",
    "VolatilityRegimeState",
    "VolatilityThresholds",
]


class StructureRegime(StrEnum):
    BULLISH_STRUCTURE = "BULLISH_STRUCTURE"
    BEARISH_STRUCTURE = "BEARISH_STRUCTURE"
    CONTRACTION_STRUCTURE = "CONTRACTION_STRUCTURE"
    EXPANSION_STRUCTURE = "EXPANSION_STRUCTURE"
    UNRESOLVED = "UNRESOLVED"


class VolatilityFeature(StrEnum):
    ATR = "ATR"
    NORMALIZED_ATR = "NORMALIZED_ATR"
    REALIZED_RANGE = "REALIZED_RANGE"
    RELATIVE_VOLUME = "RELATIVE_VOLUME"


class VolatilityRegime(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    UNCALIBRATED = "UNCALIBRATED"


@dataclass(frozen=True, slots=True)
class StructureRegimeState:
    regime: StructureRegime
    latest_high_relation: SwingRelation
    latest_low_relation: SwingRelation
    event_time: datetime | None
    confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class VolatilityThresholds:
    threshold_id: str
    calibration_dataset_id: str
    calibrated_at: datetime
    feature: VolatilityFeature
    low_threshold: Decimal
    high_threshold: Decimal
    method: str

    def __post_init__(self) -> None:
        if not self.threshold_id or not self.calibration_dataset_id or not self.method:
            raise ValueError("volatility threshold provenance fields cannot be empty")
        if self.calibrated_at.tzinfo is None:
            raise ValueError("volatility calibrated_at must be timezone-aware")
        if self.low_threshold >= self.high_threshold:
            raise ValueError("volatility low_threshold must be below high_threshold")
        if self.low_threshold < 0:
            raise ValueError("volatility thresholds cannot be negative")


@dataclass(frozen=True, slots=True)
class VolatilityObservation:
    dataset_id: str
    feature: VolatilityFeature
    value: Decimal
    event_time: datetime
    confirmed_at: datetime

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("volatility observation requires a dataset_id")
        if self.event_time.tzinfo is None or self.confirmed_at.tzinfo is None:
            raise ValueError("volatility observation timestamps must be timezone-aware")
        if self.confirmed_at <= self.event_time:
            raise ValueError("volatility observation must confirm after its event")
        if self.value < 0:
            raise ValueError("volatility observations cannot be negative")


@dataclass(frozen=True, slots=True)
class VolatilityRegimeState:
    regime: VolatilityRegime
    feature: VolatilityFeature | None
    value: Decimal | None
    threshold_id: str | None
    calibration_dataset_id: str | None
    event_time: datetime | None
    confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CompositeRegime:
    structure: StructureRegimeState
    volatility: VolatilityRegimeState
    evaluated_at: datetime

    @property
    def label(self) -> str:
        return f"{self.structure.regime.value}+{self.volatility.regime.value}_VOLATILITY"


class StructureRegimeEngine:
    """Map only confirmed 15-minute swing relations to structural regimes."""

    def __init__(self) -> None:
        self._latest: dict[PivotType, SwingClassification] = {}
        self._last_event_time: datetime | None = None
        self._last_confirmed_at: datetime | None = None

    @property
    def state(self) -> StructureRegimeState:
        high = self._latest.get(PivotType.HIGH)
        low = self._latest.get(PivotType.LOW)
        high_relation = high.relation if high is not None else SwingRelation.UNCLASSIFIED
        low_relation = low.relation if low is not None else SwingRelation.UNCLASSIFIED
        return StructureRegimeState(
            regime=_map_structure_regime(high_relation, low_relation),
            latest_high_relation=high_relation,
            latest_low_relation=low_relation,
            event_time=self._last_event_time,
            confirmed_at=self._last_confirmed_at,
        )

    def update(self, update: StructureUpdate) -> StructureRegimeState:
        if update.timeframe is not BarInterval.FIFTEEN_MINUTE:
            raise ReplayError("structure regime accepts only confirmed 15m structure")
        for swing in update.new_swings:
            if swing.timeframe is not BarInterval.FIFTEEN_MINUTE:
                raise ReplayError("structure regime received a non-15m swing")
            self._latest[swing.pivot_type] = swing
            self._last_event_time = swing.event_time
            self._last_confirmed_at = swing.confirmed_at
        return self.state


class VolatilityClassifier:
    """Apply declared thresholds; this class deliberately has no fitting method."""

    @staticmethod
    def classify(
        observation: VolatilityObservation | None,
        thresholds: VolatilityThresholds | None,
        *,
        evaluation_dataset_id: str | None = None,
    ) -> VolatilityRegimeState:
        if observation is None or thresholds is None:
            return VolatilityRegimeState(
                regime=VolatilityRegime.UNCALIBRATED,
                feature=observation.feature if observation is not None else None,
                value=observation.value if observation is not None else None,
                threshold_id=None,
                calibration_dataset_id=None,
                event_time=observation.event_time if observation is not None else None,
                confirmed_at=observation.confirmed_at if observation is not None else None,
            )
        if evaluation_dataset_id is None or observation.dataset_id != evaluation_dataset_id:
            raise ReplayError("volatility classification requires its evaluation dataset identity")
        if thresholds.calibration_dataset_id == evaluation_dataset_id:
            raise ReplayError("volatility thresholds cannot be calibrated on evaluation data")
        if thresholds.feature is not observation.feature:
            raise ReplayError("volatility threshold feature does not match the observation")
        if thresholds.calibrated_at > observation.confirmed_at:
            raise ReplayError("future-calibrated volatility thresholds are not causal")
        regime = (
            VolatilityRegime.LOW
            if observation.value < thresholds.low_threshold
            else VolatilityRegime.HIGH
            if observation.value > thresholds.high_threshold
            else VolatilityRegime.NORMAL
        )
        return VolatilityRegimeState(
            regime=regime,
            feature=observation.feature,
            value=observation.value,
            threshold_id=thresholds.threshold_id,
            calibration_dataset_id=thresholds.calibration_dataset_id,
            event_time=observation.event_time,
            confirmed_at=observation.confirmed_at,
        )


def _map_structure_regime(
    high: SwingRelation,
    low: SwingRelation,
) -> StructureRegime:
    mapping = {
        (SwingRelation.HH, SwingRelation.HL): StructureRegime.BULLISH_STRUCTURE,
        (SwingRelation.LH, SwingRelation.LL): StructureRegime.BEARISH_STRUCTURE,
        (SwingRelation.LH, SwingRelation.HL): StructureRegime.CONTRACTION_STRUCTURE,
        (SwingRelation.HH, SwingRelation.LL): StructureRegime.EXPANSION_STRUCTURE,
    }
    return mapping.get((high, low), StructureRegime.UNRESOLVED)
