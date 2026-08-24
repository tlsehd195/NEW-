"""RegimeConditionedStrategy: an illustrative `Strategy` (Phase 2
Protocol) wrapper that suppresses BUY intents from an inner strategy
while the Trend regime is BEAR.

This exists to satisfy Phase 5 spec section 9's requirement to actually
try Regime as a conditioning variable and report what happens to a
baseline's metrics -- **not** as a claim that regime-conditioning
produces alpha. `PROJECT_MASTER_PLAN.md` section 1.1 explicitly forbids
adopting anything on backtest performance alone, and the instruction for
this phase repeats that constraint specifically for Regime: "이것을
근거로 Regime이 alpha를 만든다고 주장하지 않는다." Every test exercising
this class reports metrics side by side with the unconditioned baseline;
none of them assert the conditioned version is *better*.

Implements the exact `backtest.strategy.Strategy` Protocol, so it runs
through the unmodified `BacktestEngine` exactly like
`BuyAndHoldStrategy`/`SimpleMomentumStrategy` (Phase 5 spec section 8 --
"Backtest → Regime → Strategy 구조로 연결 가능한 interface").
"""

from __future__ import annotations

from datetime import datetime

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent, Strategy

from regime.config import RegimeConfig
from regime.detector import RegimeDetector
from regime.enums import RegimeAxis, SubjectKind, TrendState

from trade_journal.enums import TradeProvenance


class RegimeConditionedStrategy:
    """Wraps `inner` (any `Strategy`); every BUY intent it proposes is
    dropped whenever `subject_id`'s Trend regime is classified BEAR as of
    that decision. SELL intents always pass through unchanged -- exiting
    a position during a bearish regime is not the behavior this
    conditioning experiment is testing."""

    version = "regime_conditioned_v1"

    def __init__(
        self,
        inner: Strategy,
        *,
        subject_id: str,
        subject_kind: SubjectKind = SubjectKind.SECURITY,
        regime_config: RegimeConfig = RegimeConfig(),
        suppressed_trend_states: frozenset = frozenset({TrendState.BEAR}),
    ) -> None:
        self._inner = inner
        self._subject_id = subject_id
        self._subject_kind = subject_kind
        self._detector = RegimeDetector(regime_config)
        self._suppressed_trend_states = suppressed_trend_states
        self.regime_history: list = []  # observed CompositeRegimeObservation per decision step, for inspection

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        intents = self._inner.generate_orders(as_of_time, data, portfolio)
        if not intents:
            return intents

        composite = self._detector.compute_composite(
            data, self._subject_id, self._subject_kind, provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        self.regime_history.append(composite)
        trend_obs = composite.get(RegimeAxis.TREND)
        if trend_obs is None or TrendState(trend_obs.state) not in self._suppressed_trend_states:
            return intents

        return [intent for intent in intents if intent.side != OrderSide.BUY]
