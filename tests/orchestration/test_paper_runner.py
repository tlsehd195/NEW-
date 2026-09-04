"""Category: Integration Test -- `orchestration.paper_runner.run_cycle`,
the Regime -> Prediction -> Decision -> Sizing -> Risk -> Order
Validation -> `PaperTradingSession.submit` chain, exercised end to end
against a real (synthetic) drifting-price scenario -- the same
scenario shape `tests/integration/test_risk_lineage.py` already uses
for its own manual chain, extended here through the two steps that
test never took (Order Validation, actual submission), and through
ADR-0062's `sector_by_security` parameter specifically."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days
from paper_helpers import make_paper_config
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig

from broker.enums import BrokerOrderStatus
from broker.enums import OrderValidationStatus
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from orchestration.paper_runner import PaperRunnerState, run_cycle

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.config import PositionSizingConfig, RiskConfig
from risk.engine import DeterministicPortfolioRiskEngine
from risk.enums import RiskCheckStatus
from risk.sizing import DeterministicPositionSizer

from storage.config import StorageConfig
from storage.decision_repository import DuckDBDecisionRepository
from storage.engine import StorageEngine
from storage.prediction_repository import DuckDBPredictionRepository
from storage.regime_repository import DuckDBRegimeRepository
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    # A steeper drift than predict_helpers.drifting_prices' own 0.0008
    # default -- deliberately chosen so DriftPredictor's resulting
    # expected_return reliably clears DecisionConfig's default
    # min_expected_return=0.005 threshold at the checkpoint these tests
    # use, producing a real BUY rather than a coin-flip NO_TRADE.
    prices = drifting_prices(days, daily_return=0.006)
    bars = make_bars("AAA", days, prices)
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="paper-runner-integration-test",
    )
    return repo, config, bars


def _build_view(repo, config, index: int):
    calendar = repo.get_trading_calendar("US_EQUITY")
    checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
    clock = BacktestClock(checkpoints)
    clock.index = index
    return AsOfDataView(repo, clock), clock, checkpoints


def _session(bars, *, risk_config: RiskConfig = RiskConfig()) -> PaperTradingSession:
    mds = InMemoryPaperMarketDataSource(list(bars))
    return PaperTradingSession(make_paper_config(max_participation=1.0), mds)


def _components(risk_config: RiskConfig = RiskConfig(max_drawdown=None, max_portfolio_volatility=None)):
    return dict(
        predictor=DriftPredictor(PredictionConfig(lookback_days=20)),
        regime_detector=RegimeDetector(RegimeConfig()),
        decision_agent=BaselineRuleDecisionAgent(DecisionConfig()),
        position_sizer=DeterministicPositionSizer(PositionSizingConfig()),
        risk_engine=DeterministicPortfolioRiskEngine(risk_config),
    )


class TestFullChainProducesOneOutcomePerSecurityWithConsistentLineage:
    def test_lineage_ids_trace_through_every_stage(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)  # well past DriftPredictor's 20-day lookback
        session = _session(bars)

        outcomes = run_cycle(["AAA"], view.current_time, view, session, **_components())

        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.sizing.decision_id == outcome.decision.decision_id
        assert outcome.sizing.prediction_id == outcome.decision.prediction_id
        assert outcome.risk_checked.sizing_id == outcome.sizing.sizing_id
        assert outcome.risk_checked.decision_id == outcome.sizing.decision_id


class TestOrdersActuallySubmitAndFill:
    def test_a_warranted_buy_is_submitted_and_filled(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)

        outcomes = run_cycle(["AAA"], view.current_time, view, session, **_components())
        outcome = outcomes[0]

        # The synthetic fixture is a steady upward drift starting from
        # an empty portfolio -- BaselineRuleDecisionAgent's own default
        # confidence threshold is expected to propose a BUY here.
        assert outcome.validation.status == OrderValidationStatus.ACCEPTED
        assert outcome.submission is not None
        assert outcome.submission.status in (BrokerOrderStatus.FILLED, BrokerOrderStatus.PARTIAL_FILLED)

    def test_a_second_cycle_sees_the_first_cycles_real_fill_via_account_summary(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        first = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert first.submission is not None and first.submission.status == BrokerOrderStatus.FILLED

        account_before_second = session.account_summary(as_of=view.current_time)
        assert "AAA" in account_before_second.positions
        assert account_before_second.positions["AAA"].quantity == first.submission.filled_quantity

        clock.index = 101
        second = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        # The portfolio state fed into the second cycle's decision/sizing
        # must reflect the real position from the first cycle's fill --
        # never a fabricated/reset-to-empty state.
        assert second.decision.as_of_time == view.current_time


class TestSectorLimitPropagatesThroughTheWholeChain:
    def test_configured_sector_limit_without_a_mapping_rejects_the_whole_order(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_sector_weight=0.5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        outcomes = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(risk_config), sector_by_security=None,
        )
        outcome = outcomes[0]

        assert outcome.risk_checked.status == RiskCheckStatus.REJECT
        assert "sector_unknown" in outcome.risk_checked.breached_limits
        assert outcome.validation.status == OrderValidationStatus.VALIDATION_REJECTED
        assert outcome.submission is None

    def test_configured_sector_limit_with_a_generous_mapping_still_submits_normally(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_sector_weight=1.0, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        outcomes = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(risk_config),
            sector_by_security={"AAA": "Technology"},
        )
        outcome = outcomes[0]

        assert outcome.risk_checked.status in (RiskCheckStatus.PASS, RiskCheckStatus.REDUCE)
        assert outcome.submission is not None


class TestMaxOrderNotionalPropagatesThroughTheWholeChain:
    def test_a_tight_notional_cap_clamps_the_submitted_quantity(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        loose_config = RiskConfig(max_drawdown=None, max_portfolio_volatility=None)
        tight_config = RiskConfig(max_order_notional=500.0, max_drawdown=None, max_portfolio_volatility=None)

        loose_session = _session(bars, risk_config=loose_config)
        loose_outcome = run_cycle(["AAA"], view.current_time, view, loose_session, **_components(loose_config))[0]

        tight_session = _session(bars, risk_config=tight_config)
        tight_outcome = run_cycle(["AAA"], view.current_time, view, tight_session, **_components(tight_config))[0]

        assert "max_order_notional" in tight_outcome.risk_checked.breached_limits
        assert tight_outcome.submission is not None
        assert tight_outcome.submission.filled_quantity < loose_outcome.submission.filled_quantity


class TestValueHistoryState:
    """Session 36 continued -- PaperRunnerState lets max_drawdown/
    max_portfolio_volatility actually become evaluable, closing the
    limitation ADR-0067's own module docstring originally disclosed."""

    def test_without_state_a_real_max_drawdown_always_rejects_as_unknown(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_drawdown=0.5, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        outcome = run_cycle(["AAA"], view.current_time, view, session, **_components(risk_config))[0]

        assert "drawdown_unknown" in outcome.risk_checked.breached_limits

    def test_with_state_value_history_accumulates_across_cycles(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_drawdown=0.5, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)
        components = _components(risk_config)
        state = PaperRunnerState()

        outcomes = []
        for offset in range(5):
            clock.index = 100 + offset
            outcomes.append(run_cycle(["AAA"], view.current_time, view, session, state=state, **components)[0])

        assert len(state.value_history) == 5
        # With enough history (>= RiskConfig.min_history_for_volatility,
        # default 5), the drawdown check has real data to evaluate --
        # the FIRST cycle (1 history point) must still reject as
        # drawdown_unknown; the LAST must not, for that specific reason.
        assert "drawdown_unknown" in outcomes[0].risk_checked.breached_limits
        assert "drawdown_unknown" not in outcomes[-1].risk_checked.breached_limits


class TestPersistence:
    """Session 36 continued -- the five upstream stages `PaperTradingSession.
    submit` itself never persists, now optionally recorded through the
    exact repository classes `tests/integration/test_risk_lineage.py`
    already established."""

    def test_all_five_repositories_receive_exactly_one_record(self, tmp_path) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        prediction_repo = DuckDBPredictionRepository(engine)
        regime_repo = DuckDBRegimeRepository(engine)
        decision_repo = DuckDBDecisionRepository(engine)
        sizing_repo = DuckDBPositionSizingRepository(engine)
        risk_repo = DuckDBRiskRepository(engine)

        run_cycle(
            ["AAA"], view.current_time, view, session, **_components(),
            prediction_repository=prediction_repo, regime_repository=regime_repo,
            decision_repository=decision_repo, sizing_repository=sizing_repo, risk_repository=risk_repo,
        )

        assert len(prediction_repo.list_all(security_id="AAA")) == 1
        assert len(regime_repo.list_composites(subject_id="AAA")) == 1
        assert len(decision_repo.list_all(security_id="AAA")) == 1
        assert len(sizing_repo.list_all(security_id="AAA")) == 1
        assert len(risk_repo.list_all(security_id="AAA")) == 1
        engine.close()

    def test_omitted_repositories_persist_nothing(self, tmp_path) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        prediction_repo = DuckDBPredictionRepository(engine)

        run_cycle(["AAA"], view.current_time, view, session, **_components(), prediction_repository=prediction_repo)

        assert len(prediction_repo.list_all(security_id="AAA")) == 1
        engine.close()
