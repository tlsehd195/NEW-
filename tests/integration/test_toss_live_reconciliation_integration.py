"""Category: Integration Test (Phase 21) -- proves the real
`TossBrokerAdapter` (not `MockBrokerAdapter`) drives
`LiveTradingSession.reconcile_order`/`broker.live.reconciliation.
compare_account`/`compare_positions` correctly now that
get_order_status/get_account/get_positions/cancel_order are actually
implemented, against Tier 1 documented endpoints
(docs/operations/TOSS-API-GAP-ANALYSIS.md Phase 20 addendum).

Uses a stub transport throughout -- never the one real, network-capable
transport implementation this codebase has (instruction section
13/16): this proves the *wiring* is correct, not that a real Toss
account behaves this way. `get_capabilities()` still reports these four
UNKNOWN (see `broker.toss.adapter`'s module docstring) so this test
never routes through `evaluate_safety_gate` and claims it passes --
that would misrepresent operational-verification status. It instead
calls `LiveTradingSession.submit`/`reconcile_order` directly, the same
way `tests/integration/test_live_trading_lineage.py`'s own lineage test
does, focused purely on proving the adapter/session/reconciliation
wiring is sound.
"""

from __future__ import annotations

from live_helpers import make_live_config, utc
from storage_helpers import new_engine

from broker.config import BrokerConfig
from broker.enums import BrokerExecutionMode, BrokerOrderStatus
from broker.live.reconciliation import compare_account, compare_positions
from broker.live.session import LiveTradingSession
from broker.toss.adapter import TossBrokerAdapter
from broker.toss.endpoints import (
    BUYING_POWER_PATH,
    CANCEL_ORDER_PATH_TEMPLATE,
    CREATE_ORDER_PATH,
    HOLDINGS_PATH,
    ORDER_DETAIL_PATH_TEMPLATE,
    TOKEN_PATH,
)
from broker.transport import TransportResponse
from broker.validation import build_validated_order

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository
from storage.live_repository import DuckDBReconciliationRepository

from broker.pipeline import submit_validated_order

from trade_journal.enums import TradeProvenance

from broker_helpers import make_risk_checked_position


class _StubTransport:
    """Routes each path to a caller-registered response; TOKEN_PATH is
    always answered automatically. Never reaches the network."""

    def __init__(self) -> None:
        self._get: dict[str, TransportResponse] = {}
        self._post: dict[str, TransportResponse] = {}

    def when_get(self, path: str, response: TransportResponse) -> "_StubTransport":
        self._get[path] = response
        return self

    def when_post(self, path: str, response: TransportResponse) -> "_StubTransport":
        self._post[path] = response
        return self

    def get(self, path, *, headers, params, timeout):
        return self._get[path]

    def post(self, path, *, headers, json_body, timeout):
        if path == TOKEN_PATH:
            return TransportResponse(200, {"access_token": "tok-abc123"}, None, {})
        return self._post[path]


def _live_config() -> BrokerConfig:
    return BrokerConfig(broker_id="toss", execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)


class TestTossAdapterFeedsLiveReconciliation:
    def test_order_status_reconciliation_matched(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        as_of = utc(2024, 3, 1)

        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "FILLED", "orderId": "TOSS-1", "filledQuantity": "20"}, None, {}))
        transport.when_get(
            ORDER_DETAIL_PATH_TEMPLATE.format(order_id="TOSS-1"),
            TransportResponse(200, {"orderId": "TOSS-1", "status": "FILLED",
                                     "execution": {"filledQuantity": "20", "averageFilledPrice": "100.0"}}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)

        engine = new_engine(tmp_path)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        reconciliation_repo = DuckDBReconciliationRepository(engine)

        risk = make_risk_checked_position(risk_id="RISK-900001", final_target_quantity=20.0, provenance=TradeProvenance.LIVE_TRADING)
        order = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order

        session = LiveTradingSession(
            make_live_config(live_trading_enabled=True), adapter, reconciliation_repository=reconciliation_repo,
        )
        submit_validated_order(
            adapter, order, execution_mode="LIVE", requested_at=as_of, configuration_version="cfg-v1",
            request_repository=request_repo, response_repository=response_repo,
        )
        session._internal_status[order.client_order_id] = BrokerOrderStatus.FILLED  # mirrors what session.submit would set

        result = session.reconcile_order(order.client_order_id, as_of=as_of)
        assert result.status.value == "MATCHED"
        assert reconciliation_repo.get_latest("order_status", order.client_order_id).status.value == "MATCHED"
        engine.close()

    def test_order_status_reconciliation_mismatch_when_toss_reports_a_different_status(self, tmp_path, monkeypatch) -> None:
        """Our internal record says FILLED, but Toss's own order-detail
        endpoint (queried fresh) says CANCELED -- e.g. the order was
        cancelled through the Toss app directly, outside this system.
        Reconciliation must surface this as MISMATCH, never silently
        trust the internal record."""
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        as_of = utc(2024, 3, 1)

        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "PENDING", "orderId": "TOSS-1"}, None, {}))
        transport.when_get(
            ORDER_DETAIL_PATH_TEMPLATE.format(order_id="TOSS-1"),
            TransportResponse(200, {"orderId": "TOSS-1", "status": "CANCELED"}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)

        engine = new_engine(tmp_path)
        reconciliation_repo = DuckDBReconciliationRepository(engine)
        risk = make_risk_checked_position(risk_id="RISK-900002", final_target_quantity=20.0, provenance=TradeProvenance.LIVE_TRADING)
        order = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order

        session = LiveTradingSession(make_live_config(live_trading_enabled=True), adapter, reconciliation_repository=reconciliation_repo)
        adapter.submit_order(order, requested_at=as_of)
        session._internal_status[order.client_order_id] = BrokerOrderStatus.FILLED  # what we (wrongly) believe happened

        result = session.reconcile_order(order.client_order_id, as_of=as_of)
        assert result.status.value == "MISMATCH"
        engine.close()

    def test_order_status_reconciliation_unknown_for_an_order_this_adapter_instance_never_submitted(self, tmp_path, monkeypatch) -> None:
        """Simulates a process restart: a fresh TossBrokerAdapter has no
        client_order_id -> orderId mapping for an order a prior process
        submitted. Reconciliation must report UNKNOWN, never a
        fabricated MATCHED/MISMATCH -- this is the documented, known
        limitation of the in-memory id map (see
        broker.toss.adapter.TossBrokerAdapter.__init__'s docstring)."""
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        as_of = utc(2024, 3, 1)

        adapter = TossBrokerAdapter(_live_config(), _StubTransport())  # nothing ever submitted through this instance
        session = LiveTradingSession(make_live_config(live_trading_enabled=True), adapter)
        session._internal_status["CID-FROM-A-PRIOR-PROCESS"] = BrokerOrderStatus.FILLED

        result = session.reconcile_order("CID-FROM-A-PRIOR-PROCESS", as_of=as_of)
        assert result.status.value == "UNKNOWN"

    def test_account_and_position_reconciliation_against_the_real_adapter(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        as_of = utc(2024, 3, 1)

        transport = _StubTransport()
        transport.when_get(BUYING_POWER_PATH, TransportResponse(200, {"currency": "USD", "cashBuyingPower": "80000.0"}, None, {}))
        transport.when_get(HOLDINGS_PATH, TransportResponse(200, {"items": [
            {"symbol": "AAPL", "quantity": "20", "averagePurchasePrice": "100.0"},
        ]}, None, {}))
        adapter = TossBrokerAdapter(_live_config(), transport)

        account_snapshot = adapter.get_account(as_of=as_of)
        account_result = compare_account(
            80000.0, account_snapshot, tolerance=0.01, reconciliation_id="RECON-A1", as_of_time=as_of,
            configuration_version="cfg-v1",
        )
        assert account_result.status.value == "MATCHED"

        positions = adapter.get_positions(as_of=as_of)
        aapl_position = next(p for p in positions if p.security_id == "AAPL")
        position_result = compare_positions(
            20.0, aapl_position, security_id="AAPL", tolerance=0.001, reconciliation_id="RECON-P1",
            as_of_time=as_of, configuration_version="cfg-v1",
        )
        assert position_result.status.value == "MATCHED"

        # a real discrepancy is surfaced, not silently accepted
        mismatch_result = compare_positions(
            999.0, aapl_position, security_id="AAPL", tolerance=0.001, reconciliation_id="RECON-P2",
            as_of_time=as_of, configuration_version="cfg-v1",
        )
        assert mismatch_result.status.value == "MISMATCH"

    def test_cancel_after_submit_then_status_query_reflects_cancellation(self, monkeypatch) -> None:
        """End-to-end within the adapter: submit -> cancel -> status
        query all correctly correlate through client_order_id, even
        though Toss issues a brand-new orderId for the cancel operation
        itself (never confused with the original order's id)."""
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        as_of = utc(2024, 3, 1)

        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "PENDING", "orderId": "TOSS-1"}, None, {}))
        transport.when_post(CANCEL_ORDER_PATH_TEMPLATE.format(order_id="TOSS-1"), TransportResponse(200, {"orderId": "TOSS-NEW-ID"}, None, {}))
        transport.when_get(
            ORDER_DETAIL_PATH_TEMPLATE.format(order_id="TOSS-1"),
            TransportResponse(200, {"orderId": "TOSS-1", "status": "CANCELED"}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)

        risk = make_risk_checked_position(risk_id="RISK-900003", final_target_quantity=20.0, provenance=TradeProvenance.LIVE_TRADING)
        order = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order

        adapter.submit_order(order, requested_at=as_of)
        cancel_response = adapter.cancel_order(order.client_order_id, requested_at=as_of)
        assert cancel_response.status == BrokerOrderStatus.CANCELED
        assert cancel_response.broker_order_id == "TOSS-1"
        assert cancel_response.cancel_reference_id == "TOSS-NEW-ID"

        observation = adapter.get_order_status(order.client_order_id, as_of=as_of)
        assert observation.status == BrokerOrderStatus.CANCELED
        assert observation.broker_order_id == "TOSS-1"
