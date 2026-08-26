"""Category: Trade Journal Integration Test -- `build_trade_record`
always uses `TradeProvenance.LIVE_TRADING`;
`build_fill_from_broker_response` sets `reference_price = price`
(documented limitation, ADR-0022 decision 9) rather than fabricating a
measured slippage/spread value."""

from __future__ import annotations

import pytest

from live_helpers import utc

from broker.enums import BrokerOrderStatus
from broker.live.journal import build_fill_from_broker_response, build_trade_record
from broker.models import BrokerOrderResponse

from backtest.enums import OrderSide

from trade_journal.enums import TradeProvenance
from trade_journal.models import TradeRecord


def _response(status=BrokerOrderStatus.FILLED, filled_quantity=10.0, avg_fill_price=100.0) -> BrokerOrderResponse:
    return BrokerOrderResponse(
        response_id="BROKRESP-1", request_client_order_id="CID-1", broker_id="toss", operation="submit_order",
        status=status, broker_order_id="TOSSORD-1", filled_quantity=filled_quantity, avg_fill_price=avg_fill_price,
        error_code=None, error_message=None, attempt_count=1, latency_ms=50.0, responded_at=utc(2024, 1, 2),
        provenance=TradeProvenance.LIVE_TRADING,
    )


class TestBuildFillFromBrokerResponse:
    def test_reference_price_equals_execution_price(self) -> None:
        fill = build_fill_from_broker_response(_response(), security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2))
        assert fill.reference_price == fill.price == 100.0
        assert fill.slippage_cost == 0.0
        assert fill.spread_cost == 0.0

    def test_partial_filled_status_accepted(self) -> None:
        fill = build_fill_from_broker_response(
            _response(status=BrokerOrderStatus.PARTIAL_FILLED, filled_quantity=5.0), security_id="AAA",
            side=OrderSide.BUY, decision_time=utc(2024, 1, 2),
        )
        assert fill.quantity == 5.0

    def test_non_filled_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_fill_from_broker_response(
                _response(status=BrokerOrderStatus.REJECTED, filled_quantity=None, avg_fill_price=None),
                security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2),
            )

    def test_missing_fill_data_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_fill_from_broker_response(
                _response(filled_quantity=None), security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2),
            )

    def test_commission_defaults_to_zero_unless_supplied(self) -> None:
        fill = build_fill_from_broker_response(_response(), security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2))
        assert fill.commission == 0.0
        fill2 = build_fill_from_broker_response(_response(), security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2), commission=1.5)
        assert fill2.commission == 1.5


class TestBuildTradeRecord:
    def test_provenance_is_always_live_trading(self) -> None:
        fill = build_fill_from_broker_response(_response(), security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2))
        record = build_trade_record(fill, trade_id="LIVETRADE-1", decision_id="DEC-1", position_after=10.0)
        assert isinstance(record, TradeRecord)
        assert record.provenance == TradeProvenance.LIVE_TRADING

    def test_fields_carried_through(self) -> None:
        fill = build_fill_from_broker_response(_response(), security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 2))
        record = build_trade_record(fill, trade_id="LIVETRADE-1", decision_id="DEC-1", position_after=10.0)
        assert record.security_id == "AAA"
        assert record.quantity == 10.0
        assert record.execution_price == 100.0
        assert record.slippage == 0.0
