"""Regime data model.

See docs/specifications/PHASE-5-market-regime.md section 2, 5, 6.

Both types are `@dataclass(frozen=True)` -- the same language-enforced
immutability discipline Phase 1 (`data_infra.models`), Phase 2
(`backtest.orders.Order`, `backtest.fills.Fill`), and Phase 3
(`trade_journal.models`) already established, continued here rather than
introduced fresh (ADR-0009's reasoning applies identically: a Regime
observation is part of this project's permanent, reproducible record of
"what did the system know," and must not be silently editable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from regime.enums import RegimeAxis, SubjectKind

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class RegimeObservation:
    """One axis's classification for one subject at one point in time.

    `timestamp` and `as_of_time` are kept as two distinct fields, per the
    instruction's explicit minimum field list, mirroring Phase 1's
    `event_time`/`available_time` distinction (ADR-0004) even though the
    reference implementation always sets them equal -- a Regime
    observation is computed *at* decision time, not backfilled from an
    earlier event, so there is currently no scenario where they differ;
    the schema keeps them separate so a future producer that *does*
    backfill (e.g., a corrected/restated regime run) does not need a
    schema change.
    """

    regime_id: str  # "REG-000001"
    axis: RegimeAxis
    subject_id: str
    subject_kind: SubjectKind
    timestamp: datetime
    as_of_time: datetime
    state: str  # the winning axis-specific enum member's .value -- see regime.enums.AXIS_STATE_ENUM
    value: Optional[float]  # the underlying numeric feature (None when state is UNKNOWN)
    definition: str  # method identifier, e.g. "trend_ma_crossover_v1"
    reliability: float  # data-completeness ratio in [0, 1] -- never a fabricated ML confidence
    lookback_days: int
    feature_version: str
    data_version: tuple[str, ...]
    method_version: str
    configuration_version: str
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.regime_id:
            raise ValueError("RegimeObservation.regime_id must not be empty")
        if not self.subject_id:
            raise ValueError("RegimeObservation.subject_id must not be empty")
        _require_aware("RegimeObservation.timestamp", self.timestamp)
        _require_aware("RegimeObservation.as_of_time", self.as_of_time)
        if not 0.0 <= self.reliability <= 1.0:
            raise ValueError(f"RegimeObservation.reliability must be in [0, 1]: {self.reliability!r}")


@dataclass(frozen=True)
class CompositeRegimeObservation:
    """A single point-in-time snapshot composing every axis's independent
    observation (Phase 5 spec section 6) plus, for a small curated set of
    combinations only, a human-readable composite label (e.g.
    "BULL_HIGH_VOL"). `composite_label` is `None` for any combination not
    in that curated set -- never a generated/concatenated label for every
    possible combination (Phase 5 spec section 6: "가능한 상태 조합을
    무한히 늘리지 않는다")."""

    composite_id: str  # "CREG-000001"
    subject_id: str
    subject_kind: SubjectKind
    as_of_time: datetime
    axes: dict[RegimeAxis, RegimeObservation] = field(default_factory=dict)
    composite_label: Optional[str] = None
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.composite_id:
            raise ValueError("CompositeRegimeObservation.composite_id must not be empty")
        if not self.subject_id:
            raise ValueError("CompositeRegimeObservation.subject_id must not be empty")
        _require_aware("CompositeRegimeObservation.as_of_time", self.as_of_time)

    def get(self, axis: RegimeAxis) -> Optional[RegimeObservation]:
        return self.axes.get(axis)
