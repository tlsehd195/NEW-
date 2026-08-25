"""Unit tests for counterfactual.counterfactual.build_counterfactual_record
and compute_counterfactual_advantage.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 3.
"""

from __future__ import annotations

from datetime import date

import pytest
from counterfactual_helpers import make_bars_repo, utc
from journal_helpers import make_fill

from backtest.enums import OrderSide

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import AlternativeOutcome, TradeRecord

from counterfactual.counterfactual import build_counterfactual_record, compute_counterfactual_advantage


def _trade(realized_return: float | None = 0.12) -> TradeRecord:
    return TradeRecord(
        trade_id="TRD-000001", decision_id="DEC-000001", order_id="ORD-000001", security_id="AAA",
        timestamp=utc(2024, 1, 9), side=OrderSide.BUY,
        quantity=10.0, execution_price=110.0, reference_price=109.9, slippage=0.1, transaction_cost=1.0,
        position_after=10.0, fill=make_fill(), realized_pnl=100.0, realized_return=realized_return,
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


class TestBuildCounterfactualRecord:
    def test_assembles_hold_and_cash_alternatives(self) -> None:
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0})
        trade = _trade()
        record = build_counterfactual_record(
            repo, trade, DecisionAction.BUY, decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
        )
        assert record.trade_id == "TRD-000001"
        assert record.selected_action == DecisionAction.BUY
        assert len(record.alternatives) == 2
        actions = {a.action for a in record.alternatives}
        assert actions == {"HOLD", "CASH"}
        hold = next(a for a in record.alternatives if a.action == "HOLD")
        cash = next(a for a in record.alternatives if a.action == "CASH")
        assert hold.hypothetical_return == pytest.approx(0.10)
        assert cash.hypothetical_return == 0.0

    def test_computed_at_is_carried_through_unchanged(self) -> None:
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0})
        record = build_counterfactual_record(
            repo, _trade(), DecisionAction.BUY, decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
            computed_at=utc(2024, 1, 10),
        )
        assert record.computed_at == utc(2024, 1, 10)

    def test_computed_at_defaults_to_none_not_now(self) -> None:
        """No hidden datetime.now() -- see spec section 7."""
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0})
        record = build_counterfactual_record(
            repo, _trade(), DecisionAction.BUY, decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
        )
        assert record.computed_at is None


class TestCounterfactualAdvantage:
    def test_positive_when_selected_action_beat_the_alternative(self) -> None:
        trade = _trade(realized_return=0.12)
        alt = AlternativeOutcome(action="HOLD", hypothetical_return=0.10)
        assert compute_counterfactual_advantage(trade, alt) == pytest.approx(0.02)

    def test_negative_when_selected_action_underperformed(self) -> None:
        trade = _trade(realized_return=0.05)
        alt = AlternativeOutcome(action="HOLD", hypothetical_return=0.10)
        assert compute_counterfactual_advantage(trade, alt) == pytest.approx(-0.05)

    def test_none_when_trade_has_no_realized_return_yet(self) -> None:
        trade = _trade(realized_return=None)
        alt = AlternativeOutcome(action="HOLD", hypothetical_return=0.10)
        assert compute_counterfactual_advantage(trade, alt) is None

    def test_none_when_alternative_has_no_computed_return(self) -> None:
        trade = _trade(realized_return=0.12)
        alt = AlternativeOutcome(action="HOLD", hypothetical_return=None, basis="insufficient_data")
        assert compute_counterfactual_advantage(trade, alt) is None
