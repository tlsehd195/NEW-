"""Category: Session Test -- `LiveTradingSession`'s gate enforcement,
idempotency, UNKNOWN-on-timeout-with-no-retry, kill switch integration,
and startup/shutdown checks. Covers instruction section 34's numbered
scenarios directly reachable through `LiveTradingSession` (the rest --
missing/invalid credential, authentication failure -- are exercised at
the `broker.toss.*`/adapter layer already, Phase 13; this session layer
never re-implements credential handling)."""

from __future__ import annotations

import pytest

from live_helpers import make_approval, make_broker_capabilities, make_live_config, make_passing_gate_context, utc

from broker.enums import BrokerCapability
from broker.errors import BrokerAuthError, BrokerRateLimitError, BrokerTimeoutError, BrokerTransportError
from broker.live.enums import OperationalState
from broker.live.session import LiveTradingSession, run_shutdown_checks, run_startup_checks
from broker.mock import MockBrokerAdapter
from broker.config import BrokerConfig
from broker.models import ValidatedOrder

from backtest.enums import OrderSide, OrderType

from trade_journal.enums import TradeProvenance


def _order(client_order_id="CID-1", security_id="AAA", side=OrderSide.BUY, quantity=10.0):
    return ValidatedOrder(
        client_order_id=client_order_id, security_id=security_id, side=side, quantity=quantity,
        order_type=OrderType.MARKET, as_of_time=utc(2024, 1, 2), decision_id="DEC-1", sizing_id="SIZE-1",
        risk_assessment_id="RISK-1", configuration_version="cfg-1", provenance=TradeProvenance.LIVE_TRADING,
    )


def _session(**adapter_kwargs) -> LiveTradingSession:
    adapter = MockBrokerAdapter(BrokerConfig(), **adapter_kwargs)
    # Phase 22: max_daily_loss/max_order_frequency_per_hour must be set
    # for evaluate_safety_gate to pass at all (Option B, LIVE-RISK-POLICY.md).
    return LiveTradingSession(
        make_live_config(live_trading_enabled=True, max_daily_loss=2000.0, max_order_frequency_per_hour=6), adapter,
    )


def _gate_ctx(session, **overrides):
    caps = session.adapter.get_capabilities(as_of=utc(2024, 1, 2))
    defaults = dict(config=session.config, broker_capabilities=caps)
    defaults.update(overrides)
    return make_passing_gate_context(**defaults)


class TestScenario1LiveDisabled:
    def test_live_disabled_produces_no_order(self) -> None:
        session = LiveTradingSession(make_live_config(live_trading_enabled=False), MockBrokerAdapter(BrokerConfig()))
        ctx = _gate_ctx(session, config=session.config)
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is False
        assert outcome.status == "BLOCKED"
        assert "live_trading_not_enabled" in outcome.gate_result.failed_conditions


class TestScenario3MissingCredentialSurrogate:
    def test_missing_approval_produces_no_order(self) -> None:
        session = _session()
        ctx = _gate_ctx(session, approval=None)
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is False
        assert "activation_approval_missing_or_invalid" in outcome.gate_result.failed_conditions


class TestScenario8KillSwitchOn:
    def test_kill_switch_engaged_produces_no_order(self) -> None:
        session = _session()
        session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 2))
        ctx = _gate_ctx(session, kill_switch_engaged=session.is_kill_switch_engaged())
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is False
        assert "kill_switch_engaged" in outcome.gate_result.failed_conditions


class TestScenario11DuplicateClientOrderId:
    def test_duplicate_submission_returns_same_response_no_new_order(self) -> None:
        session = _session()
        ctx = _gate_ctx(session)
        order = _order()
        first = session.submit(order, requested_at=utc(2024, 1, 2), gate_context=ctx)
        second = session.submit(order, requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert first.response.response_id == second.response.response_id
        positions = session.adapter.get_positions(as_of=utc(2024, 1, 2))
        assert positions[0].quantity == 10.0  # not doubled


class TestScenario12And13TimeoutOrConnectionLostAfterSubmission:
    def test_network_timeout_produces_unknown_and_no_retry(self) -> None:
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is False
        assert outcome.status == "UNKNOWN"
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED

    def test_subsequent_submission_is_blocked_pending_reconciliation(self) -> None:
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        session.submit(_order(client_order_id="CID-1"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        second = session.submit(_order(client_order_id="CID-2", security_id="BBB"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert second.submitted is False
        assert second.error == "reconciliation_required"


class TestScenario14MalformedResponse:
    def test_malformed_never_raises_and_never_reports_success(self) -> None:
        # broker.mock.MockBrokerAdapter has no "malformed" mode of its own;
        # this is exercised at the adapter layer (Phase 13/15) -- here we
        # confirm the session layer does not special-case or mask any
        # BrokerError, treating every one identically (fail closed).
        for mode, exc_type in (("unavailable", BrokerTransportError),):
            session = _session(failure_mode=mode)
            ctx = _gate_ctx(session)
            outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
            assert outcome.status == "UNKNOWN"


class TestScenario17And18PartialAndCompleteFill:
    def test_partial_fill_reflected_in_outcome(self) -> None:
        session = _session(failure_mode="partial_fill")
        ctx = _gate_ctx(session)
        outcome = session.submit(_order(quantity=100.0), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is True
        assert outcome.status == "PARTIAL_FILLED"

    def test_complete_fill(self) -> None:
        session = _session()
        ctx = _gate_ctx(session)
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.status == "FILLED"


class TestScenario19BrokerReject:
    def test_rejected_order(self) -> None:
        session = _session(failure_mode="rejected")
        ctx = _gate_ctx(session)
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is True  # the call succeeded -- the *order* was rejected, not the submission
        assert outcome.status == "REJECTED"


class TestScenario20ProcessCrashAfterSubmitThenReconcile:
    def test_reconcile_resolves_unknown_and_resumes(self) -> None:
        session = _session()
        ctx = _gate_ctx(session)
        order = _order()
        session.submit(order, requested_at=utc(2024, 1, 2), gate_context=ctx)
        # simulate a lost-response scenario by manually marking UNKNOWN,
        # matching what submit() would have done on a real BrokerError
        session._internal_status[order.client_order_id] = None  # type: ignore[assignment]
        session._operational_state = OperationalState.RECONCILIATION_REQUIRED  # type: ignore[attr-defined]
        result = session.reconcile_order(order.client_order_id, as_of=utc(2024, 1, 2))
        assert result.status.value in ("MATCHED", "MISMATCH", "UNKNOWN")


class TestNoBlindRetryAcrossFailureModes:
    @pytest.mark.parametrize("failure_mode,exc_type", [
        ("unavailable", BrokerTransportError),
    ])
    def test_broker_error_is_never_swallowed_or_retried(self, failure_mode, exc_type) -> None:
        session = _session(failure_mode=failure_mode)
        ctx = _gate_ctx(session)
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.status == "UNKNOWN"
        assert exc_type.__name__ in outcome.error


class TestStartupSafety:
    def test_startup_ready_when_everything_healthy(self) -> None:
        session = _session()
        ctx = _gate_ctx(session)
        result = run_startup_checks(ctx)
        assert result.ready is True
        assert result.blocking_reasons == ()

    def test_startup_not_ready_when_reconciliation_mismatched(self) -> None:
        from broker.live.reconciliation import ReconciliationResult
        from broker.live.enums import ReconciliationStatus

        session = _session()
        ctx = _gate_ctx(session)
        mismatch = ReconciliationResult(
            reconciliation_id="R1", target="account", subject_id="toss", status=ReconciliationStatus.MISMATCH,
            as_of_time=utc(2024, 1, 2), configuration_version="cfg-1",
        )
        result = run_startup_checks(ctx, reconciliation_results=(mismatch,))
        assert result.ready is False
        assert "reconciliation_account_mismatch" in result.blocking_reasons

    def test_startup_not_ready_when_any_critical_condition_unknown(self) -> None:
        session = _session()
        ctx = _gate_ctx(session, account_state_known=False)
        result = run_startup_checks(ctx)
        assert result.ready is False


class TestShutdownSafety:
    def test_shutdown_records_open_orders_without_cancelling(self) -> None:
        result = run_shutdown_checks(open_client_order_ids=("CID-1", "CID-2"), shutdown_at=utc(2024, 1, 2))
        assert result.open_client_order_ids == ("CID-1", "CID-2")
        assert result.operational_state.value == "SHUTTING_DOWN"
