"""Shared test helpers for the Phase 8 Position Sizing + Portfolio Risk
Engine test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backtest_helpers import make_security
from decision_helpers import build_repository, checkpoint, drifting_prices, make_bars, trading_days, view_at

from backtest.portfolio import PortfolioView, PositionView

from decision.models import DecisionOutput

from regime.enums import RegimeAxis, SubjectKind
from regime.models import CompositeRegimeObservation, RegimeObservation

from trade_journal.enums import DecisionAction


def utc(year: int, month: int, day: int, hour: int = 20) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


_DEFAULT_AS_OF = datetime(2024, 1, 1, tzinfo=timezone.utc)


def empty_portfolio(as_of_time: datetime = _DEFAULT_AS_OF, cash: float = 100_000.0) -> PortfolioView:
    return PortfolioView(as_of_time=as_of_time, cash=cash, positions={}, portfolio_value=cash)


def portfolio_holding(
    as_of_time: datetime, security_id: str, quantity: float = 100.0, average_cost: float = 90.0,
    cash: float = 50_000.0, portfolio_value: float = 100_000.0, market_value: Optional[float] = None,
) -> PortfolioView:
    return PortfolioView(
        as_of_time=as_of_time, cash=cash,
        positions={security_id: PositionView(security_id, quantity, average_cost, market_value=market_value)},
        portfolio_value=portfolio_value,
    )


class FakePrediction:
    """A minimal stand-in exposing only what PositionSizer reads
    (`expected_volatility`) -- avoids constructing a full
    `predict.models.PredictionOutput` in every sizing-only test."""

    def __init__(self, expected_volatility: Optional[float] = 0.15) -> None:
        self.expected_volatility = expected_volatility


def make_decision(
    as_of_time: datetime, *, security_id: str = "AAA", action: DecisionAction = DecisionAction.BUY,
    confidence: Optional[float] = 0.9, target_weight_hint: Optional[float] = 0.10,
    decision_id: str = "DEC-OUT-000001", prediction_id: Optional[str] = "PRED-000001",
    decision_version: str = "baseline_rule_decision_agent_v1",
) -> DecisionOutput:
    return DecisionOutput(
        decision_id=decision_id, security_id=security_id, as_of_time=as_of_time, action=action,
        decision_reason="test_reason", confidence=confidence, time_horizon_days=5,
        target_weight_hint=target_weight_hint, regime=None, prediction_id=prediction_id,
        prediction_version="drift_v1", regime_version=None, feature_version="phase7_decision_features_v1",
        data_version=("d1",), model_version=None, decision_version=decision_version,
    )


def make_regime_with_liquidity(as_of_time: datetime, security_id: str, state: str) -> CompositeRegimeObservation:
    obs = RegimeObservation(
        regime_id="REG-000001", axis=RegimeAxis.LIQUIDITY, subject_id=security_id,
        subject_kind=SubjectKind.SECURITY, timestamp=as_of_time, as_of_time=as_of_time,
        state=state, value=None, definition="test_liquidity_v1", reliability=1.0, lookback_days=20,
        feature_version="f1", data_version=("d1",), method_version="m1", configuration_version="c1",
    )
    return CompositeRegimeObservation(
        composite_id="CREG-000001", subject_id=security_id, subject_kind=SubjectKind.SECURITY,
        as_of_time=as_of_time, axes={RegimeAxis.LIQUIDITY: obs},
    )


__all__ = [
    "build_repository", "checkpoint", "drifting_prices", "make_bars", "make_security", "trading_days", "view_at",
    "utc", "empty_portfolio", "portfolio_holding", "FakePrediction", "make_decision",
    "make_regime_with_liquidity",
]
