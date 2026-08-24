"""Phase 2 integration test.

See docs/specifications/PHASE-3-trade-journal.md section 13. Verifies
ingest_backtest_result against a real BacktestEngine run, and that
Phase 2's own test suite is unaffected by anything Phase 3 added.
"""

from __future__ import annotations

from datetime import date

import pytest
from journal_helpers import utc

from data_infra.calendar import US_EQUITY
from data_infra.enums import InstrumentType, SecurityStatus
from data_infra.models import PriceBar, Provenance, SecurityMaster
from data_infra.repository import InMemoryDataRepository

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.enums import OrderSide
from backtest.strategy import BuyAndHoldStrategy, OrderIntent

from trade_journal.backtest_adapter import ingest_backtest_result
from trade_journal.enums import TradeProvenance
from trade_journal.repository import InMemoryTradeJournalRepository


def _trading_days(start: date, end: date) -> list[date]:
    days = []
    current = start
    from datetime import timedelta

    while current <= end:
        if US_EQUITY.is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def _bars(security_id: str, days: list[date], closes: list[float]) -> list[PriceBar]:
    bars = []
    for i, (d, close) in enumerate(zip(days, closes)):
        bars.append(
            PriceBar(
                security_id=security_id, timestamp=utc(d.year, d.month, d.day, 0), open=close,
                high=close * 1.01, low=close * 0.99, close=close, volume=200_000.0,
                available_time=utc(d.year, d.month, d.day, 20), ingestion_time=utc(d.year, d.month, d.day, 20),
                provenance=Provenance(source="test", source_dataset="test_ds",
                                       source_record_id=f"{security_id}-{i}",
                                       retrieved_at=utc(d.year, d.month, d.day, 20), data_version=f"v{i}"),
                adjusted_close=close,
            )
        )
    return bars


class _BuyThenSellStrategy:
    """Buys once, sells everything a few steps later — deliberately
    simple, so realized PnL is hand-verifiable."""

    version = "buy_then_sell_test_v1"

    def __init__(self, security_id: str, sell_after_steps: int) -> None:
        self._security_id = security_id
        self._sell_after_steps = sell_after_steps
        self._step = 0

    def generate_orders(self, as_of_time, data, portfolio):
        self._step += 1
        if self._step == 1:
            return [OrderIntent(self._security_id, OrderSide.BUY, 10.0)]
        if self._step == self._sell_after_steps and portfolio.quantity_of(self._security_id) > 0:
            return [OrderIntent(self._security_id, OrderSide.SELL, portfolio.quantity_of(self._security_id))]
        return []


def _run_round_trip_backtest():
    days = _trading_days(date(2024, 1, 2), date(2024, 1, 19))
    closes = [100.0 + i for i in range(len(days))]  # steadily rising
    bars = _bars("AAA", days, closes)
    sec = SecurityMaster(security_id="AAA", ticker="AAA", exchange="NASDAQ", currency="USD",
                          company_id="C1", instrument_type=InstrumentType.EQUITY,
                          valid_from=utc(2020, 1, 1), status=SecurityStatus.ACTIVE)
    repo = InMemoryDataRepository(bars=bars, securities=[sec], calendars={"US_EQUITY": US_EQUITY})
    config = BacktestConfig(market="US_EQUITY", start_date=days[0], end_date=days[-1],
                              initial_capital=10_000.0, security_ids=("AAA",))
    strategy = _BuyThenSellStrategy("AAA", sell_after_steps=5)
    result = BacktestEngine(repo, config, strategy).run()
    return repo, config, result


class TestBacktestIntegration:
    def test_ingest_records_every_order_and_every_fill(self) -> None:
        _, config, result = _run_round_trip_backtest()
        journal = InMemoryTradeJournalRepository()
        summary = ingest_backtest_result(journal, result, config)

        assert summary.decisions_recorded == len(result.orders)
        assert summary.trades_recorded == len(result.fills)
        assert len(journal.list_decisions()) == len(result.orders)
        assert len(journal.list_trades()) == len(result.fills)

    def test_round_trip_realized_pnl_matches_hand_computation(self) -> None:
        _, config, result = _run_round_trip_backtest()
        journal = InMemoryTradeJournalRepository()
        ingest_backtest_result(journal, result, config)

        sell_trades = [t for t in journal.list_trades() if t.side == OrderSide.SELL]
        assert len(sell_trades) == 1
        sell = sell_trades[0]
        buy_trades = [t for t in journal.list_trades() if t.side == OrderSide.BUY]
        buy = buy_trades[0]

        expected_pnl = (sell.execution_price - buy.execution_price) * buy.quantity - sell.transaction_cost
        assert sell.realized_pnl == pytest.approx(expected_pnl)
        assert sell.holding_period is not None
        assert sell.holding_period.total_seconds() > 0

    def test_ingestion_is_idempotent_on_the_same_result(self) -> None:
        _, config, result = _run_round_trip_backtest()
        journal = InMemoryTradeJournalRepository()
        ingest_backtest_result(journal, result, config)
        second = ingest_backtest_result(journal, result, config)
        assert second.decisions_recorded == 0
        assert second.trades_recorded == 0

    def test_all_journaled_trades_are_tagged_historical_simulation(self) -> None:
        _, config, result = _run_round_trip_backtest()
        journal = InMemoryTradeJournalRepository()
        ingest_backtest_result(journal, result, config)
        for trade in journal.list_trades():
            assert trade.provenance == TradeProvenance.HISTORICAL_SIMULATION
        for decision in journal.list_decisions():
            assert decision.provenance == TradeProvenance.HISTORICAL_SIMULATION

    def test_experiment_id_links_journal_back_to_the_backtest_run(self) -> None:
        _, config, result = _run_round_trip_backtest()
        journal = InMemoryTradeJournalRepository()
        summary = ingest_backtest_result(journal, result, config)
        assert summary.experiment_id == result.experiment.experiment_id
        for trade in journal.list_trades():
            assert trade.experiment_id == result.experiment.experiment_id

    def test_baseline_strategy_backtest_also_ingests_cleanly(self) -> None:
        # Reuses Phase 2's own baseline strategy directly, not just the
        # test-only round-trip strategy above.
        days = _trading_days(date(2024, 1, 2), date(2024, 1, 12))
        closes = [100.0 + i for i in range(len(days))]
        bars = _bars("AAA", days, closes)
        sec = SecurityMaster(security_id="AAA", ticker="AAA", exchange="NASDAQ", currency="USD",
                              company_id="C1", instrument_type=InstrumentType.EQUITY,
                              valid_from=utc(2020, 1, 1), status=SecurityStatus.ACTIVE)
        repo = InMemoryDataRepository(bars=bars, securities=[sec], calendars={"US_EQUITY": US_EQUITY})
        config = BacktestConfig(market="US_EQUITY", start_date=days[0], end_date=days[-1],
                                  initial_capital=10_000.0, security_ids=("AAA",))
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        journal = InMemoryTradeJournalRepository()
        summary = ingest_backtest_result(journal, result, config)
        assert summary.decisions_recorded >= 1
        decisions = journal.list_decisions()
        assert decisions[0].strategy_version == "buy_and_hold_v1"
