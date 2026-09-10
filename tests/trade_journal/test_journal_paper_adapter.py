"""Category: Unit Test -- `trade_journal.paper_adapter.record_decision_and_trades`
(Session 37, ADR-0086), exercised directly (not through
`orchestration.paper_runner.run_cycle`) so the realized_pnl/
realized_return/holding_period math can be checked against exact
expected numbers, not just "is not None" (the integration coverage in
`tests/orchestration/test_paper_runner.py::TestTradeJournalWiring`
already covers the real end-to-end wiring; this file covers the
adapter's own arithmetic precisely)."""

from __future__ import annotations

from datetime import timedelta

from journal_helpers import make_fill, utc

from backtest.enums import OrderSide, OrderType
from backtest.portfolio import PortfolioView

from broker.enums import OrderValidationStatus
from broker.models import OrderValidationResult, ValidatedOrder
from broker.paper.models import PaperFillRecord

from decision.models import DecisionOutput

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.paper_adapter import PaperJournalState, record_decision_and_trades, reconstruct_journal_state
from trade_journal.repository import InMemoryTradeJournalRepository

_EMPTY_PORTFOLIO = PortfolioView(as_of_time=utc(2024, 1, 2), cash=1_000_000.0, positions={}, portfolio_value=1_000_000.0)


def _decision(action: DecisionAction, as_of_time, *, decision_id: str = "DEC-OUT-000001") -> DecisionOutput:
    return DecisionOutput(
        decision_id=decision_id, security_id="AAA", as_of_time=as_of_time, action=action,
        decision_reason="test_reason", confidence=0.9, time_horizon_days=5, target_weight_hint=0.1,
        regime=None, prediction_id="PRED-000001", prediction_version="v1", regime_version="v1",
        feature_version="v1", data_version=("dv1",), model_version=None,
        decision_version="test_decision_agent_v1", provenance=TradeProvenance.PAPER_TRADING,
    )


def _accepted_validation(*, quantity: float = 10.0, side: OrderSide = OrderSide.BUY, as_of_time) -> OrderValidationResult:
    order = ValidatedOrder(
        client_order_id=f"CID-{side.value}-{as_of_time.isoformat()}", security_id="AAA", side=side,
        quantity=quantity, order_type=OrderType.MARKET, as_of_time=as_of_time,
        decision_id="DEC-OUT-000001", sizing_id="SIZ-000001", risk_assessment_id="RISK-000001",
        configuration_version="cfg-v1", provenance=TradeProvenance.PAPER_TRADING,
    )
    return OrderValidationResult(status=OrderValidationStatus.ACCEPTED, validated_order=order, reason="ok", checks={})


_REJECTED_VALIDATION = OrderValidationResult(
    status=OrderValidationStatus.VALIDATION_REJECTED, validated_order=None, reason="test_reject", checks={},
)


def _fill_record(*, side: OrderSide, quantity: float, price: float, as_of_time, order_id: str) -> PaperFillRecord:
    fill = make_fill(
        order_id=order_id, security_id="AAA", side=side, quantity=quantity, price=price,
        reference_price=price, commission=1.0, spread_cost=0.1, slippage_cost=0.0,
        decision_time=as_of_time, execution_time=as_of_time,
    )
    return PaperFillRecord(fill_id=f"PAPERFILL-{order_id}", client_order_id=order_id, fill=fill, configuration_version="cfg-v1", recorded_at=as_of_time)


class TestDecisionAlwaysRecorded:
    def test_a_hold_with_no_fills_still_records_one_decision_and_zero_trades(self) -> None:
        journal = InMemoryTradeJournalRepository()
        state = PaperJournalState()
        as_of = utc(2024, 1, 2)

        snapshot, trades = record_decision_and_trades(
            journal, state, security_id="AAA", as_of_time=as_of,
            decision=_decision(DecisionAction.HOLD, as_of), validation=_REJECTED_VALIDATION, fills=(),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )

        assert snapshot.decision == DecisionAction.HOLD
        assert snapshot.order is None  # never a ValidatedOrder -- see module docstring
        assert trades == ()
        assert journal.list_trades() == []

    def test_calling_twice_for_the_same_security_and_checkpoint_dedupes_via_natural_key(self) -> None:
        journal = InMemoryTradeJournalRepository()
        state = PaperJournalState()
        as_of = utc(2024, 1, 2)
        kwargs = dict(
            journal=journal, state=state, security_id="AAA", as_of_time=as_of,
            decision=_decision(DecisionAction.HOLD, as_of), validation=_REJECTED_VALIDATION, fills=(),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )

        first, _ = record_decision_and_trades(**kwargs)
        second, _ = record_decision_and_trades(**kwargs)

        assert first.snapshot_id == second.snapshot_id
        assert len(journal.list_decisions()) == 1


class TestRealizedPnlArithmetic:
    def test_buy_then_closing_sell_computes_exact_realized_pnl_and_holding_period(self) -> None:
        journal = InMemoryTradeJournalRepository()
        state = PaperJournalState()
        buy_time = utc(2024, 1, 2)
        sell_time = utc(2024, 1, 12)

        buy_snapshot, buy_trades = record_decision_and_trades(
            journal, state, security_id="AAA", as_of_time=buy_time,
            decision=_decision(DecisionAction.BUY, buy_time), validation=_accepted_validation(as_of_time=buy_time),
            fills=(_fill_record(side=OrderSide.BUY, quantity=10.0, price=100.0, as_of_time=buy_time, order_id="CID-BUY"),),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )
        assert len(buy_trades) == 1
        assert buy_trades[0].realized_pnl is None  # an opening leg realizes nothing yet
        assert buy_trades[0].position_after == 10.0

        _, sell_trades = record_decision_and_trades(
            journal, state, security_id="AAA", as_of_time=sell_time,
            decision=_decision(DecisionAction.SELL, sell_time, decision_id="DEC-OUT-000002"),
            validation=_accepted_validation(quantity=10.0, side=OrderSide.SELL, as_of_time=sell_time),
            fills=(_fill_record(side=OrderSide.SELL, quantity=10.0, price=110.0, as_of_time=sell_time, order_id="CID-SELL"),),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )

        assert len(sell_trades) == 1
        sell_trade = sell_trades[0]
        # entry cost basis = 100.0 * 10 = 1000.0; exit proceeds before
        # cost = 110.0 * 10 = 1100.0; PortfolioAccounting.apply_fill's
        # realized formula is (price - average_cost) * quantity - total_cost
        # (total_cost = commission + spread_cost + slippage_cost = 1.1).
        expected_pnl = (110.0 - 100.0) * 10.0 - 1.1
        assert sell_trade.realized_pnl == expected_pnl
        assert sell_trade.realized_return == expected_pnl / 1000.0
        assert sell_trade.holding_period == sell_time - buy_time
        assert sell_trade.position_after == 0.0
        assert sell_trade.decision_id == journal.list_decisions(security_id="AAA")[-1].snapshot_id

    def test_partial_fills_across_two_calls_each_produce_their_own_trade_record(self) -> None:
        journal = InMemoryTradeJournalRepository()
        state = PaperJournalState()
        day1 = utc(2024, 1, 2)
        day2 = utc(2024, 1, 3)

        _, first_trades = record_decision_and_trades(
            journal, state, security_id="AAA", as_of_time=day1,
            decision=_decision(DecisionAction.BUY, day1), validation=_accepted_validation(quantity=25.0, as_of_time=day1),
            fills=(_fill_record(side=OrderSide.BUY, quantity=15.0, price=100.0, as_of_time=day1, order_id="CID-P1"),),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )
        _, second_trades = record_decision_and_trades(
            journal, state, security_id="AAA", as_of_time=day2,
            decision=_decision(DecisionAction.BUY, day2, decision_id="DEC-OUT-000002"),
            validation=_accepted_validation(quantity=25.0, as_of_time=day2),
            fills=(_fill_record(side=OrderSide.BUY, quantity=10.0, price=101.0, as_of_time=day2, order_id="CID-P2"),),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )

        assert first_trades[0].position_after == 15.0
        assert second_trades[0].position_after == 25.0
        assert len(journal.list_trades(security_id="AAA")) == 2


class TestReconstructJournalState:
    def test_reconstructed_state_produces_the_same_realized_pnl_as_a_live_run(self) -> None:
        """Simulates a process restart mid-position: records a real BUY
        with one `PaperJournalState`, reconstructs a FRESH one purely
        from the journal (as a resumed run would), then closes the
        position with the reconstructed state -- the resulting
        realized_pnl must match what an uninterrupted single-process run
        would have produced (TestRealizedPnlArithmetic's own BUY/SELL
        numbers), not a value corrupted by restarting mid-position."""
        journal = InMemoryTradeJournalRepository()
        live_state = PaperJournalState()
        buy_time = utc(2024, 1, 2)
        sell_time = utc(2024, 1, 12)

        record_decision_and_trades(
            journal, live_state, security_id="AAA", as_of_time=buy_time,
            decision=_decision(DecisionAction.BUY, buy_time), validation=_accepted_validation(as_of_time=buy_time),
            fills=(_fill_record(side=OrderSide.BUY, quantity=10.0, price=100.0, as_of_time=buy_time, order_id="CID-BUY"),),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )

        # "Process restart": a brand-new state, rebuilt only from what
        # the journal already persisted -- never carried over in memory.
        resumed_state = reconstruct_journal_state(journal)
        assert resumed_state.position_opened_at["AAA"] == buy_time

        _, sell_trades = record_decision_and_trades(
            journal, resumed_state, security_id="AAA", as_of_time=sell_time,
            decision=_decision(DecisionAction.SELL, sell_time, decision_id="DEC-OUT-000002"),
            validation=_accepted_validation(quantity=10.0, side=OrderSide.SELL, as_of_time=sell_time),
            fills=(_fill_record(side=OrderSide.SELL, quantity=10.0, price=110.0, as_of_time=sell_time, order_id="CID-SELL"),),
            portfolio_state=_EMPTY_PORTFOLIO, strategy_version="unknown",
            provenance=TradeProvenance.PAPER_TRADING, experiment_id="exp-1",
        )

        expected_pnl = (110.0 - 100.0) * 10.0 - 1.1
        assert sell_trades[0].realized_pnl == expected_pnl
        assert sell_trades[0].holding_period == sell_time - buy_time

    def test_empty_journal_reconstructs_an_empty_state(self) -> None:
        journal = InMemoryTradeJournalRepository()
        state = reconstruct_journal_state(journal)
        assert state.accounting.positions == {}
        assert state.position_opened_at == {}
