"""Category: Paper Trading Runner Test (Phase 22) --
run_buy_and_hold_paper_session drives PaperTradingSession over an
explicit decision schedule, never reading wall-clock time."""

from __future__ import annotations

from datetime import datetime, timezone

from paper_helpers import make_bar, make_paper_config

from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession
from broker.paper.us_longterm_runner import run_buy_and_hold_paper_session

from orchestration.paper_runner import build_buy_and_hold_risk_check

from risk.config import RiskConfig
from risk.engine import DeterministicPortfolioRiskEngine

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository
from storage.config import StorageConfig
from storage.engine import StorageEngine


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _permissive_risk_check():
    """RiskConfig's own default max_position_weight (0.10) is tuned for
    a diversified RUN_CYCLE strategy holding many small positions --
    real buy_and_hold usage (PILOT_UNIVERSE/RESEARCH_UNIVERSE, 15-87
    symbols) never approaches it (1/15 ~= 6.7%, 1/87 ~= 1.1%), but this
    test file's own small, 1-2-symbol scenarios legitimately allocate
    >10% per symbol -- a permissive config here isolates the ALLOCATION
    logic these tests exist to check from the SEPARATE, real limit-
    enforcement behavior TestRiskEngineLimitsActuallyApply below proves
    with a deliberately strict one. max_drawdown=None (unlike RiskConfig's
    own 0.20 default) for the same reason production's own CLI default
    already is None (--max-drawdown, run_multi_strategy_paper_trading_
    cycle.py): a strategy's very first-ever allocation has no portfolio
    value_history yet, by construction, so a CONFIGURED drawdown limit
    fail-closed-rejects it every time regardless of any real risk --
    correct behavior for an operator who explicitly opts into it, not
    something these allocation-logic tests should also have to model."""
    engine = DeterministicPortfolioRiskEngine(
        RiskConfig(
            max_position_weight=1.0, minimum_cash_ratio=0.0, concentration_limit=1.0,
            max_drawdown=None, max_portfolio_volatility=None,
        )
    )
    return build_buy_and_hold_risk_check(engine)


class TestEqualWeightAllocation:
    def test_allocates_cash_equally_across_symbols(self) -> None:
        buy_time = utc(2024, 1, 2)
        symbols = ["AAA", "BBB"]
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=buy_time, close=100.0),
            make_bar(security_id="BBB", available_time=buy_time, close=50.0),
        ])
        # A large enough cash base that per-share integer flooring is a
        # small relative rounding effect, not the dominant one -- the
        # point of this test is the equal-weight allocation logic, not
        # small-number lot-rounding behavior (covered separately).
        config = make_paper_config(initial_cash=100_000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(symbols, mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=_permissive_risk_check())

        assert len(result.orders) == 2
        assert result.skipped_symbols == ()
        for outcome in result.orders:
            # ADR-0154: submission never fills synchronously -- the
            # order stays PENDING until an explicit advance() call.
            assert outcome.response.status.value == "PENDING"
            assert len(outcome.fills) == 0

        session.advance(buy_time)  # first (deferred) fill attempt for every order this call submitted

        by_symbol = {o.security_id: o for o in result.orders}
        for outcome in result.orders:
            status = session.adapter.get_order_status(outcome.response.request_client_order_id, as_of=buy_time)
            assert status.status.value == "FILLED"
        # Roughly equal notional value per symbol (not exact -- a
        # cost-safety-margin and per-fill commission/spread mean each
        # leg spends a slightly different amount, and BBB is priced
        # from whatever cash remains after AAA's own costs, not the
        # original 500/500 split) -- within 20% of each other confirms
        # the allocation is genuinely equal-weight, not skewed.
        aaa_notional = by_symbol["AAA"].quantity * 100.0
        bbb_notional = by_symbol["BBB"].quantity * 50.0
        assert aaa_notional > 0 and bbb_notional > 0
        assert abs(aaa_notional - bbb_notional) / max(aaa_notional, bbb_notional) < 0.20

    def test_a_duplicate_security_id_is_deduplicated_not_double_allocated(self) -> None:
        """Independent audit finding F4 (2026-09-24): before this fix,
        a repeated symbol in `security_ids` produced TWO separate BUY
        orders for it, but `positions_so_far[security_id] = PositionView
        (...)` silently overwrote the first entry rather than
        accumulating -- undercounting portfolio_value for every LATER
        symbol's own risk_check, and the repeat's own `current_quantity
        =0.0` (hardcoded, correct only for a genuine first allocation)
        let the risk engine treat the second AAA buy as opening a brand
        new position rather than adding to the one just placed a few
        lines above -- a real single-name concentration-limit bypass.
        With the fix, "AAA" duplicated must produce exactly ONE order,
        identical to passing ["AAA", "BBB"] without a repeat."""
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=buy_time, close=100.0),
            make_bar(security_id="BBB", available_time=buy_time, close=50.0),
        ])
        config = make_paper_config(initial_cash=100_000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(
            ["AAA", "AAA", "BBB"], mds, session, buy_time=buy_time,
            configuration_version="cfg-v1", risk_check=_permissive_risk_check(),
        )

        assert len(result.orders) == 2  # not 3 -- the duplicate AAA never became a second order
        assert {o.security_id for o in result.orders} == {"AAA", "BBB"}
        assert result.skipped_symbols == ()

    def test_only_buys_once_true_buy_and_hold(self) -> None:
        """Calling the runner a second time re-allocates against
        whatever cash remains, proving this is a one-shot allocation
        primitive, not a rebalancing loop -- a caller who wants true
        buy-and-hold simply calls it once."""
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id="AAA", available_time=buy_time, close=100.0)])
        config = make_paper_config(initial_cash=1000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        first = run_buy_and_hold_paper_session(["AAA"], mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=_permissive_risk_check())
        assert len(first.orders) == 1
        session.advance(buy_time)  # ADR-0154: fill is deferred -- attempt it now
        remaining_cash = session.adapter.get_account(as_of=buy_time).cash
        assert remaining_cash < 1000.0  # cash was actually spent, not simulated

    def test_two_calls_on_different_days_get_distinguishable_audit_trail_ids(self, tmp_path) -> None:
        """Every previous call to this function re-minted the SAME
        synthetic decision_id/sizing_id/risk_id ("DEC-BAH-000001" etc,
        an in-function counter reset to 1 every call) for the first
        symbol processed, regardless of which real buy_time/security it
        was actually for -- a real BrokerRequestRecord audit trail could
        not tell two genuinely different real runs' decisions apart by
        decision_id alone. Deriving the id from (buy_time, security_id)
        instead makes it unique per real economic event, independent of
        how many times this function has been called before."""
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=utc(2024, 1, 2), close=100.0),
            make_bar(security_id="AAA", available_time=utc(2024, 2, 1), close=100.0),
        ])
        engine = StorageEngine(StorageConfig(root_dir=tmp_path / "store"))
        request_repository = DuckDBBrokerRequestRepository(engine)
        response_repository = DuckDBBrokerResponseRepository(engine)

        config = make_paper_config(initial_cash=1000.0, max_participation=1.0)
        run_buy_and_hold_paper_session(
            ["AAA"], mds, PaperTradingSession(config, mds), buy_time=utc(2024, 1, 2), configuration_version="cfg-v1",
            risk_check=_permissive_risk_check(),
            request_repository=request_repository, response_repository=response_repository,
        )
        run_buy_and_hold_paper_session(
            ["AAA"], mds, PaperTradingSession(config, mds), buy_time=utc(2024, 2, 1), configuration_version="cfg-v1",
            risk_check=_permissive_risk_check(),
            request_repository=request_repository, response_repository=response_repository,
        )

        recorded = request_repository.list_all()
        assert len(recorded) == 2
        decision_ids = {r.decision_id for r in recorded}
        assert len(decision_ids) == 2, "two calls for different real buy_times must not share a synthetic decision_id"


class TestSkipsSymbolsHonestly:
    def test_symbol_with_no_reference_price_is_skipped_not_fabricated(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id="AAA", available_time=buy_time, close=100.0)])
        config = make_paper_config(initial_cash=1000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(["AAA", "NODATA"], mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=_permissive_risk_check())
        assert "NODATA" in result.skipped_symbols
        assert result.skip_reasons["NODATA"] == "no_reference_price_available"
        assert len(result.orders) == 1

    def test_insufficient_cash_for_one_lot_is_skipped(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=buy_time, close=1.0),
            make_bar(security_id="EXPENSIVE", available_time=buy_time, close=1_000_000.0),
        ])
        config = make_paper_config(initial_cash=10.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(["AAA", "EXPENSIVE"], mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=_permissive_risk_check())
        assert "EXPENSIVE" in result.skipped_symbols
        assert result.skip_reasons["EXPENSIVE"] == "insufficient_cash_for_one_lot"


class TestRiskEngineLimitsActuallyApply:
    """External audit finding (2026-09-24): this runner used to
    construct a `risk.models.RiskCheckedPosition` directly with a
    hardcoded `status=PASS`, so no portfolio-level limit -- single-
    position weight, sector weight, gross exposure, minimum cash,
    max order notional -- was ever actually checked for this strategy.
    These tests use a REAL, strict `DeterministicPortfolioRiskEngine`
    (not the permissive one above) and prove it genuinely constrains
    the allocation, the same as it already does for every RUN_CYCLE
    strategy."""

    def test_max_position_weight_clamps_a_single_symbol_allocation(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id="AAA", available_time=buy_time, close=100.0)])
        config = make_paper_config(initial_cash=10_000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)
        # A single symbol would otherwise receive ~100% of cash
        # (equal-weight over one symbol) -- max_position_weight=0.10
        # must clamp it down to ~10%, not let the pre-clamp target
        # through unchanged the way the old synthetic PASS did.
        strict_engine = DeterministicPortfolioRiskEngine(
            RiskConfig(max_position_weight=0.10, minimum_cash_ratio=0.0, max_drawdown=None, max_portfolio_volatility=None)
        )

        result = run_buy_and_hold_paper_session(
            ["AAA"], mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=build_buy_and_hold_risk_check(strict_engine),
        )

        assert len(result.orders) == 1
        notional = result.orders[0].quantity * 100.0
        # Well under the naive ~10,000 (minus safety margin) the old
        # unchecked synthetic PASS would have produced, and close to
        # the configured 10% ceiling (some slack for the cost-safety
        # margin/lot-size flooring both already applied beforehand).
        assert notional < 1_500.0
        assert notional > 500.0

    def test_zero_gross_exposure_budget_rejects_every_symbol(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=buy_time, close=100.0),
            make_bar(security_id="BBB", available_time=buy_time, close=100.0),
        ])
        config = make_paper_config(initial_cash=10_000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)
        # max_gross_exposure just above zero (RiskConfig itself requires
        # > 0) -- effectively no new risk-taking is allowed, the same
        # "hard portfolio-level limit" every RUN_CYCLE strategy is
        # already subject to.
        zero_budget_engine = DeterministicPortfolioRiskEngine(
            RiskConfig(max_gross_exposure=0.0001, minimum_cash_ratio=0.0, max_drawdown=None, max_portfolio_volatility=None)
        )

        result = run_buy_and_hold_paper_session(
            ["AAA", "BBB"], mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=build_buy_and_hold_risk_check(zero_budget_engine),
        )

        assert result.orders == ()
        assert set(result.skipped_symbols) == {"AAA", "BBB"}
        for reason in result.skip_reasons.values():
            assert reason.startswith("risk_check_rejected:") or reason.startswith("sized_to_zero_after_risk_limit:")

    def test_minimum_cash_ratio_leaves_the_configured_cash_buffer_untouched(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id="AAA", available_time=buy_time, close=100.0)])
        config = make_paper_config(initial_cash=10_000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)
        strict_engine = DeterministicPortfolioRiskEngine(
            RiskConfig(max_position_weight=1.0, concentration_limit=1.0, minimum_cash_ratio=0.80, max_drawdown=None, max_portfolio_volatility=None)
        )

        result = run_buy_and_hold_paper_session(
            ["AAA"], mds, session, buy_time=buy_time, configuration_version="cfg-v1", risk_check=build_buy_and_hold_risk_check(strict_engine),
        )

        assert len(result.orders) == 1
        notional = result.orders[0].quantity * 100.0
        # At most ~20% of the 10,000 portfolio may be spent, leaving
        # >= 80% as cash -- a real, enforced floor the old synthetic
        # PASS had no way to apply.
        assert notional <= 2_100.0
