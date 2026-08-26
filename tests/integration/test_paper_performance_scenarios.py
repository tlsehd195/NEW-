"""Category: Integration Test (Phase 18) -- Paper Trading scenarios A-H,
run through the real pipeline: PaperBrokerAdapter/PaperTradingSession
(Phase 15) -> Trade Journal (Phase 3) -> PortfolioAccounting equity
curve (Phase 2, reused via `PaperBrokerAdapter.accounting`, Phase 18) ->
`compute_paper_performance_report` (Phase 18). Each scenario asserts
the lineage survives end to end, not just that each layer works in
isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from broker_helpers import make_risk_checked_position
from paper_helpers import make_bar, make_paper_config

from broker.enums import BrokerOrderStatus, OrderValidationStatus
from broker.errors import BrokerTimeoutError
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from broker.paper.performance import compute_paper_performance_report

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.repository import InMemoryTradeJournalRepository


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _validated_order(*, quantity: float, risk_id: str, status=None, current_quantity: float = 0.0):
    from risk.enums import RiskCheckStatus

    risk = make_risk_checked_position(
        risk_id=risk_id, final_target_quantity=quantity, status=status or RiskCheckStatus.PASS,
        provenance=TradeProvenance.PAPER_TRADING,
    )
    return build_validated_order(risk, current_quantity=current_quantity, configuration_version="cfg-v1")


class TestScenarioA_BuyFilledSellClosed:
    def test_full_round_trip_reaches_a_labeled_performance_report(self) -> None:
        buy_day, sell_day = utc(2024, 1, 1), utc(2024, 1, 10)
        journal = InMemoryTradeJournalRepository()

        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([
            make_bar(available_time=buy_day, volume=1_000_000.0, close=100.0),
            make_bar(available_time=sell_day, volume=1_000_000.0, close=110.0),
        ])
        session = PaperTradingSession(config, mds)

        buy_validation = _validated_order(quantity=100.0, risk_id="RISK-A1")
        buy_order = buy_validation.validated_order
        buy_decision = journal.record_decision(decision_time=buy_day, security_id=buy_order.security_id, decision=DecisionAction.BUY)
        _, buy_fills = session.submit(buy_order, requested_at=buy_day)
        assert buy_fills[0].fill.side.value == "BUY"
        buy_trade = journal.record_trade(
            decision_id=buy_decision.snapshot_id, fill=buy_fills[0].fill, position_after=100.0,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        session.adapter.accounting.mark_to_market({buy_order.security_id: 100.0}, buy_day)

        sell_validation = _validated_order(quantity=0.0, risk_id="RISK-A2", current_quantity=100.0)
        sell_order = sell_validation.validated_order
        sell_decision = journal.record_decision(decision_time=sell_day, security_id=sell_order.security_id, decision=DecisionAction.SELL)
        _, sell_fills = session.submit(sell_order, requested_at=sell_day)
        assert sell_fills[0].fill.side.value == "SELL"
        sell_trade = journal.record_trade(
            decision_id=sell_decision.snapshot_id, fill=sell_fills[0].fill, position_after=0.0,
            realized_pnl=900.0, realized_return=0.09, holding_period=sell_day - buy_day,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        session.adapter.accounting.mark_to_market({sell_order.security_id: 110.0}, sell_day)

        assert len(journal.list_trades(provenance=TradeProvenance.PAPER_TRADING)) == 2

        equity_history = [(p.as_of_time, p.portfolio_value) for p in session.adapter.accounting.value_series]
        report = compute_paper_performance_report(
            report_id="RPT-A1", paper_session_id="SESSION-A", equity_history=equity_history,
            trades=journal.list_trades(provenance=TradeProvenance.PAPER_TRADING), evaluated_at=sell_day,
            turnover=session.adapter.accounting.turnover(),
        )
        assert report.num_trades == 2
        assert report.realized_pnl == 900.0
        assert report.total_return is not None and report.total_return > 0


class TestScenarioB_PartialThenFullFillThenSell:
    def test_partial_fills_each_reach_the_journal_and_the_report(self) -> None:
        day1, day2, sell_day = utc(2024, 1, 1), utc(2024, 1, 2), utc(2024, 1, 10)
        journal = InMemoryTradeJournalRepository()

        config = make_paper_config(initial_cash=10_000_000.0, max_participation=0.10)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day1, volume=1_000.0, close=100.0)])
        session = PaperTradingSession(config, mds)

        validation = _validated_order(quantity=150.0, risk_id="RISK-B1")
        order = validation.validated_order
        decision = journal.record_decision(decision_time=day1, security_id=order.security_id, decision=DecisionAction.BUY)

        _, fills1 = session.submit(order, requested_at=day1)
        assert fills1[0].fill.quantity == 100.0  # 10% of 1000 volume
        journal.record_trade(decision_id=decision.snapshot_id, fill=fills1[0].fill, position_after=100.0, provenance=TradeProvenance.PAPER_TRADING)

        mds.register(make_bar(available_time=day2, volume=1_000.0, close=101.0))
        _, fills2 = session.advance(day2)
        assert fills2[0].fill.quantity == 50.0
        journal.record_trade(decision_id=decision.snapshot_id, fill=fills2[0].fill, position_after=150.0, provenance=TradeProvenance.PAPER_TRADING)

        assert len(journal.list_trades()) == 2  # Phase 17's natural-key fix: both partial fills preserved

        sell_validation = _validated_order(quantity=0.0, risk_id="RISK-B2", current_quantity=150.0)
        sell_order = sell_validation.validated_order
        sell_decision = journal.record_decision(decision_time=sell_day, security_id=sell_order.security_id, decision=DecisionAction.SELL)
        mds.register(make_bar(available_time=sell_day, volume=1_000_000.0, close=105.0))
        _, sell_fills = session.submit(sell_order, requested_at=sell_day)
        journal.record_trade(
            decision_id=sell_decision.snapshot_id, fill=sell_fills[0].fill, position_after=0.0,
            realized_pnl=500.0, realized_return=0.033, provenance=TradeProvenance.PAPER_TRADING,
        )

        assert len(journal.list_trades()) == 3
        report = compute_paper_performance_report(
            report_id="RPT-B1", paper_session_id="SESSION-B", equity_history=[],
            trades=journal.list_trades(provenance=TradeProvenance.PAPER_TRADING), evaluated_at=sell_day,
        )
        assert report.num_trades == 3
        assert report.realized_pnl == 500.0  # only the closing leg realizes PnL


class TestScenarioC_InsufficientCashRejected:
    def test_rejected_order_never_reaches_the_journal(self) -> None:
        day = utc(2024, 1, 1)
        journal = InMemoryTradeJournalRepository()
        config = make_paper_config(initial_cash=100.0, max_participation=1.0)  # far too little cash
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day, volume=1_000_000.0, close=100.0)])
        session = PaperTradingSession(config, mds)

        validation = _validated_order(quantity=1000.0, risk_id="RISK-C1")
        order = validation.validated_order
        response, fills = session.submit(order, requested_at=day)

        assert response.status == BrokerOrderStatus.REJECTED
        assert response.error_code == "insufficient_cash"
        assert fills == ()
        assert journal.list_trades() == []  # no false trade for a rejected order


class TestScenarioD_InsufficientPositionRejected:
    def test_selling_more_than_held_is_rejected_before_any_fill_attempt(self) -> None:
        day = utc(2024, 1, 1)
        journal = InMemoryTradeJournalRepository()
        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0, allow_short=False)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day, volume=1_000_000.0, close=100.0)])
        session = PaperTradingSession(config, mds)

        # current_quantity=0.0 but requesting to sell down to a negative target -- build_validated_order
        # computes a SELL of magnitude 50 from a flat position, which PaperBrokerAdapter must reject
        # (no shares held, allow_short=False).
        from risk.enums import RiskCheckStatus

        risk = make_risk_checked_position(risk_id="RISK-D1", final_target_quantity=-50.0, status=RiskCheckStatus.PASS, provenance=TradeProvenance.PAPER_TRADING)
        validation = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1")
        order = validation.validated_order
        assert order.side.value == "SELL"

        response, fills = session.submit(order, requested_at=day)
        assert response.status == BrokerOrderStatus.REJECTED
        assert response.error_code == "insufficient_position"
        assert journal.list_trades() == []


class TestScenarioE_DuplicateClientOrderIdNeverDuplicates:
    def test_resubmitting_the_same_order_produces_no_second_fill_or_journal_entry(self) -> None:
        day = utc(2024, 1, 1)
        journal = InMemoryTradeJournalRepository()
        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day, volume=1_000_000.0, close=100.0)])
        session = PaperTradingSession(config, mds)

        validation = _validated_order(quantity=10.0, risk_id="RISK-E1")
        order = validation.validated_order
        decision = journal.record_decision(decision_time=day, security_id=order.security_id, decision=DecisionAction.BUY)

        response1, fills1 = session.submit(order, requested_at=day)
        journal.record_trade(decision_id=decision.snapshot_id, fill=fills1[0].fill, position_after=10.0, provenance=TradeProvenance.PAPER_TRADING)

        response2, fills2 = session.submit(order, requested_at=day)  # identical client_order_id
        assert response2.broker_order_id == response1.broker_order_id
        assert fills2 == ()  # idempotent replay -- no new fill surfaced to capture
        assert len(journal.list_trades()) == 1


class TestScenarioF_BrokerFailureLeavesNoFalseTrade:
    def test_timeout_raises_and_leaves_the_journal_empty(self) -> None:
        day = utc(2024, 1, 1)
        journal = InMemoryTradeJournalRepository()
        config = make_paper_config(initial_cash=1_000_000.0, failure_mode="timeout")
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day, volume=1_000_000.0)])
        session = PaperTradingSession(config, mds)

        validation = _validated_order(quantity=10.0, risk_id="RISK-F1")
        order = validation.validated_order

        import pytest

        with pytest.raises(BrokerTimeoutError):
            submit_validated_order(session.adapter, order, execution_mode="PAPER", requested_at=day, configuration_version="cfg-v1")
        assert journal.list_trades() == []


class TestScenarioG_TransactionCostAndSlippageFlowIntoTheReport:
    def test_nonzero_cost_and_slippage_are_reflected_in_the_performance_report(self) -> None:
        day = utc(2024, 1, 1)
        journal = InMemoryTradeJournalRepository()
        config = make_paper_config(
            initial_cash=1_000_000.0, max_participation=1.0,
            commission_fixed_per_trade=2.0, commission_per_share=0.01, spread_bps=5.0, slippage_bps=10.0,
        )
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day, volume=1_000_000.0, close=100.0)])
        session = PaperTradingSession(config, mds)

        validation = _validated_order(quantity=100.0, risk_id="RISK-G1")
        order = validation.validated_order
        decision = journal.record_decision(decision_time=day, security_id=order.security_id, decision=DecisionAction.BUY)
        _, fills = session.submit(order, requested_at=day)
        assert fills[0].fill.slippage_cost > 0
        assert fills[0].fill.commission > 0
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=fills[0].fill, position_after=100.0, provenance=TradeProvenance.PAPER_TRADING)

        report = compute_paper_performance_report(
            report_id="RPT-G1", paper_session_id="SESSION-G", equity_history=[],
            trades=[trade], evaluated_at=day,
        )
        assert report.total_transaction_cost is not None and report.total_transaction_cost > 0
        assert report.total_slippage is not None and report.total_slippage > 0


class TestScenarioH_DrawdownIsReflectedInTheReport:
    def test_a_real_price_decline_produces_a_nonzero_max_drawdown(self) -> None:
        day1, day2, day3 = utc(2024, 1, 1), utc(2024, 1, 5), utc(2024, 1, 10)
        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=day1, volume=1_000_000.0, close=100.0)])
        session = PaperTradingSession(config, mds)

        validation = _validated_order(quantity=1000.0, risk_id="RISK-H1")
        order = validation.validated_order
        session.submit(order, requested_at=day1)

        session.adapter.accounting.mark_to_market({order.security_id: 100.0}, day1)
        session.adapter.accounting.mark_to_market({order.security_id: 130.0}, day2)  # peak
        session.adapter.accounting.mark_to_market({order.security_id: 90.0}, day3)   # drawdown from peak

        equity_history = [(p.as_of_time, p.portfolio_value) for p in session.adapter.accounting.value_series]
        report = compute_paper_performance_report(
            report_id="RPT-H1", paper_session_id="SESSION-H", equity_history=equity_history,
            trades=[], evaluated_at=day3,
        )
        assert report.max_drawdown is not None
        assert report.max_drawdown < 0
        assert report.calmar_ratio is not None or report.reasons.get("calmar_ratio") is not None
