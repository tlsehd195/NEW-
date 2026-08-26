"""Category: Trade Journal Integration Test -- instruction section 23:
`build_trade_record` bridges a Paper Trading fill into
`trade_journal.models.TradeRecord` unchanged, always with
`TradeProvenance.PAPER_TRADING`."""

from __future__ import annotations

from paper_helpers import utc

from broker.paper.journal import build_trade_record
from broker.paper.models import PaperFillRecord

from backtest.enums import OrderSide
from backtest.fills import Fill

from trade_journal.enums import TradeProvenance
from trade_journal.models import TradeRecord


def _fill_record(**overrides) -> PaperFillRecord:
    defaults = dict(
        order_id="CID-1", security_id="AAA", side=OrderSide.BUY, quantity=10.0, reference_price=100.0,
        price=100.1, commission=1.05, spread_cost=0.1, slippage_cost=0.05,
        decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2), data_version="dv1",
    )
    defaults.update(overrides)
    fill = Fill(**defaults)
    return PaperFillRecord(
        fill_id="PAPERFILL-000001", client_order_id="CID-1", fill=fill,
        configuration_version="cfg-1", recorded_at=utc(2024, 1, 2),
    )


class TestBuildTradeRecord:
    def test_provenance_is_always_paper_trading(self) -> None:
        record = build_trade_record(_fill_record(), trade_id="PAPERTRADE-000001", decision_id="DEC-1", position_after=10.0)
        assert isinstance(record, TradeRecord)
        assert record.provenance == TradeProvenance.PAPER_TRADING

    def test_fields_carried_through_from_fill(self) -> None:
        record = build_trade_record(_fill_record(), trade_id="PAPERTRADE-000001", decision_id="DEC-1", position_after=10.0)
        assert record.order_id == "CID-1"
        assert record.security_id == "AAA"
        assert record.side == OrderSide.BUY
        assert record.quantity == 10.0
        assert record.execution_price == 100.1
        assert record.reference_price == 100.0
        assert record.slippage == 0.05
        assert record.transaction_cost == 1.05 + 0.1  # commission + spread_cost, slippage tracked separately
        assert record.fill.commission == 1.05  # sanity: the nested Fill itself is unchanged

    def test_realized_pnl_passed_through_only_when_supplied(self) -> None:
        record_no_pnl = build_trade_record(_fill_record(), trade_id="T1", decision_id="DEC-1", position_after=10.0)
        assert record_no_pnl.realized_pnl is None

        record_with_pnl = build_trade_record(
            _fill_record(side=OrderSide.SELL), trade_id="T2", decision_id="DEC-1", position_after=0.0,
            realized_pnl=12.5, realized_return=0.05,
        )
        assert record_with_pnl.realized_pnl == 12.5
        assert record_with_pnl.realized_return == 0.05
