"""Category: Integration Test (Phase 20, instruction section 15) --
proves the full path this phase's real market data is meant to feed:

  TiingoDataProvider.fetch/normalize (real, non-mock DataProvider)
    -> IngestionRunner (Phase 1, unmodified)
    -> DuckDBDataRepository (Phase 4, unmodified, real on-disk catalog)
    -> DataRepository.get_bars(as_of_time=...) (point-in-time query)
    -> InMemoryPaperMarketDataSource, built from repository-fetched
       PriceBars, not a hand-built fixture (Phase 15, unmodified)
    -> PaperTradingSession/PaperBrokerAdapter (Phase 15, unmodified)
    -> DuckDBTradeJournalRepository (Phase 3, unmodified)
    -> monitoring.collectors.collect_broker (Phase 14, unmodified)
    -> compute_paper_performance_report (Phase 18, unmodified)

is *structurally connectable* end to end -- every module downstream of
TiingoDataProvider is completely unmodified by Phase 20; only the data
source at the very top of the chain is new. This directly answers
instruction section 15 ("verify this path is structurally connectable,
with an end-to-end test using small real historical data where
possible") without building an always-on polling loop, which that same
section explicitly says is not required this phase.

**Honesty about the data**: network access to Tiingo is blocked from
this environment (ADR-0025), so the transport below is a stub, like
every other Tiingo test this phase -- but the raw records it returns are
genuinely Tiingo-shaped, and parsed by the real, unmodified
TiingoDataProvider.normalize()/fetch() code, not a hand-built PriceBar.
The AAPL close values used are small, plausible, real-market-scale
figures (the 2024-01-02 value matches the one already used in
tests/integration/test_market_data_point_in_time.py) -- not
independently re-verified against a live feed this session, and not
claimed as verified ground truth anywhere in this repository.
"""

from __future__ import annotations

from broker_helpers import make_risk_checked_position
from storage_helpers import new_engine

from broker.paper.config import PaperTradingConfig
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.performance import compute_paper_performance_report
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from data_infra.provider import IngestionRunner
from data_infra.providers.tiingo import TiingoDataProvider
from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.providers.tiingo_transport import TiingoTransportResponse

from monitoring.collectors import collect_broker
from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus

from storage.broker_repository import (
    DuckDBBrokerRequestRepository,
    DuckDBBrokerResponseRepository,
    DuckDBOrderStatusEventRepository,
)
from storage.data_repository import DuckDBDataRepository
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from trade_journal.enums import DecisionAction, TradeProvenance


def utc(year, month, day, hour=0):
    from datetime import datetime, timezone

    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class _StubTransport:
    """Never reaches the network (ADR-0025) -- returns fixed,
    Tiingo-shaped AAPL rows regardless of the request."""

    def __init__(self, body) -> None:
        self._body = body

    def get(self, path, *, params, timeout):
        return TiingoTransportResponse(status_code=200, body=self._body, raw_text=None, headers={})


class TestRealMarketDataFeedsPaperTradingEndToEnd:
    def test_ingested_tiingo_data_flows_through_paper_trading_to_a_performance_report(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
        buy_day, sell_day = utc(2024, 1, 2), utc(2024, 1, 3)
        # Session 36 continued (external review remediation): a bar's
        # `available_time` is now end-of-session (20:00 UTC) on its own
        # date (`data_infra.provider.bar_available_time`), not the bare
        # midnight-UTC event date -- any `as_of`/`requested_at` actually
        # used to look up a reference bar must be realistically after
        # that. `buy_day`/`sell_day` stay at midnight -- still used
        # below to match `PriceBar.timestamp` (the bar's own event
        # date, a separate field from `available_time`) and for
        # decision/risk metadata timestamps, neither of which drives a
        # reference-bar lookup.
        buy_time, sell_time = utc(2024, 1, 2, 20), utc(2024, 1, 3, 20)
        raw_body = [
            {"date": "2024-01-02T00:00:00.000Z", "open": "185.0", "high": "186.5", "low": "184.2",
             "close": "185.64", "volume": "82488700", "adjClose": "185.64", "splitFactor": "1.0", "divCash": "0.0"},
            {"date": "2024-01-03T00:00:00.000Z", "open": "184.5", "high": "185.9", "low": "183.6",
             "close": "184.25", "volume": "58414500", "adjClose": "184.25", "splitFactor": "1.0", "divCash": "0.0"},
        ]

        # -- 1. Real (non-mock) provider, real IngestionRunner, real
        # on-disk DuckDB repository -- exactly the Phase 1 pipeline,
        # with TiingoDataProvider as the only new component. --
        provider = TiingoDataProvider(TiingoConfig(), _StubTransport(raw_body))
        engine = new_engine(tmp_path)
        data_repo = DuckDBDataRepository(engine)
        result = IngestionRunner(provider, data_repo).run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 4))
        assert result.status.value == "SUCCESS"

        # -- 2. Point-in-time query back out of the repository -- the
        # PaperMarketDataSource below is built from what the repository
        # actually returns, not from the raw fixture. --
        ingested_bars = data_repo.get_bars("AAPL", utc(2024, 1, 1), utc(2024, 1, 4), as_of_time=utc(2024, 1, 4))
        assert len(ingested_bars) == 2
        assert {b.timestamp for b in ingested_bars} == {buy_day, sell_day}

        # -- 3. PaperMarketDataSource, PaperTradingSession, and every
        # other broker.paper.* / storage.* / trade_journal.* /
        # monitoring.* component below this point is Phase 3/4/14/15/18
        # code, completely unmodified this phase. --
        mds = InMemoryPaperMarketDataSource(ingested_bars)
        config = PaperTradingConfig(initial_cash=1_000_000.0, max_participation=1.0)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        session = PaperTradingSession(
            config, mds,
            order_repository=DuckDBPaperOrderRepository(engine),
            fill_repository=DuckDBPaperFillRepository(engine),
            status_repository=DuckDBOrderStatusEventRepository(engine),
        )
        journal_repo = DuckDBTradeJournalRepository(engine)

        buy_risk = make_risk_checked_position(
            risk_id="RISK-RD0001", security_id="AAPL", as_of_time=buy_day,
            final_target_quantity=100.0, provenance=TradeProvenance.PAPER_TRADING,
        )
        buy_validation = build_validated_order(buy_risk, current_quantity=0.0, configuration_version="cfg-v1")
        buy_order = buy_validation.validated_order
        assert buy_order is not None

        buy_decision = journal_repo.record_decision(
            decision_time=buy_day, security_id="AAPL", decision=DecisionAction.BUY,
        )
        buy_response = submit_validated_order(
            session.adapter, buy_order, execution_mode="PAPER", requested_at=buy_time,
            configuration_version="cfg-v1", request_repository=request_repo, response_repository=response_repo,
        )
        buy_fills = session.capture(buy_order.client_order_id, as_of=buy_time)
        assert buy_response.status.value == "FILLED"
        assert len(buy_fills) == 1
        # -- the fill price is derived from the real ingested bar's
        # close (185.64), through the cost model, not a fixture value --
        assert buy_fills[0].fill.price > 0
        journal_repo.record_trade(
            decision_id=buy_decision.snapshot_id, fill=buy_fills[0].fill, position_after=100.0,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        session.adapter.accounting.mark_to_market({"AAPL": 185.64}, buy_day)

        sell_risk = make_risk_checked_position(
            risk_id="RISK-RD0002", security_id="AAPL", as_of_time=sell_day,
            final_target_quantity=0.0, provenance=TradeProvenance.PAPER_TRADING,
        )
        sell_validation = build_validated_order(sell_risk, current_quantity=100.0, configuration_version="cfg-v1")
        sell_order = sell_validation.validated_order
        assert sell_order is not None

        sell_decision = journal_repo.record_decision(
            decision_time=sell_day, security_id="AAPL", decision=DecisionAction.SELL,
        )
        sell_response = submit_validated_order(
            session.adapter, sell_order, execution_mode="PAPER", requested_at=sell_time,
            configuration_version="cfg-v1", request_repository=request_repo, response_repository=response_repo,
        )
        sell_fills = session.capture(sell_order.client_order_id, as_of=sell_time)
        assert sell_response.status.value == "FILLED"
        journal_repo.record_trade(
            decision_id=sell_decision.snapshot_id, fill=sell_fills[0].fill, position_after=0.0,
            realized_pnl=sell_fills[0].fill.price * 100.0 - buy_fills[0].fill.price * 100.0,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        session.adapter.accounting.mark_to_market({"AAPL": 184.25}, sell_day)

        trades = journal_repo.list_trades(provenance=TradeProvenance.PAPER_TRADING)
        assert len(trades) == 2

        # -- 4. Monitoring: the generic Phase 14 broker collector,
        # unmodified, observing requests/responses this real-data-fed
        # session actually produced. --
        monitoring_config = MonitoringConfig(min_sample_count=1)
        event, health = collect_broker(
            response_repo.list_all(), request_repo.list_all(), as_of_time=sell_time, observed_at=sell_time,
            config=monitoring_config, event_id="MONEVT-RD0001", health_id="HEALTH-RD0001",
        )
        assert health.status == ComponentHealthStatus.HEALTHY
        assert event.metrics["count"] == 2.0

        # -- 5. Performance Report: Phase 18, unmodified, over the
        # equity curve PortfolioAccounting actually built from these
        # real-data-priced fills. --
        equity_history = [(p.as_of_time, p.portfolio_value) for p in session.adapter.accounting.value_series]
        report = compute_paper_performance_report(
            report_id="RPT-RD0001", paper_session_id="SESSION-RD1", equity_history=equity_history,
            trades=trades, evaluated_at=sell_time, turnover=session.adapter.accounting.turnover(),
        )
        assert report.num_trades == 2
        # AAPL dropped from 185.64 to 184.25 over this window -- the
        # report must honestly reflect a loss, not a fabricated gain.
        assert report.realized_pnl is not None and report.realized_pnl < 0

        engine.close()
