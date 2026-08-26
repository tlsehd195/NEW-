"""Category: Regression Test (Phase 18, instruction sections 8-9) --
re-verifies, through the Live journal-building path specifically (not
just Paper's), the two bugs Phase 17 found and fixed:

1. Trade Journal `record_trade`'s natural-key collision on
   `fill.order_id` alone, which silently dropped every partial fill
   after the first for one order -- `broker.live.journal.
   build_fill_from_broker_response` produces exactly this shape
   (`Fill.order_id = response.request_client_order_id`, shared across
   every response for the same order, `Fill.execution_time =
   response.responded_at`, which differs per response).
2. Toss 5xx responses mis-mapped to a definitive `REJECTED` instead of
   the honest `UNKNOWN` -- re-verified end to end through
   `LiveTradingSession.submit`, not just `parse_order_response` in
   isolation (`tests/broker/toss/test_toss_production_safety_contract.py`
   already covers the isolated case).
"""

from __future__ import annotations

from datetime import datetime, timezone

from broker_helpers import make_risk_checked_position
from live_helpers import make_approval, make_broker_capabilities, make_live_config

from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerExecutionMode, BrokerOrderStatus, OrderValidationStatus
from broker.live.enums import OperationalState
from broker.live.journal import build_fill_from_broker_response, build_trade_record
from broker.live.safety_gate import SafetyGateContext
from broker.live.session import LiveTradingSession
from broker.models import BrokerOrderResponse
from broker.toss.adapter import TossBrokerAdapter
from broker.toss.endpoints import CREATE_ORDER_PATH, TOKEN_PATH
from broker.transport import TransportResponse
from broker.validation import build_validated_order

from monitoring.enums import ComponentHealthStatus

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.repository import InMemoryTradeJournalRepository


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestLivePartialFillJournalRegression:
    def test_two_broker_responses_for_the_same_order_both_reach_the_journal(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 1), security_id="AAA", decision=DecisionAction.BUY)

        first_response = BrokerOrderResponse(
            response_id="BROKRESP-1", request_client_order_id="CID-LIVE-1", broker_id="toss",
            operation="submit_order", status=BrokerOrderStatus.PARTIAL_FILLED, broker_order_id="TOSS-1",
            filled_quantity=40.0, avg_fill_price=100.0, error_code=None, error_message=None, attempt_count=1,
            latency_ms=50.0, responded_at=utc(2024, 1, 1), provenance=TradeProvenance.LIVE_TRADING,
        )
        second_response = BrokerOrderResponse(
            response_id="BROKRESP-2", request_client_order_id="CID-LIVE-1", broker_id="toss",
            operation="submit_order", status=BrokerOrderStatus.FILLED, broker_order_id="TOSS-1",
            filled_quantity=60.0, avg_fill_price=101.0, error_code=None, error_message=None, attempt_count=1,
            latency_ms=50.0, responded_at=utc(2024, 1, 2), provenance=TradeProvenance.LIVE_TRADING,
        )

        from backtest.enums import OrderSide

        fill1 = build_fill_from_broker_response(first_response, security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 1))
        fill2 = build_fill_from_broker_response(second_response, security_id="AAA", side=OrderSide.BUY, decision_time=utc(2024, 1, 1))
        assert fill1.order_id == fill2.order_id  # same logical order
        assert fill1.execution_time != fill2.execution_time  # two distinct fill events

        trade1 = journal.record_trade(decision_id=decision.snapshot_id, fill=fill1, position_after=40.0, provenance=TradeProvenance.LIVE_TRADING)
        trade2 = journal.record_trade(decision_id=decision.snapshot_id, fill=fill2, position_after=100.0, provenance=TradeProvenance.LIVE_TRADING)

        assert trade1.trade_id != trade2.trade_id
        assert len(journal.list_trades(provenance=TradeProvenance.LIVE_TRADING)) == 2


class TestLiveToss5xxRegressionEndToEnd:
    class _FiveHundredThenTokenTransport:
        def __init__(self) -> None:
            self.order_call_count = 0

        def post(self, path, *, headers, json_body, timeout):
            if path == TOKEN_PATH:
                return TransportResponse(200, {"access_token": "tok-abc"}, None, {})
            assert path == CREATE_ORDER_PATH
            self.order_call_count += 1
            return TransportResponse(500, {"code": "internal-error", "message": "unexpected failure"}, None, {})

        def get(self, path, *, headers, params, timeout):
            raise NotImplementedError

    def _live_config(self, **overrides):
        fields = dict(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)
        fields.update(overrides)
        return BrokerConfig(**fields)

    def _order(self, risk_id: str):
        risk = make_risk_checked_position(risk_id=risk_id, final_target_quantity=10.0, provenance=TradeProvenance.LIVE_TRADING)
        return build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order

    def _gate_context(self, session):
        return SafetyGateContext(
            as_of_time=utc(2024, 1, 2), config=session.config, approval=make_approval(),
            required_capabilities=(BrokerCapability.MARKET_ORDER,), broker_capabilities=make_broker_capabilities(),
            risk_health=ComponentHealthStatus.HEALTHY, order_validation_status=OrderValidationStatus.ACCEPTED,
            kill_switch_engaged=session.is_kill_switch_engaged(), account_state_known=True,
            position_state_known=True, model_state_valid=True, configuration_integrity_valid=True,
        )

    def test_5xx_produces_unknown_and_reconciliation_required_with_no_blind_retry(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")

        transport = self._FiveHundredThenTokenTransport()
        adapter = TossBrokerAdapter(self._live_config(), transport)
        session = LiveTradingSession(make_live_config(live_trading_enabled=True), adapter)

        outcome1 = session.submit(self._order("RISK-5XX-1"), requested_at=utc(2024, 1, 2), gate_context=self._gate_context(session))
        assert outcome1.submitted is False
        assert outcome1.status == "UNKNOWN"
        assert outcome1.error is not None and "BrokerProviderError" in outcome1.error
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED
        assert transport.order_call_count == 1  # exactly one attempt -- no automatic retry

        # A second submission is blocked outright, not retried against the broker again.
        outcome2 = session.submit(self._order("RISK-5XX-2"), requested_at=utc(2024, 1, 3), gate_context=self._gate_context(session))
        assert outcome2.submitted is False
        assert outcome2.status == "BLOCKED"
        assert outcome2.error == "reconciliation_required"
        assert transport.order_call_count == 1  # still exactly one -- the second call never reached the broker
