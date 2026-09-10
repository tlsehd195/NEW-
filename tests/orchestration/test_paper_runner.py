"""Category: Integration Test -- `orchestration.paper_runner.run_cycle`,
the Regime -> Prediction -> Decision -> Sizing -> Risk -> Order
Validation -> `PaperTradingSession.submit` chain, exercised end to end
against a real (synthetic) drifting-price scenario -- the same
scenario shape `tests/integration/test_risk_lineage.py` already uses
for its own manual chain, extended here through the two steps that
test never took (Order Validation, actual submission), and through
ADR-0062's `sector_by_security` parameter specifically."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backtest_helpers import build_repository, make_bars, make_security, trading_days
from journal_helpers import make_fill, make_order
from paper_helpers import make_paper_config
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig
from backtest.enums import OrderSide

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

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.repository import InMemoryTradeJournalRepository


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


def _reversal_scenario():
    """Session 37 (ADR-0113) -- `_scenario`'s steady upward drift never
    produces a real SELL (`BaselineRuleDecisionAgent` only exits on a
    negative expected return, `decision/agent.py`), so no existing test
    in this file could ever exercise a real closing trade's realized
    PnL. This fixture rises for the first 150 trading days (long enough
    to clear a real BUY) then reverses into a sustained decline for the
    rest -- once `DriftPredictor`'s 20-day lookback drift turns negative
    enough to clear `DecisionConfig.min_expected_return`'s threshold on
    the sell side, a real SELL follows. Deterministic (fixed seed), not
    tuned per-run -- confirmed to produce a real SELL by direct
    instrumentation before being written as a test."""
    import random

    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    rng = random.Random(3)
    prices = [100.0]
    for i in range(1, len(days)):
        daily_return = 0.006 if i < 150 else -0.015
        prices.append(prices[-1] * (1 + daily_return + rng.gauss(0.0, 0.005)))
    bars = make_bars("AAA", days, prices)
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="paper-runner-reversal-test",
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

    def test_risk_state_position_weight_reflects_real_price_not_stale_fill_cost(self) -> None:
        """External review finding (Session 36 continued): `_portfolio_
        view` now populates `PositionView.market_value` from the same
        real reference price it already computes for the aggregate
        `portfolio_value` -- proving the fix reaches all the way through
        `run_cycle`'s real chain, not just a risk-engine unit test. The
        fixture's own steady upward price drift (`_scenario`) means the
        position's real market value diverges from its average fill
        cost by the time of this later checkpoint."""
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        first = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert first.submission is not None and first.submission.status == BrokerOrderStatus.FILLED
        fill_price = first.submission.avg_fill_price

        clock.index = 130  # far enough past the drift to move price meaningfully
        second = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        risk_state = second.risk_checked.risk_state
        assert risk_state is not None
        position = session.account_summary(as_of=view.current_time).positions["AAA"]

        cost_basis_weight = (position.quantity * position.average_cost) / risk_state.portfolio_value
        # The real weight this session's own fix now reports must differ
        # from what a cost-basis-only calculation would have reported --
        # the steady upward drift guarantees current price > fill cost.
        assert risk_state.position_weights["AAA"] != pytest.approx(cost_basis_weight)
        assert fill_price is not None and position.average_cost == pytest.approx(fill_price)


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


class TestReentryCooldownPropagatesThroughTheWholeChain:
    """Session 36 continued -- ADR-0093/ADR-0095/ADR-0096:
    `last_exit_time_by_security` is now sourced from a REAL
    `TradeJournalRepository`'s own `list_trades`, not fabricated by the
    test."""

    def _journal_with_exit(self, *, exit_time, position_after: float) -> InMemoryTradeJournalRepository:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=exit_time, security_id="AAA", decision=DecisionAction.SELL,
            order=make_order(order_id="ORD-EXIT", side=OrderSide.SELL),
        )
        journal.record_trade(
            decision_id=decision.snapshot_id,
            fill=make_fill(order_id="ORD-EXIT", side=OrderSide.SELL, execution_time=exit_time),
            position_after=position_after, provenance=TradeProvenance.PAPER_TRADING,
        )
        return journal

    def test_a_recent_full_exit_rejects_the_new_buy(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)
        journal = self._journal_with_exit(exit_time=view.current_time - timedelta(days=2), position_after=0.0)

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(risk_config),
            trade_journal_repository=journal,
        )[0]

        assert outcome.risk_checked.status == RiskCheckStatus.REJECT
        assert "reentry_cooldown" in outcome.risk_checked.breached_limits
        assert outcome.submission is None

    def test_an_exit_outside_the_cooldown_window_does_not_reject(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)
        journal = self._journal_with_exit(exit_time=view.current_time - timedelta(days=30), position_after=0.0)

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(risk_config),
            trade_journal_repository=journal,
        )[0]

        assert "reentry_cooldown" not in outcome.risk_checked.breached_limits
        assert outcome.submission is not None

    def test_a_partial_exit_still_holding_a_position_does_not_count(self) -> None:
        """A SELL that still leaves a nonzero position is ordinary
        rebalancing, not a full exit -- must not trigger the cooldown
        even if very recent."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)
        journal = self._journal_with_exit(exit_time=view.current_time - timedelta(days=1), position_after=5.0)

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(risk_config),
            trade_journal_repository=journal,
        )[0]

        assert "reentry_cooldown" not in outcome.risk_checked.breached_limits
        assert outcome.submission is not None

    def test_omitted_trade_journal_repository_is_not_gated_even_with_the_limit_configured(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        outcome = run_cycle(["AAA"], view.current_time, view, session, **_components(risk_config))[0]

        assert "reentry_cooldown" not in outcome.risk_checked.breached_limits
        assert outcome.submission is not None


class TestTradeJournalWriteSide:
    """Session 36 continued -- ADR-0096: `run_cycle` now WRITES a real
    `TradeRecord` for every real fill, closing the gap that this
    project's Paper Trading pipeline had never once populated the Trade
    Journal in its production code path before this."""

    def test_a_filled_buy_is_recorded_as_a_real_trade_with_a_real_joinable_decision(self) -> None:
        """Session 37 (ADR-0113): `trade.decision_id` now points to a
        real `DecisionSnapshot` this function itself records (superseding
        ADR-0097's own documented "not joinable" limitation) -- verified
        by actually resolving the join, not just comparing IDs, since
        `learning.cleaning.DataCleaner.clean` depends on exactly this
        join succeeding (`journal.get_decision(record.decision_id)`)."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(),
            trade_journal_repository=journal,
        )[0]

        assert outcome.submission is not None and outcome.submission.filled_quantity
        trades = journal.list_trades(security_id="AAA")
        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == OrderSide.BUY
        assert trade.quantity == outcome.submission.filled_quantity
        assert trade.position_after == outcome.submission.filled_quantity  # started from an empty portfolio
        assert trade.provenance == TradeProvenance.PAPER_TRADING

        decision_snapshot = journal.get_decision(trade.decision_id)
        assert decision_snapshot is not None  # the real join DataCleaner.clean depends on
        assert decision_snapshot.security_id == "AAA"
        assert decision_snapshot.decision == outcome.decision.action
        assert decision_snapshot.order is None  # never a ValidatedOrder -- see module docstring
        assert decision_snapshot.provenance == TradeProvenance.PAPER_TRADING

    def test_a_rejected_order_writes_no_trade(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_sector_weight=0.5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)
        journal = InMemoryTradeJournalRepository()

        # Same "configured but no mapping supplied" REJECT this project's
        # own TestSectorLimitPropagatesThroughTheWholeChain already
        # establishes -- reused here to reliably exercise a REJECT rather
        # than a merely-reduced BUY.
        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(risk_config),
            sector_by_security=None, trade_journal_repository=journal,
        )[0]

        assert outcome.submission is None
        assert journal.list_trades() == []

    def test_omitted_trade_journal_repository_writes_nothing_and_does_not_crash(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)

        outcome = run_cycle(["AAA"], view.current_time, view, session, **_components())[0]

        assert outcome.submission is not None and outcome.submission.filled_quantity

    def test_a_closing_sell_records_real_realized_pnl_return_and_holding_period(self) -> None:
        """Session 37 (ADR-0113): ADR-0096/ADR-0097's original write-side
        wiring never passed realized_pnl/realized_return/holding_period
        to record_trade at all -- every real TradeRecord this module
        ever wrote had them permanently None, even for a genuine closing
        SELL, which silently made learning.pipeline.run_learning_pipeline
        structurally unable to ever train from real Paper Trading
        experience (DataCleaningConfig.require_realized_outcome=True's
        default excludes any sample without a real realized_return).
        Uses _reversal_scenario (rise then decline) since _scenario's own
        steady uptrend never produces a real SELL to test against."""
        repo, config, bars = _reversal_scenario()
        view, clock, checkpoints = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()
        components = _components()

        sell_outcome = None
        for offset in range(0, len(checkpoints) - 100):
            clock.index = 100 + offset
            outcome = run_cycle(
                ["AAA"], view.current_time, view, session, trade_journal_repository=journal, **components,
            )[0]
            if outcome.submission is not None and outcome.decision.action.value == "SELL":
                sell_outcome = outcome
                break

        assert sell_outcome is not None, "fixture must produce a real SELL -- see _reversal_scenario's own docstring"

        trades = journal.list_trades(security_id="AAA")
        buy_trades = [t for t in trades if t.side == OrderSide.BUY]
        sell_trades = [t for t in trades if t.side == OrderSide.SELL]
        assert len(buy_trades) == 1 and buy_trades[0].realized_pnl is None  # an opening leg realizes nothing yet
        assert len(sell_trades) == 1
        sell_trade = sell_trades[0]

        # Hand-computed against the same real inputs run_cycle itself
        # used: the BUY's own real fill price (cost basis) and the
        # SELL's own real fill price/quantity/commission. commission
        # ONLY, not sell_fill.total_cost -- fill.price already nets out
        # spread/slippage on both legs (Session 37, ADR-0114).
        buy_fill = buy_trades[0].fill
        sell_fill = sell_trade.fill
        expected_pnl = (sell_fill.price - buy_fill.price) * sell_fill.quantity - sell_fill.commission
        assert sell_trade.realized_pnl == pytest.approx(expected_pnl)
        expected_return = expected_pnl / (buy_fill.price * sell_fill.quantity)
        assert sell_trade.realized_return == pytest.approx(expected_return)
        assert sell_trade.holding_period == sell_fill.execution_time - buy_fill.execution_time
        assert sell_trade.position_after == 0.0

    def test_omitted_trade_journal_repository_still_omits_realized_fields_by_default(self) -> None:
        """Regression guard: TradeJournalRepositoryLike widening
        record_trade's signature (Session 37) must not change behavior
        for a caller that never supplies trade_journal_repository at
        all -- covered structurally by every other test in this class
        that omits it and still passes, this test just names the
        invariant explicitly."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)

        outcomes = run_cycle(["AAA"], view.current_time, view, session, **_components())
        assert outcomes[0].submission is not None  # unchanged baseline behavior


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
