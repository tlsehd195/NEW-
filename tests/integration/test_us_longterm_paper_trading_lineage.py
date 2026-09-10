"""Category: Integration Test (Phase 22, instruction section 24) -- the
full lineage the instruction names, exercised end to end with real
on-disk DuckDB persistence and a process restart:

  TiingoDataProvider (real, non-mock DataProvider; TEST FIXTURE data,
    Tiingo-shaped, never fetched live -- ADR-0025)
    -> IngestionRunner (Phase 1, unmodified)
    -> DuckDBDataRepository (Phase 4, unmodified, real on-disk catalog)
    -> point-in-time get_bars(as_of_time=...)
    -> InMemoryPaperMarketDataSource (built from repository-fetched
       bars, not a hand fixture)
    -> run_buy_and_hold_paper_session (Phase 22) driving
       PaperTradingSession/PaperBrokerAdapter (Phase 15, unmodified)
    -> DuckDBTradeJournalRepository (Phase 3, unmodified)
    -> monitoring.collectors.collect_broker (Phase 14, unmodified)
    -> compute_paper_performance_report (Phase 18, unmodified)

using a 3-symbol subset of the Phase 22 default 16-symbol US long-term
Paper Trading universe (AAPL, MSFT, JPM) and the Phase 22 reference
USD Paper capital (`us_longterm_config.PAPER_CAPITAL_USD`).

Every module downstream of TiingoDataProvider is completely unmodified
by Phase 22 -- this test only proves the chain is structurally
connectable end to end, including surviving a restart, using small
TEST FIXTURE data. No real network call is made anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from storage_helpers import new_engine

from broker.paper.config import PaperTradingConfig
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.performance import compute_paper_performance_report
from broker.paper.session import PaperTradingSession
from broker.paper.us_longterm_config import PAPER_CAPITAL_USD, build_us_longterm_paper_config
from broker.paper.us_longterm_runner import run_buy_and_hold_paper_session
from data_infra.provider import IngestionRunner
from data_infra.providers.tiingo import TiingoDataProvider
from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.providers.tiingo_transport import TiingoTransportResponse

from monitoring.collectors import collect_broker
from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository, DuckDBOrderStatusEventRepository
from storage.data_repository import DuckDBDataRepository
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from trade_journal.enums import DecisionAction, TradeProvenance


def utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


# TEST FIXTURE / SYNTHETIC: Tiingo-shaped raw daily bars for a 3-symbol
# subset of the Phase 22 default universe -- small, plausible,
# real-market-scale values, never fetched live this session (network
# access to api.tiingo.com is blocked from this environment, ADR-0025).
_FIXTURE_BODIES = {
    "AAPL": [
        {"date": "2024-01-02T00:00:00.000Z", "open": "185.0", "high": "186.5", "low": "184.2",
         "close": "185.64", "volume": "82488700", "adjClose": "185.64", "splitFactor": "1.0", "divCash": "0.0"},
        {"date": "2024-06-03T00:00:00.000Z", "open": "192.0", "high": "193.5", "low": "191.0",
         "close": "192.25", "volume": "50000000", "adjClose": "192.25", "splitFactor": "1.0", "divCash": "0.0"},
    ],
    "MSFT": [
        {"date": "2024-01-02T00:00:00.000Z", "open": "370.0", "high": "372.0", "low": "368.0",
         "close": "370.87", "volume": "20000000", "adjClose": "370.87", "splitFactor": "1.0", "divCash": "0.0"},
        {"date": "2024-06-03T00:00:00.000Z", "open": "415.0", "high": "417.0", "low": "413.0",
         "close": "416.02", "volume": "18000000", "adjClose": "416.02", "splitFactor": "1.0", "divCash": "0.0"},
    ],
    "JPM": [
        {"date": "2024-01-02T00:00:00.000Z", "open": "170.0", "high": "171.5", "low": "169.0",
         "close": "170.10", "volume": "9000000", "adjClose": "170.10", "splitFactor": "1.0", "divCash": "0.0"},
        {"date": "2024-06-03T00:00:00.000Z", "open": "198.0", "high": "200.0", "low": "197.0",
         "close": "199.50", "volume": "8500000", "adjClose": "199.50", "splitFactor": "1.0", "divCash": "0.0"},
    ],
}

_UNIVERSE_SUBSET = ["AAPL", "MSFT", "JPM"]


class _RoutingStubTransport:
    """Never reaches the network -- routes each symbol's fetch to its
    own fixture body, keyed by the last path segment Tiingo's
    per-symbol endpoint carries."""

    def get(self, path, *, params, timeout):
        for symbol, body in _FIXTURE_BODIES.items():
            if f"/{symbol}/" in path:
                return TiingoTransportResponse(status_code=200, body=body, raw_text=None, headers={})
        raise AssertionError(f"no fixture registered for path {path!r}")


class TestUSLongTermPaperTradingFullLineage:
    def test_ingestion_to_performance_report_survives_restart(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
        buy_day, mark_day = utc(2024, 1, 2), utc(2024, 6, 3)
        # Session 36 continued (external review remediation): a bar's
        # `available_time` is now end-of-session (20:00 UTC) on its own
        # date, not the bare midnight-UTC event date `buy_day` itself
        # (`data_infra.provider.bar_available_time`) -- the actual
        # `as_of` moment passed to `run_buy_and_hold_paper_session` must
        # be realistically AFTER that, matching how a real caller (e.g.
        # `scripts/run_paper_trading_cycle.py`, via `backtest.clock.
        # build_daily_checkpoints`'s own 20:00 UTC default) would
        # actually invoke it. `buy_day` itself stays at midnight --
        # still used below to match `PriceBar.timestamp` (the bar's own
        # event date), a separate field from `available_time`.
        buy_time = utc(2024, 1, 2, 20)

        # -- 1. Real (non-mock) provider, real IngestionRunner, real
        # on-disk DuckDB repository for every symbol in the subset. --
        provider = TiingoDataProvider(TiingoConfig(), _RoutingStubTransport())
        engine = new_engine(tmp_path)
        data_repo = DuckDBDataRepository(engine)
        result = IngestionRunner(provider, data_repo).run(_UNIVERSE_SUBSET, utc(2024, 1, 1), utc(2024, 6, 4))
        assert result.status.value == "SUCCESS"

        # -- 2. Point-in-time query back out of the repository -- the
        # PaperMarketDataSource is built from what the repository
        # actually returns, not from the raw fixture. --
        all_bars = []
        for symbol in _UNIVERSE_SUBSET:
            all_bars.extend(data_repo.get_bars(symbol, utc(2024, 1, 1), utc(2024, 6, 4), as_of_time=utc(2024, 6, 4)))
        assert len(all_bars) == 6  # 3 symbols x 2 dates

        # -- 3. Reference Phase 22 Paper config (USD-denominated
        # stand-in for the user's stated 10,000,000 KRW target -- see
        # us_longterm_config's own docstring for why no FX conversion
        # is performed) + the Buy & Hold runner, over the real
        # repository-fetched bars. --
        mds = InMemoryPaperMarketDataSource(all_bars)
        config = build_us_longterm_paper_config(max_participation=1.0)
        assert config.initial_cash == PAPER_CAPITAL_USD

        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        session = PaperTradingSession(
            config, mds,
            order_repository=DuckDBPaperOrderRepository(engine),
            fill_repository=DuckDBPaperFillRepository(engine),
            status_repository=DuckDBOrderStatusEventRepository(engine),
        )
        journal_repo = DuckDBTradeJournalRepository(engine)

        buy_result = run_buy_and_hold_paper_session(
            _UNIVERSE_SUBSET, mds, session, buy_time=buy_time, configuration_version="cfg-v1",
            request_repository=request_repo, response_repository=response_repo,
        )
        assert len(buy_result.orders) == 3
        assert buy_result.skipped_symbols == ()

        # -- Record each buy as a Trade Journal decision+trade -- the
        # broker_requests/broker_responses audit trail was already
        # populated by the runner itself (via request_repository/
        # response_repository above), one record per real order, no
        # separate/duplicate submission needed. --
        for outcome in buy_result.orders:
            decision = journal_repo.record_decision(decision_time=buy_day, security_id=outcome.security_id, decision=DecisionAction.BUY)
            journal_repo.record_trade(
                decision_id=decision.snapshot_id, fill=outcome.fills[0].fill, position_after=outcome.quantity,
                provenance=TradeProvenance.PAPER_TRADING,
            )

        # -- Mark to market at buy_day itself first (the performance
        # report needs at least two valuation points to compute a
        # return at all -- Phase 18's own "never fabricate 0.0 for
        # insufficient data" discipline, unchanged here). --
        buy_day_prices = {
            symbol: next(b.close for b in all_bars if b.security_id == symbol and b.timestamp == buy_day)
            for symbol in _UNIVERSE_SUBSET
        }
        session.adapter.accounting.mark_to_market(buy_day_prices, buy_day)

        # -- Mark to market at the later date using the same
        # repository-fetched bars, then confirm the account genuinely
        # moved (real price change, not a static snapshot). --
        mark_prices = {
            symbol: next(b.close for b in all_bars if b.security_id == symbol and b.timestamp == mark_day)
            for symbol in _UNIVERSE_SUBSET
        }
        session.adapter.accounting.mark_to_market(mark_prices, mark_day)

        trades = journal_repo.list_trades(provenance=TradeProvenance.PAPER_TRADING)
        assert len(trades) == 3

        # -- 4. Monitoring: the generic Phase 14 broker collector,
        # unmodified, observing the audit records this real-data-fed
        # Buy & Hold run actually produced. --
        monitoring_config = MonitoringConfig(min_sample_count=1)
        event, health = collect_broker(
            response_repo.list_all(), request_repo.list_all(), as_of_time=mark_day, observed_at=mark_day,
            config=monitoring_config, event_id="MONEVT-USLT001", health_id="HEALTH-USLT001",
        )
        assert health.status == ComponentHealthStatus.HEALTHY
        assert event.metrics["count"] == 3.0

        # -- 5. Performance Report: Phase 18, unmodified, over the
        # equity curve PortfolioAccounting actually built. --
        equity_history = [(p.as_of_time, p.portfolio_value) for p in session.adapter.accounting.value_series]
        report = compute_paper_performance_report(
            report_id="RPT-USLT001", paper_session_id="SESSION-USLT1", equity_history=equity_history,
            trades=trades, evaluated_at=mark_day, turnover=session.adapter.accounting.turnover(),
        )
        assert report.num_trades == 3
        # All three symbols in this fixture appreciated from Jan to
        # June -- an honest, real-data-driven positive result, not
        # asserted as "proof of alpha" (the strategy is a Buy & Hold
        # baseline, not a claimed edge -- ADR-0028).
        assert report.total_return is not None and report.total_return > 0

        engine.close()

        # -- 6. Restart: reopen the same DuckDB/Parquet catalog file --
        # both the real ingested market data and the full Paper Trading
        # lineage are still there, unchanged. --
        engine2 = new_engine(tmp_path)
        reloaded_bars = DuckDBDataRepository(engine2).get_bars("AAPL", utc(2024, 1, 1), utc(2024, 6, 4), as_of_time=utc(2024, 6, 4))
        assert len(reloaded_bars) == 2
        assert reloaded_bars[0].close == 185.64  # the raw ingested value, unchanged by any of the Paper Trading activity above

        reloaded_trades = DuckDBTradeJournalRepository(engine2).list_trades(provenance=TradeProvenance.PAPER_TRADING)
        assert len(reloaded_trades) == 3

        reloaded_order = DuckDBPaperOrderRepository(engine2).get(buy_result.orders[0].response.request_client_order_id)
        assert reloaded_order is not None

        engine2.close()
