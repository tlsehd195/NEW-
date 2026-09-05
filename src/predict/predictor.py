"""Predictor Protocol + Phase 6 baseline predictors.

See docs/specifications/PHASE-6-prediction.md sections 4, 6, 9.

Every predictor sources data exclusively through `backtest.asof.AsOfDataView`
-- the same reuse Phase 5's `RegimeDetector` already established (ADR-0011
section 2): no new point-in-time guard is written here. `Predictor.predict`
returns a `PredictionOutput` and nothing else -- no predictor here (or
anywhere in this package) has a method that returns an `Order`/
`OrderIntent`, or accepts a `PortfolioView`/risk state as input. That
absence is the structural implementation of "Prediction은 투자 결정과
분리한다" (PROJECT_MASTER_PLAN.md section 8.1) -- there is no parameter
through which a portfolio/risk concern could even be threaded in.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional, Protocol

from backtest.asof import AsOfDataView
from backtest.metrics import compute_returns

from data_infra.versioning import compute_data_version

from predict.config import PredictionConfig
from predict.enums import PredictionMethodType
from predict.models import PredictionOutput

from regime.config import RegimeConfig
from regime.detector import RegimeDetector
from regime.enums import RegimeAxis, SubjectKind, VolatilityState
from regime.features import annualized_realized_vol, data_completeness

from trade_journal.enums import TradeProvenance

FEATURE_VERSION = "phase6_prediction_features_v1"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5


class Predictor(Protocol):
    def predict(
        self,
        data: AsOfDataView,
        security_id: str,
        *,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> PredictionOutput: ...


class _IdAllocator:
    def __init__(self, start: int = 1) -> None:
        self._next_id = start

    def allocate(self) -> str:
        pid = f"PRED-{self._next_id:06d}"
        self._next_id += 1
        return pid


class RandomWalkPredictor:
    """The null-hypothesis baseline: no forecastable drift.
    `expected_return = 0`, `probability = 0.5` -- both true by
    construction of the hypothesis, not estimated from data, so this
    predictor needs no market data lookup at all (Phase 6 spec section
    6). Any predictor that cannot beat this one is not adding
    forecasting value (the same "baseline first" role Phase 4's Buy &
    Hold plays for strategies, PROJECT_MASTER_PLAN.md section 85-86,
    applied here to Prediction)."""

    version = "random_walk_v1"
    method_type = PredictionMethodType.DETERMINISTIC_BASELINE

    def __init__(self, config: PredictionConfig = PredictionConfig(), *, starting_id: int = 1) -> None:
        self._config = config
        self._ids = _IdAllocator(starting_id)

    def predict(
        self,
        data: AsOfDataView,
        security_id: str,
        *,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> PredictionOutput:
        return PredictionOutput(
            prediction_id=self._ids.allocate(),
            security_id=security_id,
            as_of_time=data.current_time,
            horizon_days=self._config.horizon_days,
            expected_return=0.0,
            probability=0.5,
            expected_volatility=None,
            uncertainty=None,
            confidence=1.0,  # no data requirement -- nothing can be insufficient
            method=self.version,
            method_type=self.method_type,
            feature_version=FEATURE_VERSION,
            data_version=(),
            method_version=self.version,
            configuration_version=self._config.configuration_version(),
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=data.current_time,
        )


class DriftPredictor:
    """A simple, well-known naive forecasting baseline: assume the
    trailing average daily return continues, and that recent realized
    volatility persists (Phase 6 spec section 4). Both are standard,
    documented "no model" baselines in forecasting practice -- not
    presented as a claim of skill."""

    version = "drift_v1"
    method_type = PredictionMethodType.DETERMINISTIC_BASELINE

    def __init__(self, config: PredictionConfig = PredictionConfig(), *, starting_id: int = 1) -> None:
        self._config = config
        self._ids = _IdAllocator(starting_id)

    def predict(
        self,
        data: AsOfDataView,
        security_id: str,
        *,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> PredictionOutput:
        config = self._config
        as_of_time = data.current_time
        start = as_of_time - timedelta(days=config.lookback_days * 2)
        bars = data.get_bars(security_id, start, as_of_time)

        required = config.lookback_days + 1
        reliability = data_completeness(len(bars), required)

        common = dict(
            prediction_id=self._ids.allocate(),
            security_id=security_id,
            as_of_time=as_of_time,
            horizon_days=config.horizon_days,
            method=self.version,
            method_type=self.method_type,
            feature_version=FEATURE_VERSION,
            data_version=tuple(sorted({b.provenance.data_version for b in bars})),
            method_version=self.version,
            configuration_version=config.configuration_version(),
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=as_of_time,
        )

        if len(bars) < 2 or reliability < config.min_data_completeness:
            return PredictionOutput(
                expected_return=None, probability=None, expected_volatility=None,
                uncertainty=None, confidence=reliability, **common,
            )

        prices = [b.adjusted_close if b.adjusted_close is not None else b.close for b in bars]
        returns = compute_returns(prices)
        if len(returns) < 2:
            return PredictionOutput(
                expected_return=None, probability=None, expected_volatility=None,
                uncertainty=None, confidence=reliability, **common,
            )

        mean_return = _mean(returns)
        expected_return = (1.0 + mean_return) ** config.horizon_days - 1.0
        probability = sum(1 for r in returns if r > 0) / len(returns)
        expected_volatility = annualized_realized_vol(prices)
        uncertainty = _stdev(returns) / (len(returns) ** 0.5)  # standard error of the mean

        return PredictionOutput(
            expected_return=expected_return, probability=probability,
            expected_volatility=expected_volatility, uncertainty=uncertainty,
            confidence=reliability, **common,
        )


class RegimeAwarePredictor:
    """Wraps `DriftPredictor` and dampens its expected_return/confidence
    when the subject's Volatility regime is EXTREME -- an illustrative
    demonstration that Prediction *can* consume Regime as an input
    (PROJECT_MASTER_PLAN.md section 4.1's "Market Regime Detection →
    Prediction/Signal Engine" data flow), not a claim that this damping
    improves forecast accuracy. No test in this phase asserts this
    predictor is more accurate than the plain `DriftPredictor` -- only
    that the wiring runs and `regime_context` is populated (the same
    no-alpha-claim discipline ADR-0011 section 6 established for
    `RegimeConditionedStrategy`)."""

    version = "regime_aware_drift_v1"
    method_type = PredictionMethodType.DETERMINISTIC_BASELINE

    def __init__(
        self,
        prediction_config: PredictionConfig = PredictionConfig(),
        regime_config: RegimeConfig = RegimeConfig(),
    ) -> None:
        self._prediction_config = prediction_config
        self._drift = DriftPredictor(prediction_config)
        self._regime_detector = RegimeDetector(regime_config)

    def predict(
        self,
        data: AsOfDataView,
        security_id: str,
        *,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> PredictionOutput:
        base = self._drift.predict(data, security_id, provenance=provenance, experiment_id=experiment_id)
        composite = self._regime_detector.compute_composite(
            data, security_id, SubjectKind.SECURITY, provenance=provenance, experiment_id=experiment_id,
        )
        regime_context = {axis.value: obs.state for axis, obs in composite.axes.items()}

        if base.expected_return is None:
            adjusted_return = None
            adjusted_confidence = base.confidence
        else:
            volatility_obs = composite.get(RegimeAxis.VOLATILITY)
            is_extreme = volatility_obs is not None and volatility_obs.state == VolatilityState.EXTREME.value
            damping = self._prediction_config.regime_extreme_vol_damping if is_extreme else 0.0
            adjusted_return = base.expected_return * (1.0 - damping)
            confidence_multiplier = (
                self._prediction_config.regime_extreme_vol_confidence_multiplier if is_extreme else 1.0
            )
            adjusted_confidence = (base.confidence or 0.0) * confidence_multiplier

        configuration_version = compute_data_version(
            {"prediction": self._prediction_config.configuration_version(), "regime": composite.get(RegimeAxis.VOLATILITY).configuration_version if composite.get(RegimeAxis.VOLATILITY) else None}
        )

        return PredictionOutput(
            prediction_id=base.prediction_id,
            security_id=security_id,
            as_of_time=base.as_of_time,
            horizon_days=base.horizon_days,
            expected_return=adjusted_return,
            probability=base.probability,
            expected_volatility=base.expected_volatility,
            uncertainty=base.uncertainty,
            confidence=adjusted_confidence,
            method=self.version,
            method_type=self.method_type,
            feature_version=FEATURE_VERSION,
            data_version=base.data_version,
            method_version=self.version,
            configuration_version=configuration_version,
            regime_context=regime_context,
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=base.as_of_time,
        )
