"""RegimeDetector: orchestrates the five axis feature functions
(features.py) into `RegimeObservation`/`CompositeRegimeObservation`
records, sourcing all price/volume data exclusively through
`backtest.asof.AsOfDataView` -- the exact point-in-time-safe view
Strategy code already receives from `BacktestEngine` (Phase 2 spec
section 3.2). This is a deliberate reuse, not a new "safe view"
implementation: `AsOfDataView.get_bars`/`get_benchmark` are already
bound to `BacktestClock.current_time`, so a regime computed through this
class automatically inherits the same "no method exists to request a
later as_of_time" guarantee ADR-0004 established at the data layer and
Phase 2 section 3.2 re-established one layer up -- Regime does not need,
and does not implement, a third copy of that guard.

Because the sole input is `AsOfDataView`, `RegimeDetector.compute*` works
identically whether called from inside a live `BacktestEngine.run()` loop
(via the `data: AsOfDataView` a `Strategy.generate_orders` already
receives) or standalone, via `make_single_point_view()` below, which
constructs a one-checkpoint `BacktestClock`/`AsOfDataView` pair over an
arbitrary `DataRepository` -- reusing Phase 2's own types rather than
building a parallel "point-in-time repository view" concept (Phase 5
spec section 8).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from data_infra.repository import DataRepository

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from regime.config import RegimeConfig
from regime.enums import RegimeAxis, SubjectKind, VolatilityState
from regime.features import compute_correlation, compute_liquidity, compute_stress, compute_trend, compute_volatility
from regime.models import CompositeRegimeObservation, RegimeObservation
from regime.points import PricePoint, bars_to_price_points, benchmark_to_price_points

from trade_journal.enums import TradeProvenance

METHOD_VERSION = "phase5_baseline_regime_detector_v1"
FEATURE_VERSION = "phase5_regime_features_v1"

# A small, deliberately curated set of composite labels -- not every
# combination of axis states, per Phase 5 spec section 6.
_COMPOSITE_LABELS: dict[tuple, str] = {
    ("BULL", "LOW"): "BULL_LOW_VOL",
    ("BULL", "HIGH"): "BULL_HIGH_VOL",
    ("BULL", "EXTREME"): "BULL_HIGH_VOL",
    ("BEAR", "LOW"): "BEAR_LOW_VOL",
    ("BEAR", "HIGH"): "BEAR_HIGH_VOL",
    ("BEAR", "EXTREME"): "BEAR_HIGH_VOL",
}
_STRESS_OVERRIDE_LABELS: dict[str, str] = {
    "HIGH": "HIGH_STRESS",
}


def make_single_point_view(repository: DataRepository, as_of_time: datetime) -> AsOfDataView:
    """Builds an `AsOfDataView` fixed at a single checkpoint, for regime
    computation outside a live backtest loop (e.g., standalone historical
    analysis or replay). Reuses `backtest.clock.BacktestClock` verbatim --
    a `BacktestClock` with exactly one checkpoint is already a fully valid
    instance of that type (its own validation only requires "at least one
    checkpoint, strictly increasing" -- one checkpoint trivially
    satisfies both)."""
    return AsOfDataView(repository, BacktestClock((as_of_time,)))


class RegimeDetector:
    def __init__(self, config: RegimeConfig) -> None:
        self._config = config
        self._next_observation_id = 1
        self._next_composite_id = 1

    def _allocate_observation_id(self) -> str:
        oid = f"REG-{self._next_observation_id:06d}"
        self._next_observation_id += 1
        return oid

    def _allocate_composite_id(self) -> str:
        cid = f"CREG-{self._next_composite_id:06d}"
        self._next_composite_id += 1
        return cid

    def _fetch_points(
        self, data: AsOfDataView, subject_id: str, subject_kind: SubjectKind, lookback_days: int
    ) -> list[PricePoint]:
        start = data.current_time - timedelta(days=lookback_days)
        end = data.current_time
        if subject_kind == SubjectKind.SECURITY:
            return bars_to_price_points(data.get_bars(subject_id, start, end))
        return benchmark_to_price_points(data.get_benchmark(subject_id, start, end))

    def _lookback_days_for(self, axis: RegimeAxis) -> int:
        cfg = self._config
        if axis == RegimeAxis.TREND:
            return cfg.trend_long_window * 2
        if axis == RegimeAxis.VOLATILITY:
            return (cfg.volatility_window + cfg.volatility_percentile_window) * 2
        if axis == RegimeAxis.LIQUIDITY:
            return cfg.liquidity_baseline_window * 2
        if axis == RegimeAxis.CORRELATION:
            return cfg.correlation_window * 2
        if axis == RegimeAxis.STRESS:
            return cfg.stress_drawdown_window * 2
        raise ValueError(f"unknown axis: {axis!r}")

    def _build_observation(
        self,
        *,
        axis: RegimeAxis,
        subject_id: str,
        subject_kind: SubjectKind,
        as_of_time: datetime,
        state,
        value: Optional[float],
        reliability: float,
        lookback_days: int,
        data_version: tuple[str, ...],
        provenance: TradeProvenance,
        experiment_id: Optional[str],
    ) -> RegimeObservation:
        return RegimeObservation(
            regime_id=self._allocate_observation_id(),
            axis=axis,
            subject_id=subject_id,
            subject_kind=subject_kind,
            timestamp=as_of_time,
            as_of_time=as_of_time,
            state=state.value,
            value=value,
            definition=f"{axis.value.lower()}_{METHOD_VERSION}",
            reliability=reliability,
            lookback_days=lookback_days,
            feature_version=FEATURE_VERSION,
            data_version=data_version,
            method_version=METHOD_VERSION,
            configuration_version=self._config.configuration_version(),
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=as_of_time,
        )

    def compute_composite(
        self,
        data: AsOfDataView,
        subject_id: str,
        subject_kind: SubjectKind = SubjectKind.SECURITY,
        *,
        reference_id: Optional[str] = None,
        reference_kind: SubjectKind = SubjectKind.BENCHMARK,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> CompositeRegimeObservation:
        """Computes every axis for one subject as of `data.current_time`.
        `reference_id` (typically a benchmark_id) is optional and only
        used for the Correlation axis -- omitting it yields an honestly
        UNKNOWN Correlation observation rather than a fabricated one."""
        config = self._config
        as_of_time = data.current_time

        trend_points = self._fetch_points(data, subject_id, subject_kind, self._lookback_days_for(RegimeAxis.TREND))
        trend_state, trend_value, trend_reliability = compute_trend(trend_points, config)
        trend_obs = self._build_observation(
            axis=RegimeAxis.TREND, subject_id=subject_id, subject_kind=subject_kind, as_of_time=as_of_time,
            state=trend_state, value=trend_value, reliability=trend_reliability,
            lookback_days=config.trend_long_window,
            data_version=tuple(sorted({p.data_version for p in trend_points})),
            provenance=provenance, experiment_id=experiment_id,
        )

        vol_points = self._fetch_points(data, subject_id, subject_kind, self._lookback_days_for(RegimeAxis.VOLATILITY))
        vol_state, vol_value, vol_reliability = compute_volatility(vol_points, config)
        vol_obs = self._build_observation(
            axis=RegimeAxis.VOLATILITY, subject_id=subject_id, subject_kind=subject_kind, as_of_time=as_of_time,
            state=vol_state, value=vol_value, reliability=vol_reliability,
            lookback_days=config.volatility_window + config.volatility_percentile_window,
            data_version=tuple(sorted({p.data_version for p in vol_points})),
            provenance=provenance, experiment_id=experiment_id,
        )

        liq_points = self._fetch_points(data, subject_id, subject_kind, self._lookback_days_for(RegimeAxis.LIQUIDITY))
        liq_state, liq_value, liq_reliability = compute_liquidity(liq_points, config)
        liq_obs = self._build_observation(
            axis=RegimeAxis.LIQUIDITY, subject_id=subject_id, subject_kind=subject_kind, as_of_time=as_of_time,
            state=liq_state, value=liq_value, reliability=liq_reliability,
            lookback_days=config.liquidity_baseline_window,
            data_version=tuple(sorted({p.data_version for p in liq_points})),
            provenance=provenance, experiment_id=experiment_id,
        )

        corr_points = self._fetch_points(data, subject_id, subject_kind, self._lookback_days_for(RegimeAxis.CORRELATION))
        reference_points: list[PricePoint] = []
        if reference_id is not None:
            reference_points = self._fetch_points(
                data, reference_id, reference_kind, self._lookback_days_for(RegimeAxis.CORRELATION)
            )
        corr_state, corr_value, corr_reliability = compute_correlation(corr_points, reference_points, config)
        corr_obs = self._build_observation(
            axis=RegimeAxis.CORRELATION, subject_id=subject_id, subject_kind=subject_kind, as_of_time=as_of_time,
            state=corr_state, value=corr_value, reliability=corr_reliability,
            lookback_days=config.correlation_window,
            data_version=tuple(sorted({p.data_version for p in corr_points} | {p.data_version for p in reference_points})),
            provenance=provenance, experiment_id=experiment_id,
        )

        stress_points = self._fetch_points(data, subject_id, subject_kind, self._lookback_days_for(RegimeAxis.STRESS))
        stress_state, stress_value, stress_reliability = compute_stress(
            stress_points, VolatilityState(vol_state.value), config
        )
        stress_obs = self._build_observation(
            axis=RegimeAxis.STRESS, subject_id=subject_id, subject_kind=subject_kind, as_of_time=as_of_time,
            state=stress_state, value=stress_value, reliability=stress_reliability,
            lookback_days=config.stress_drawdown_window,
            data_version=tuple(sorted({p.data_version for p in stress_points})),
            provenance=provenance, experiment_id=experiment_id,
        )

        axes = {
            RegimeAxis.TREND: trend_obs,
            RegimeAxis.VOLATILITY: vol_obs,
            RegimeAxis.LIQUIDITY: liq_obs,
            RegimeAxis.CORRELATION: corr_obs,
            RegimeAxis.STRESS: stress_obs,
        }
        composite_label = self._composite_label(trend_obs.state, vol_obs.state, stress_obs.state)

        return CompositeRegimeObservation(
            composite_id=self._allocate_composite_id(),
            subject_id=subject_id,
            subject_kind=subject_kind,
            as_of_time=as_of_time,
            axes=axes,
            composite_label=composite_label,
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=as_of_time,
        )

    @staticmethod
    def _composite_label(trend_state: str, vol_state: str, stress_state: str) -> Optional[str]:
        if stress_state in _STRESS_OVERRIDE_LABELS:
            return _STRESS_OVERRIDE_LABELS[stress_state]
        return _COMPOSITE_LABELS.get((trend_state, vol_state))
