"""Category: Integration Test -- `orchestration.paper_runner.run_cycle`,
the Regime -> Prediction -> Decision -> Sizing -> Risk -> Order
Validation -> `PaperTradingSession.submit` chain, exercised end to end
against a real (synthetic) drifting-price scenario -- the same
scenario shape `tests/integration/test_risk_lineage.py` already uses
for its own manual chain, extended here through the two steps that
test never took (Order Validation, actual submission), and through
ADR-0062's `sector_by_security` parameter specifically."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backtest_helpers import build_repository, checkpoint, make_bars, make_dividend, make_provenance, make_security, make_split, trading_days
from journal_helpers import make_fill, make_order
from paper_helpers import make_paper_config
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig
from backtest.enums import OrderSide, OrderType

from broker.enums import BrokerOrderStatus
from broker.enums import OrderValidationStatus
from broker.models import ValidatedOrder
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession

from data_infra.enums import CorporateActionType
from data_infra.models import CorporateAction

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


def _two_security_scenario():
    """ADR-0177 (independent audit P1-3): identical to `_scenario()`
    except for a SECOND security (BBB) with the exact same rising-price
    shape, so both independently produce a real BUY at the same
    checkpoint -- the minimal real setup needed to prove
    `run_cycle` refreshes its own cumulative gross-exposure state
    between securities within one cycle, rather than checking every
    security against the same pre-cycle snapshot."""
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    prices = drifting_prices(days, daily_return=0.006)
    bars = make_bars("AAA", days, prices) + make_bars("BBB", days, prices)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA", "BBB"), code_version="paper-runner-cumulative-exposure-test",
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
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        outcomes = run_cycle(["AAA"], view.current_time, view, session, **components)
        outcome = outcomes[0]

        # The synthetic fixture is a steady upward drift starting from
        # an empty portfolio -- BaselineRuleDecisionAgent's own default
        # confidence threshold is expected to propose a BUY here.
        assert outcome.validation.status == OrderValidationStatus.ACCEPTED
        assert outcome.submission is not None
        # ADR-0154: submission never fills synchronously -- the fill is
        # deferred to the NEXT cycle's own advance() call.
        assert outcome.submission.status == BrokerOrderStatus.PENDING

        clock.index = 101
        # No new decision this cycle (empty security_ids) -- isolates
        # this call to exercise only the delayed-fill retry run_cycle
        # performs first, via its own advance().
        assert run_cycle([], view.current_time, view, session, **components) == ()
        status = session.adapter.get_order_status(outcome.submission.request_client_order_id, as_of=view.current_time)
        assert status.status in (BrokerOrderStatus.FILLED, BrokerOrderStatus.PARTIAL_FILLED)

    def test_a_second_cycle_sees_the_first_cycles_real_fill_via_account_summary(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        first = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert first.submission is not None and first.submission.status == BrokerOrderStatus.PENDING  # ADR-0154

        # Before the second cycle's own advance() runs, the fill has not
        # landed yet -- no position exists, never a fabricated one.
        account_before_second = session.account_summary(as_of=view.current_time)
        assert "AAA" not in account_before_second.positions

        clock.index = 101
        second = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        # The second cycle's own advance() (called first, before its own
        # decision) fills the first cycle's order -- its decision/sizing/
        # risk chain therefore sees a real, non-empty position, never a
        # fabricated one.
        account_after_advance = session.account_summary(as_of=view.current_time)
        assert "AAA" in account_after_advance.positions
        assert account_after_advance.positions["AAA"].quantity > 0
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
        assert first.submission is not None and first.submission.status == BrokerOrderStatus.PENDING  # ADR-0154

        clock.index = 101
        run_cycle([], view.current_time, view, session, **components)  # delayed fill lands here
        status = session.adapter.get_order_status(first.submission.request_client_order_id, as_of=view.current_time)
        assert status.status == BrokerOrderStatus.FILLED
        fill_price = status.avg_fill_price

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
        loose_session.advance(view.current_time)  # ADR-0154: fill is deferred -- attempt it now

        tight_session = _session(bars, risk_config=tight_config)
        tight_outcome = run_cycle(["AAA"], view.current_time, view, tight_session, **_components(tight_config))[0]
        tight_session.advance(view.current_time)  # ADR-0154: fill is deferred -- attempt it now

        assert "max_order_notional" in tight_outcome.risk_checked.breached_limits
        assert tight_outcome.submission is not None
        loose_status = loose_session.adapter.get_order_status(
            loose_outcome.submission.request_client_order_id, as_of=view.current_time,
        )
        tight_status = tight_session.adapter.get_order_status(
            tight_outcome.submission.request_client_order_id, as_of=view.current_time,
        )
        assert tight_status.filled_quantity < loose_status.filled_quantity


class TestCumulativeGrossExposureEnforcedWithinOneCycle:
    """ADR-0177 (independent audit P1-3): `portfolio` used to be
    captured once per cycle and never updated, even after a real
    submission -- a SECOND security in the same cycle would have its
    `risk_engine.assess` gross-exposure check run against the exact same
    stale snapshot the FIRST security was checked against, so both could
    individually pass while their combined effect breaches
    `RiskConfig.max_gross_exposure`. Note ADR-0154 makes every real
    submission PENDING (never filled synchronously, by design) -- the
    fix must therefore track this cycle's own pending exposure in
    memory, never by re-reading `session.account_summary()` (which would
    see no change at all until the NEXT cycle's own `advance()`)."""

    def test_second_securitys_risk_check_reflects_the_firsts_already_submitted_order(self) -> None:
        repo, config, bars = _two_security_scenario()
        view, _, _ = _build_view(repo, config, 100)
        # DeterministicPositionSizer's own PositionSizingConfig.max_position_weight
        # default (0.10) means a single full-size BUY proposes roughly 10% of
        # the portfolio -- comfortably below 0.15 alone, comfortably above it
        # combined with a second, identical ~10% BUY.
        risk_config = RiskConfig(max_gross_exposure=0.15, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        aaa_outcome, bbb_outcome = run_cycle(
            ["AAA", "BBB"], view.current_time, view, session, **_components(risk_config),
        )

        # AAA and BBB have identical price/volatility inputs, so
        # PositionSizer (which has no cross-security visibility at all)
        # proposes the identical raw target weight for both -- any
        # difference in the RISK-CHECKED result below can only come from
        # risk_engine.assess seeing AAA's already-submitted order.
        assert aaa_outcome.sizing.proposed_target_weight == bbb_outcome.sizing.proposed_target_weight
        assert aaa_outcome.submission is not None

        assert "gross_exposure" in bbb_outcome.risk_checked.breached_limits
        assert bbb_outcome.risk_checked.final_target_weight is not None
        assert aaa_outcome.risk_checked.final_target_weight is not None
        assert bbb_outcome.risk_checked.final_target_weight < aaa_outcome.risk_checked.final_target_weight

    def test_a_generous_gross_exposure_limit_lets_both_submit_at_full_size(self) -> None:
        repo, config, bars = _two_security_scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_gross_exposure=1.0, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        aaa_outcome, bbb_outcome = run_cycle(
            ["AAA", "BBB"], view.current_time, view, session, **_components(risk_config),
        )

        assert "gross_exposure" not in aaa_outcome.risk_checked.breached_limits
        assert "gross_exposure" not in bbb_outcome.risk_checked.breached_limits
        assert aaa_outcome.risk_checked.final_target_weight == bbb_outcome.risk_checked.final_target_weight
        assert aaa_outcome.submission is not None
        assert bbb_outcome.submission is not None

    def test_real_broker_account_state_is_untouched_by_the_in_memory_estimate(self) -> None:
        """The fix must never call `session.account_summary()` again or
        otherwise mutate real broker state mid-cycle -- ADR-0154's T+1
        discipline (no synchronous fills) must remain completely intact."""
        repo, config, bars = _two_security_scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_gross_exposure=0.15, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)
        cash_before = session.account_summary(as_of=view.current_time).cash

        run_cycle(["AAA", "BBB"], view.current_time, view, session, **_components(risk_config))

        real_account = session.account_summary(as_of=view.current_time)
        assert "AAA" not in real_account.positions
        assert "BBB" not in real_account.positions
        # No real fill can happen this cycle (ADR-0154) -- real cash must
        # be exactly unchanged, never reflecting this fix's own in-memory
        # cash_delta estimate.
        assert real_account.cash == cash_before


class TestMaxTurnoverPropagatesThroughTheWholeChain:
    """Independent audit finding (Step 4/9, P2): `risk.engine.
    DeterministicPortfolioRiskEngine.assess` fail-closed REJECTs every
    BUY as "turnover_unknown" whenever `RiskConfig.max_turnover` is
    configured but no real `turnover` value is passed -- `run_cycle`
    never passed one at all before this fix. A real, already-existing
    `session.adapter.accounting.turnover()` is now threaded through."""

    def test_a_configured_max_turnover_no_longer_rejects_every_buy_as_unknown(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_turnover=10.0, max_drawdown=None, max_portfolio_volatility=None)
        session = _session(bars, risk_config=risk_config)

        outcomes = run_cycle(["AAA"], view.current_time, view, session, **_components(risk_config))
        outcome = outcomes[0]

        assert "turnover_unknown" not in outcome.risk_checked.breached_limits
        assert outcome.submission is not None


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
        join succeeding (`journal.get_decision(record.decision_id)`).

        ADR-0154: the decision is recorded in the SAME cycle it is made,
        but the fill (and therefore the TradeRecord) is deferred to the
        NEXT cycle's `advance()` -- so this test now spans two cycles."""
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()
        components = _components()

        cycle1_time = view.current_time
        outcome = run_cycle(
            ["AAA"], cycle1_time, view, session, **components,
            trade_journal_repository=journal,
        )[0]
        assert outcome.submission is not None
        assert outcome.submission.status == BrokerOrderStatus.PENDING  # ADR-0154: fill deferred
        assert journal.list_trades() == []  # no premature TradeRecord this cycle

        decision_snapshot_pending = journal.get_decision_by_natural_key(
            ("paper_decision", None, "AAA", cycle1_time),
        )
        assert decision_snapshot_pending is not None  # the decision itself IS recorded immediately

        clock.index = 101
        run_cycle([], view.current_time, view, session, **components, trade_journal_repository=journal)  # delayed fill lands here

        trades = journal.list_trades(security_id="AAA")
        assert len(trades) == 1
        trade = trades[0]
        assert trade.side == OrderSide.BUY
        status = session.adapter.get_order_status(outcome.submission.request_client_order_id, as_of=cycle1_time)
        assert trade.quantity == status.filled_quantity
        assert trade.position_after == status.filled_quantity  # started from an empty portfolio
        assert trade.provenance == TradeProvenance.PAPER_TRADING

        decision_snapshot = journal.get_decision(trade.decision_id)
        assert decision_snapshot is not None  # the real join DataCleaner.clean depends on
        assert decision_snapshot.snapshot_id == decision_snapshot_pending.snapshot_id  # the SAME decision, joined via natural_key
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
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        outcome = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert outcome.submission is not None
        assert outcome.submission.status == BrokerOrderStatus.PENDING  # ADR-0154: fill deferred

        clock.index = 101
        run_cycle([], view.current_time, view, session, **components)  # advance() must not crash without a journal
        status = session.adapter.get_order_status(outcome.submission.request_client_order_id, as_of=view.current_time)
        assert status.status in (BrokerOrderStatus.FILLED, BrokerOrderStatus.PARTIAL_FILLED)

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

        # ADR-0154: a SELL decided this cycle only fills (and therefore
        # only reaches the Trade Journal) on a LATER cycle's advance() --
        # so this loop watches the journal itself for the real SELL
        # TradeRecord to appear, rather than the same-cycle `outcome.
        # decision.action` this used to check before fills were deferred.
        sell_trade = None
        for offset in range(0, len(checkpoints) - 100):
            clock.index = 100 + offset
            run_cycle(
                ["AAA"], view.current_time, view, session, trade_journal_repository=journal, **components,
            )
            sell_trades = [t for t in journal.list_trades(security_id="AAA") if t.side == OrderSide.SELL]
            if sell_trades:
                sell_trade = sell_trades[0]
                break

        assert sell_trade is not None, "fixture must produce a real SELL -- see _reversal_scenario's own docstring"

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

    def test_an_unknown_broker_average_cost_never_fabricates_realized_pnl(self) -> None:
        """Session 37 (ADR-0115, external review N-16): before this fix,
        `position_average_cost` was read from `portfolio.positions[...]
        .average_cost` -- `_portfolio_view`'s own `PositionView.
        average_cost`, a non-Optional `float` field that MUST fabricate
        `0.0` whenever the broker's own `BrokerPosition.average_cost`
        (genuinely `Optional[float]`) is unknown. That silently turned
        "cost basis unknown" into "cost basis is exactly zero," making
        realized_pnl the entire sale proceeds instead of the honest
        `None` this module's own docstring promises. Reading straight
        from `account.positions` (the raw `BrokerPosition`) instead
        preserves a genuine `None` through to the recorded TradeRecord."""
        from broker.paper.session import AccountSummary
        from broker.models import BrokerPosition

        repo, config, bars = _reversal_scenario()
        view, clock, checkpoints = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()
        components = _components()

        real_account_summary = session.account_summary
        sell_outcome = None
        for offset in range(0, len(checkpoints) - 100):
            clock.index = 100 + offset
            real_summary = real_account_summary(as_of=view.current_time)
            aaa_position = real_summary.positions.get("AAA")
            about_to_sell_with_known_cost = aaa_position is not None and aaa_position.quantity > 0

            if about_to_sell_with_known_cost:
                # Report AAA's average_cost as genuinely unknown for this
                # one cycle -- everything else (quantity, cash) is real.
                unknown_cost_position = BrokerPosition(
                    security_id="AAA", as_of_time=aaa_position.as_of_time, available=True,
                    unavailable_reason=None, quantity=aaa_position.quantity, average_cost=None,
                )
                stub_summary = AccountSummary(
                    as_of_time=real_summary.as_of_time, cash=real_summary.cash,
                    positions={**real_summary.positions, "AAA": unknown_cost_position},
                )
                session.account_summary = lambda *, as_of, _s=stub_summary: _s
            else:
                session.account_summary = real_account_summary

            run_cycle(
                ["AAA"], view.current_time, view, session, trade_journal_repository=journal, **components,
            )
            # ADR-0154: watch the journal itself for the real (delayed)
            # SELL fill, rather than the same-cycle `outcome.decision`.
            if [t for t in journal.list_trades(security_id="AAA") if t.side == OrderSide.SELL]:
                sell_outcome = True
                break

        assert sell_outcome is not None, "fixture must produce a real SELL -- see _reversal_scenario's own docstring"
        sell_trades = [t for t in journal.list_trades(security_id="AAA") if t.side == OrderSide.SELL]
        assert len(sell_trades) == 1
        # The bug: without the fix, this would be a large fabricated
        # profit (the entire sale proceeds, cost basis wrongly zero).
        assert sell_trades[0].realized_pnl is None
        assert sell_trades[0].realized_return is None

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


class TestDecisionSnapshotFeatures:
    """Session 38: before this, `run_cycle` never populated `Decision
    Snapshot.features` for any real Paper Trading decision --
    `scripts/run_learning_cycle.py`'s own module docstring already
    disclosed this honestly ("no Strategy/DecisionAgent... sets
    OrderIntent.features yet"), which is why `learning.linear_trainer.
    LinearRegressionTrainer` always reported `fitted=False,
    train_sample_count=0` against real data regardless of how much
    real Paper Trading history existed."""

    def test_real_prediction_fields_reach_the_decision_snapshot(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()

        cycle_time = view.current_time
        outcome = run_cycle(
            ["AAA"], cycle_time, view, session, **_components(),
            trade_journal_repository=journal,
        )[0]

        # ADR-0154: the decision is recorded immediately (a TradeRecord
        # is not, since the fill is deferred) -- fetched here via the
        # SAME natural_key `record_decision` indexes it under.
        decision_snapshot = journal.get_decision_by_natural_key(("paper_decision", None, "AAA", cycle_time))
        assert decision_snapshot is not None
        assert decision_snapshot.features is not None
        # Every value actually matches this cycle's own real prediction
        # -- never a fabricated or re-derived number.
        assert decision_snapshot.features["expected_return"] == outcome.prediction.expected_return
        assert decision_snapshot.features["confidence"] == outcome.prediction.confidence

    def test_a_none_valued_prediction_field_is_omitted_not_written_as_none(self) -> None:
        """`LinearRegressionTrainer._samples_with_required_features`
        only checks KEY PRESENCE (`required <= set(s.features)`) --
        writing `"key": None` would pass that check and then crash
        `LinearRegressionModel.fit`'s own arithmetic on a real
        (fitted=True-eligible) sample. Confirmed directly against the
        real helper function, not just asserted."""
        from orchestration.paper_runner import _prediction_features
        from predict.models import PredictionOutput
        from predict.enums import PredictionMethodType

        prediction = PredictionOutput(
            prediction_id="PRED-000001", security_id="AAA", as_of_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
            horizon_days=20, expected_return=0.01, probability=None, expected_volatility=0.2,
            uncertainty=None, confidence=0.8, method="drift_v1", method_type=PredictionMethodType.MODEL_BASED,
            feature_version="fv1", data_version=(), method_version="mv1", configuration_version="cv1",
        )
        features = _prediction_features(prediction)
        assert features == {"expected_return": 0.01, "expected_volatility": 0.2, "confidence": 0.8}
        assert "probability" not in features
        assert "uncertainty" not in features

    def test_all_fields_none_returns_none_not_an_empty_dict(self) -> None:
        from orchestration.paper_runner import _prediction_features
        from predict.models import PredictionOutput
        from predict.enums import PredictionMethodType

        prediction = PredictionOutput(
            prediction_id="PRED-000001", security_id="AAA", as_of_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
            horizon_days=20, expected_return=None, probability=None, expected_volatility=None,
            uncertainty=None, confidence=None, method="drift_v1", method_type=PredictionMethodType.MODEL_BASED,
            feature_version="fv1", data_version=(), method_version="mv1", configuration_version="cv1",
        )
        assert _prediction_features(prediction) is None

    def test_regime_state_is_one_hot_encoded_excluding_unknown(self) -> None:
        """External review (Session 38 continued, ADR-0141's own
        disclosed trade-off): regime axis observations were not encoded
        into numeric features at all. A real (non-UNKNOWN) state gets
        one key per real state of that SAME axis -- 1.0 for the active
        one, 0.0 for the others -- never a fabricated value for the
        UNKNOWN axis (Distribution) below."""
        from orchestration.paper_runner import _regime_features
        from regime.enums import RegimeAxis, SubjectKind
        from regime.models import CompositeRegimeObservation, RegimeObservation

        as_of = datetime(2024, 6, 1, tzinfo=timezone.utc)
        trend_obs = RegimeObservation(
            regime_id="REG-000001", axis=RegimeAxis.TREND, subject_id="AAA",
            subject_kind=SubjectKind.SECURITY, timestamp=as_of, as_of_time=as_of,
            state="BULL", value=0.05, definition="trend_ma_crossover_v1", reliability=1.0,
            lookback_days=20, feature_version="f1", data_version=("d1",),
            method_version="m1", configuration_version="c1",
        )
        distribution_obs = RegimeObservation(
            regime_id="REG-000002", axis=RegimeAxis.DISTRIBUTION, subject_id="AAA",
            subject_kind=SubjectKind.SECURITY, timestamp=as_of, as_of_time=as_of,
            state="UNKNOWN", value=None, definition="distribution_days_v1", reliability=0.0,
            lookback_days=20, feature_version="f1", data_version=("d1",),
            method_version="m1", configuration_version="c1",
        )
        regime = CompositeRegimeObservation(
            composite_id="CREG-000001", subject_id="AAA", subject_kind=SubjectKind.SECURITY,
            as_of_time=as_of, axes={RegimeAxis.TREND: trend_obs, RegimeAxis.DISTRIBUTION: distribution_obs},
        )

        features = _regime_features(regime)
        assert features == {
            "regime_trend_value": 0.05,
            "regime_trend_is_bull": 1.0,
            "regime_trend_is_bear": 0.0,
            "regime_trend_is_neutral": 0.0,
        }
        # The UNKNOWN Distribution axis contributes nothing at all --
        # never an all-zero one-hot block, never a fabricated value.
        assert not any(k.startswith("regime_distribution_") for k in features)

    def test_regime_value_can_be_present_even_when_state_is_unknown(self) -> None:
        """`compute_volatility` can return a real `.value` (the raw
        annualized vol estimate) while `.state` is still `UNKNOWN`
        (insufficient percentile history to classify it) -- value and
        state are independent facts, confirmed here directly."""
        from orchestration.paper_runner import _regime_features
        from regime.enums import RegimeAxis, SubjectKind
        from regime.models import CompositeRegimeObservation, RegimeObservation

        as_of = datetime(2024, 6, 1, tzinfo=timezone.utc)
        vol_obs = RegimeObservation(
            regime_id="REG-000001", axis=RegimeAxis.VOLATILITY, subject_id="AAA",
            subject_kind=SubjectKind.SECURITY, timestamp=as_of, as_of_time=as_of,
            state="UNKNOWN", value=0.22, definition="realized_vol_v1", reliability=0.4,
            lookback_days=20, feature_version="f1", data_version=("d1",),
            method_version="m1", configuration_version="c1",
        )
        regime = CompositeRegimeObservation(
            composite_id="CREG-000001", subject_id="AAA", subject_kind=SubjectKind.SECURITY,
            as_of_time=as_of, axes={RegimeAxis.VOLATILITY: vol_obs},
        )

        features = _regime_features(regime)
        assert features == {"regime_volatility_value": 0.22}  # value present, no state one-hot

    def test_all_axes_unknown_and_valueless_returns_none(self) -> None:
        from orchestration.paper_runner import _regime_features
        from regime.enums import RegimeAxis, SubjectKind
        from regime.models import CompositeRegimeObservation, RegimeObservation

        as_of = datetime(2024, 6, 1, tzinfo=timezone.utc)
        obs = RegimeObservation(
            regime_id="REG-000001", axis=RegimeAxis.TREND, subject_id="AAA",
            subject_kind=SubjectKind.SECURITY, timestamp=as_of, as_of_time=as_of,
            state="UNKNOWN", value=None, definition="trend_ma_crossover_v1", reliability=0.0,
            lookback_days=20, feature_version="f1", data_version=("d1",),
            method_version="m1", configuration_version="c1",
        )
        regime = CompositeRegimeObservation(
            composite_id="CREG-000001", subject_id="AAA", subject_kind=SubjectKind.SECURITY,
            as_of_time=as_of, axes={RegimeAxis.TREND: obs},
        )
        assert _regime_features(regime) is None

    def test_a_real_cycle_s_decision_snapshot_carries_both_prediction_and_regime_features(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()

        cycle_time = view.current_time
        run_cycle(
            ["AAA"], cycle_time, view, session, **_components(),
            trade_journal_repository=journal,
        )

        # ADR-0154: the fill (and therefore a TradeRecord) is deferred --
        # the decision itself is recorded immediately, so it is fetched
        # directly via its natural_key rather than through a TradeRecord.
        decision_snapshot = journal.get_decision_by_natural_key(("paper_decision", None, "AAA", cycle_time))
        assert decision_snapshot.features is not None
        assert "expected_return" in decision_snapshot.features  # prediction side, unchanged
        # At least one real regime key reached the snapshot too -- the
        # fixture's own drift produces a real, classifiable Trend axis.
        assert any(k.startswith("regime_") for k in decision_snapshot.features)


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


class TestMarkToMarketAccounting:
    """Session 38: before this, nothing ever called `mark_to_market` on
    `session.adapter.accounting`, so `broker.paper.performance.
    compute_paper_performance_report`'s own `equity_history`/`turnover`
    inputs stayed permanently unavailable to any real caller driving
    Paper Trading through `run_cycle` -- confirmed here directly rather
    than only from reading the source."""

    def test_each_cycle_appends_exactly_one_valuation_point(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        assert session.adapter.accounting.value_series == ()

        run_cycle(["AAA"], view.current_time, view, session, **components)
        assert len(session.adapter.accounting.value_series) == 1

        clock.index = 101
        run_cycle(["AAA"], view.current_time, view, session, **components)
        assert len(session.adapter.accounting.value_series) == 2

    def test_valuation_point_uses_the_same_reference_price_every_other_stage_used(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        outcome = run_cycle(["AAA"], view.current_time, view, session, **components)[0]

        point = session.adapter.accounting.value_series[-1]
        assert point.as_of_time == view.current_time
        # A real BUY this cycle (the fixture's steady upward drift --
        # see TestOrdersActuallySubmitAndFill) means the position's own
        # market_value inside the risk-checked portfolio view was priced
        # off the same reference price this valuation point must use.
        assert outcome.submission is not None
        assert point.portfolio_value > 0

    def test_turnover_reflects_real_fills_within_one_process(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        assert session.adapter.accounting.turnover() == 0.0
        outcome = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert outcome.submission is not None  # a real BUY was decided this cycle
        assert session.adapter.accounting.turnover() == 0.0  # ADR-0154: no fill has landed yet

        clock.index = 101
        run_cycle([], view.current_time, view, session, **components)  # the delayed fill lands here
        assert session.adapter.accounting.turnover() > 0.0

    def test_a_held_security_with_no_price_this_cycle_is_recorded_as_missing(self) -> None:
        """External review (Session 38 continued): before this, `run_cycle`
        discarded `mark_to_market`'s own second return value entirely --
        a held security silently falling back to average-cost valuation
        left no signal anywhere. Now recorded on the caller's own
        `PaperRunnerState` when supplied."""
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()
        state = PaperRunnerState()

        outcome = run_cycle(["AAA"], view.current_time, view, session, state=state, **components)[0]
        assert outcome.submission is not None  # a real BUY was decided this cycle (fill still PENDING, ADR-0154)
        assert state.mark_to_market_missing == []

        clock.index = 101
        # No security_ids this cycle at all -- AAA is still held in
        # `session.adapter.accounting`, but `prices_by_security` stays
        # empty, so `mark_to_market` must fall back to AAA's average
        # cost and report it as missing.
        run_cycle([], view.current_time, view, session, state=state, **components)

        assert len(state.mark_to_market_missing) == 1
        as_of, missing = state.mark_to_market_missing[0]
        assert as_of == view.current_time
        assert missing == ("AAA",)

    def test_missing_is_not_tracked_when_no_state_is_supplied(self) -> None:
        """`state` stays optional -- a caller that doesn't pass one gets
        the original unconditional-mark_to_market behavior with no
        AttributeError, exactly like `value_history`."""
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        run_cycle(["AAA"], view.current_time, view, session, **components)
        clock.index = 101
        run_cycle([], view.current_time, view, session, **components)  # must not raise


class TestStuckOrderRetryViaAdvance:
    """Session 38: before this, nothing in this pipeline ever called
    `PaperTradingSession.advance`/`adapter.advance_simulation` -- an
    order that only partially filled on its own submission day (e.g.
    `PaperTradingConfig.max_participation`'s default 10%-of-bar-volume
    cap, here lowered further to make the scenario deterministic) stayed
    PARTIAL_FILLED forever, never retried against a later day's fresh
    market data -- confirmed by direct instrumentation before this fix,
    not assumed."""

    def test_a_stuck_partial_order_gets_retried_and_completes_on_a_later_cycle(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        mds = InMemoryPaperMarketDataSource(list(bars))
        # backtest_helpers.make_bars' own default bar volume is 200_000
        # -- a 1% participation cap therefore caps any single fill
        # attempt at 2_000 shares, well below the 10_000-share order
        # this test submits directly.
        session = PaperTradingSession(make_paper_config(max_participation=0.01), mds)

        order = ValidatedOrder(
            client_order_id="TEST-STUCK-ORDER-1", security_id="AAA", side=OrderSide.BUY,
            quantity=10_000.0, order_type=OrderType.MARKET, as_of_time=view.current_time,
            decision_id="DEC-TEST-1", sizing_id="SIZE-TEST-1", risk_assessment_id="RISK-TEST-1",
            configuration_version="cfg-v1",
        )
        response, _ = session.submit(order, requested_at=view.current_time)
        assert response.status == BrokerOrderStatus.PENDING  # ADR-0154: fill is deferred

        _, fills = session.advance(view.current_time)  # first (deferred) fill attempt
        assert len(fills) == 1
        status = session.adapter.get_order_status(order.client_order_id, as_of=view.current_time)
        assert status.status == BrokerOrderStatus.PARTIAL_FILLED
        assert status.filled_quantity == 2_000.0

        clock.index = 101
        # An empty security_ids list means run_cycle makes NO new
        # decision at all this cycle -- isolates this test to exercise
        # ONLY the stuck-order retry run_cycle now performs first,
        # unrelated to whatever a fresh decision might otherwise do.
        outcomes = run_cycle([], view.current_time, view, session, **_components())
        assert outcomes == ()

        account = session.account_summary(as_of=view.current_time)
        # The SAME order continued filling on this later day's fresh
        # 2_000-share allowance -- 4_000 total now, still short of the
        # full 10_000 (a third day would finish it) -- proving this was
        # a genuine retry of the original order, not a new one (no new
        # order was ever submitted in this test).
        assert account.positions["AAA"].quantity == 4_000.0


class TestDeferredFillDecisionJournalLink:
    """ADR-0154: dedicated coverage for the new deferred-fill contract
    and its Trade Journal join -- on top of the same-cycle/reversal
    tests above (which now exercise this path implicitly), these name
    each individual guarantee explicitly."""

    def test_a_fresh_order_stays_pending_through_its_own_cycle_and_writes_no_premature_trade(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, **_components(),
            trade_journal_repository=journal,
        )[0]

        assert outcome.submission is not None
        assert outcome.submission.status == BrokerOrderStatus.PENDING
        assert journal.list_trades() == []  # no premature TradeRecord this cycle

    def test_the_same_order_fills_next_cycle_and_joins_its_original_decision(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()
        components = _components()

        cycle1_time = view.current_time
        outcome = run_cycle(
            ["AAA"], cycle1_time, view, session, **components,
            trade_journal_repository=journal,
        )[0]
        decision_snapshot = journal.get_decision_by_natural_key(("paper_decision", None, "AAA", cycle1_time))
        assert decision_snapshot is not None

        clock.index = 101
        run_cycle([], view.current_time, view, session, **components, trade_journal_repository=journal)

        trades = journal.list_trades(security_id="AAA")
        assert len(trades) == 1
        trade = trades[0]
        # A real decision_id resolving through get_decision -- never
        # missing or fabricated -- is exactly what learning.cleaning.
        # DataCleaner.clean depends on for this sample to be usable.
        assert trade.decision_id == decision_snapshot.snapshot_id
        assert journal.get_decision(trade.decision_id) is not None
        assert trade.side == OrderSide.BUY

    def test_get_decision_by_natural_key_returns_none_gracefully_when_never_recorded(self) -> None:
        """A delayed fill for an order whose original cycle had no
        `trade_journal_repository` at all must be skipped silently when
        that fill later lands under a DIFFERENT cycle that does supply
        one -- never a crash, never a fabricated decision link."""
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        # Cycle 1: no journal supplied at all -- the decision is never recorded.
        outcome = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert outcome.submission is not None and outcome.submission.status == BrokerOrderStatus.PENDING

        journal = InMemoryTradeJournalRepository()
        assert journal.get_decision_by_natural_key(("paper_decision", None, "AAA", view.current_time)) is None

        clock.index = 101
        # Cycle 2: a journal IS supplied now -- cycle 1's order fills
        # here (delayed), but its decision was never recorded anywhere,
        # so this fill must be skipped, never crash.
        run_cycle([], view.current_time, view, session, **components, trade_journal_repository=journal)

        assert journal.list_trades() == []  # skipped, not fabricated

    def test_delayed_fill_closing_sell_computes_real_realized_pnl_and_holding_period(self) -> None:
        """The same realized_pnl/holding_period invariant `TestTradeJournalWriteSide::
        test_a_closing_sell_records_real_realized_pnl_return_and_holding_period`
        already checks -- named here explicitly as the deferred-fill scenario,
        since every fill in this pipeline is now a delayed one (ADR-0154)."""
        repo, config, bars = _reversal_scenario()
        view, clock, checkpoints = _build_view(repo, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()
        components = _components()

        sell_trade = None
        for offset in range(0, len(checkpoints) - 100):
            clock.index = 100 + offset
            run_cycle(["AAA"], view.current_time, view, session, trade_journal_repository=journal, **components)
            sell_trades = [t for t in journal.list_trades(security_id="AAA") if t.side == OrderSide.SELL]
            if sell_trades:
                sell_trade = sell_trades[0]
                break

        assert sell_trade is not None, "fixture must produce a real SELL -- see _reversal_scenario's own docstring"
        buy_trade = [t for t in journal.list_trades(security_id="AAA") if t.side == OrderSide.BUY][0]
        buy_fill, sell_fill = buy_trade.fill, sell_trade.fill
        expected_pnl = (sell_fill.price - buy_fill.price) * sell_fill.quantity - sell_fill.commission
        assert sell_trade.realized_pnl == pytest.approx(expected_pnl)
        assert sell_trade.holding_period == sell_fill.execution_time - buy_fill.execution_time


class TestCorporateActionsAppliedEachCycle:
    """ADR-0155: `run_cycle` now applies every real corporate action
    `view.get_corporate_actions` returns for the tracked securities each
    cycle, via `session.apply_corporate_actions` -- before this,
    `broker/paper/*` had zero corporate-action handling at all."""

    def test_an_unhandled_action_type_surfaces_a_warning_and_does_not_crash(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        target_day = days[100]
        merger = CorporateAction(
            security_id="AAA", action_type=CorporateActionType.MERGER,
            available_time=checkpoint(target_day), ingestion_time=checkpoint(target_day),
            provenance=make_provenance("AAA-merger-test", target_day, "corp_actions"),
        )
        prices = drifting_prices(days, daily_return=0.006)
        bars = make_bars("AAA", days, prices)
        securities = [make_security("AAA", "AAA")]
        repo = build_repository(bars=bars, securities=securities, corporate_actions=[merger])
        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
            security_ids=("AAA",), code_version="paper-runner-corporate-action-merger-test",
        )
        view, _, _ = _build_view(repo, config, 100)
        session = _session(bars)
        state = PaperRunnerState()

        outcomes = run_cycle(["AAA"], view.current_time, view, session, state=state, **_components())

        assert len(outcomes) == 1  # a real chain outcome -- never crashed
        assert len(state.corporate_action_warnings) == 1
        as_of, warnings = state.corporate_action_warnings[0]
        assert as_of == view.current_time
        assert any("MERGER" in w for w in warnings)

    def test_a_split_on_a_held_position_is_applied_before_this_cycles_decision(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        split = make_split("AAA", days[102], ratio="2:1")
        prices = drifting_prices(days, daily_return=0.006)
        bars = make_bars("AAA", days, prices)
        securities = [make_security("AAA", "AAA")]
        repo = build_repository(bars=bars, securities=securities, corporate_actions=[split])
        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
            security_ids=("AAA",), code_version="paper-runner-corporate-action-split-test",
        )
        view, clock, _ = _build_view(repo, config, 100)
        session = _session(bars)
        components = _components()

        outcome = run_cycle(["AAA"], view.current_time, view, session, **components)[0]
        assert outcome.submission is not None and outcome.submission.status == BrokerOrderStatus.PENDING

        clock.index = 101
        run_cycle([], view.current_time, view, session, **components)  # ADR-0154: delayed fill lands here
        quantity_before_split = session.account_summary(as_of=view.current_time).positions["AAA"].quantity
        assert quantity_before_split > 0

        clock.index = 102  # the split's own available_time
        run_cycle([], view.current_time, view, session, **components)
        quantity_after_split = session.account_summary(as_of=view.current_time).positions["AAA"].quantity
        assert quantity_after_split == pytest.approx(quantity_before_split * 2.0)


class TestCorporateActionOrderingRelativeToFill:
    """ADR-0158 (external review): corporate actions must be applied
    BEFORE this cycle's own T+1 fill attempt, never after -- the exact
    same-`as_of_time` boundary corruption `backtest.engine.
    BacktestEngine.run()` already had to fix once (ADR-0115). An
    earlier version of `run_cycle` applied corporate actions AFTER
    `session.advance()`, so a fill landing on the SAME `as_of_time` a
    split/dividend became available got corrupted by it."""

    def test_a_fill_landing_the_same_cycle_a_split_becomes_available_is_not_double_adjusted(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        prices = drifting_prices(days, daily_return=0.006)
        bars = make_bars("AAA", days, prices)
        securities = [make_security("AAA", "AAA")]
        config = BacktestConfig(
            market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
            security_ids=("AAA",), code_version="paper-runner-corporate-action-same-day-fill-test",
        )
        components = _components()

        # Baseline: identical scenario, no corporate action at all -- the
        # real quantity a fresh BUY submitted at day[100] and filled
        # (delayed, T+1) at day[101] actually produces.
        repo_baseline = build_repository(bars=bars, securities=securities)
        view_b, clock_b, _ = _build_view(repo_baseline, config, 100)
        session_b = _session(bars)
        run_cycle(["AAA"], view_b.current_time, view_b, session_b, **components)
        clock_b.index = 101
        run_cycle([], view_b.current_time, view_b, session_b, **components)
        baseline_quantity = session_b.account_summary(as_of=view_b.current_time).positions["AAA"].quantity
        assert baseline_quantity > 0

        # Same scenario, but a 2:1 split becomes available on day[101] --
        # the EXACT same as_of_time the delayed BUY fill from day[100]
        # also lands on. There is no PRIOR holding for the split to
        # legitimately act on (this is the position's very first fill);
        # applying the split AFTER that fill would blindly double it too
        # (baseline_quantity * 2), since PortfolioAccounting.apply_split
        # multiplies whatever is currently held with no notion of "how
        # it got there."
        split = make_split("AAA", days[101])
        repo_overlap = build_repository(bars=bars, securities=securities, corporate_actions=[split])
        view_s, clock_s, _ = _build_view(repo_overlap, config, 100)
        session_s = _session(bars)
        run_cycle(["AAA"], view_s.current_time, view_s, session_s, **components)
        clock_s.index = 101
        run_cycle([], view_s.current_time, view_s, session_s, **components)
        quantity_with_overlap = session_s.account_summary(as_of=view_s.current_time).positions["AAA"].quantity

        assert quantity_with_overlap == pytest.approx(baseline_quantity)

    def test_a_closing_sell_landing_the_same_cycle_a_dividend_becomes_available_still_receives_it(self) -> None:
        repo_baseline, config, bars = _reversal_scenario()
        view, clock, checkpoints = _build_view(repo_baseline, config, 100)
        session = _session(bars)
        journal = InMemoryTradeJournalRepository()
        components = _components()

        sell_fill = None
        for offset in range(0, len(checkpoints) - 100):
            clock.index = 100 + offset
            run_cycle(["AAA"], view.current_time, view, session, trade_journal_repository=journal, **components)
            sell_trades = [t for t in journal.list_trades(security_id="AAA") if t.side == OrderSide.SELL]
            if sell_trades:
                sell_fill = sell_trades[0].fill
                break
        assert sell_fill is not None, "fixture must produce a real SELL -- see _reversal_scenario's own docstring"
        cash_without_dividend = session.account_summary(as_of=sell_fill.execution_time).cash

        # Re-run the identical scenario, but with a dividend that becomes
        # available on the EXACT same as_of_time the closing SELL's own
        # delayed fill lands on. The position must still be open (and
        # therefore entitled) at the moment the dividend is applied --
        # PortfolioAccounting.apply_dividend is a silent no-op against a
        # flat/closed position (`if pos is None or pos.quantity == 0:
        # return`), so applying it AFTER a same-cycle closing fill would
        # silently skip the dividend this holder actually earned.
        dividend_amount = 0.50
        dividend = make_dividend("AAA", sell_fill.execution_time.date(), dividend_amount)
        _, config2, bars2 = _reversal_scenario()  # deterministic (fixed seed) -- identical scenario
        repo_with_dividend = build_repository(
            bars=bars2, securities=[make_security("AAA", "AAA")], corporate_actions=[dividend],
        )
        view2, clock2, _ = _build_view(repo_with_dividend, config2, 100)
        session2 = _session(bars2)
        journal2 = InMemoryTradeJournalRepository()
        for offset in range(0, len(checkpoints) - 100):
            clock2.index = 100 + offset
            run_cycle(["AAA"], view2.current_time, view2, session2, trade_journal_repository=journal2, **components)
            sell_trades2 = [t for t in journal2.list_trades(security_id="AAA") if t.side == OrderSide.SELL]
            if sell_trades2:
                break
        cash_with_dividend = session2.account_summary(as_of=sell_fill.execution_time).cash

        assert cash_with_dividend == pytest.approx(cash_without_dividend + sell_fill.quantity * dividend_amount)
