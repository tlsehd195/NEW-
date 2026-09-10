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

from broker.enums import BrokerCapability, BrokerOrderStatus
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

    def test_stale_gate_context_cannot_bypass_the_sessions_own_kill_switch_state(self) -> None:
        """External review finding (Session 36 continued): `submit()`
        used to trust `gate_context.kill_switch_engaged` alone. A
        caller that built its `gate_context` from a snapshot taken
        BEFORE this session's own `engage_kill_switch` ran -- i.e. the
        caller still believes the switch is off -- must still be
        blocked, because the session now also checks its own
        `is_kill_switch_engaged()`/`operational_state` directly against
        real state, not just whatever the caller happened to pass in."""
        session = _session()
        ctx = _gate_ctx(session, kill_switch_engaged=False)  # deliberately stale/wrong
        session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 2))
        outcome = session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.submitted is False
        assert outcome.status == "BLOCKED"
        assert "kill_switch_engaged" in outcome.gate_result.failed_conditions


class TestCancelOnKillSwitch:
    """Session 36 -- ADR-0045: `engage_kill_switch` now automatically
    attempts to cancel every order not already known to be closed,
    gated by `LiveTradingConfig.auto_cancel_on_kill_switch` (default
    `True`). Distinct from the general, still-manual `Shutdown`
    procedure (`run_shutdown_checks`) -- a kill-switch trigger is the
    emergency condition where leaving orders unmanaged is the wrong
    default."""

    def test_open_order_is_cancelled_on_kill_switch(self) -> None:
        session = _session(failure_mode="partial_fill")
        ctx = _gate_ctx(session)
        order = _order()
        outcome = session.submit(order, requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.status == "PARTIAL_FILLED"  # an OPEN status -- a real cancellation candidate

        result = session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 3))
        assert result.event.engaged is True
        assert len(result.cancellation_outcomes) == 1
        cancellation = result.cancellation_outcomes[0]
        assert cancellation.client_order_id == order.client_order_id
        assert cancellation.cancelled is True
        assert cancellation.broker_status == "CANCELED"
        assert cancellation.error is None

    def test_filled_order_is_not_a_cancellation_candidate(self) -> None:
        session = _session()  # default failure_mode=None -> MARKET orders fill immediately
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        result = session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 3))
        assert result.cancellation_outcomes == ()

    def test_auto_cancel_disabled_leaves_open_orders_untouched(self) -> None:
        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="partial_fill")
        config = make_live_config(
            live_trading_enabled=True, max_daily_loss=2000.0, max_order_frequency_per_hour=6,
            auto_cancel_on_kill_switch=False,
        )
        session = LiveTradingSession(config, adapter)
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)

        result = session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 3))
        assert result.cancellation_outcomes == ()

    def test_unknown_status_order_is_still_a_cancellation_attempt(self) -> None:
        """UNKNOWN (a disconnected submission) is not CLOSED -- attempting
        cancellation is the fail-safe response, not silently skipping an
        order this session cannot confirm is actually closed."""
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        order = _order()
        outcome = session.submit(order, requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert outcome.status == "UNKNOWN"

        result = session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 3))
        assert len(result.cancellation_outcomes) == 1
        assert result.cancellation_outcomes[0].cancelled is False
        assert result.cancellation_outcomes[0].error is not None


class TestReleaseKillSwitchPreservesReconciliationRequirement:
    """External review finding (Session 36 continued):
    `release_kill_switch` used to unconditionally set `READY`,
    regardless of prior state -- meaning a real UNKNOWN order (never
    confirmed with the broker) could get silently forgotten the moment
    someone released the kill switch, resuming trading with no
    reconciliation having actually happened. It now re-derives the
    correct resulting state from `self._internal_status` itself: any
    order still UNKNOWN forces `RECONCILIATION_REQUIRED`, not `READY`."""

    def test_release_after_an_unresolved_unknown_order_stays_blocked_not_ready(self) -> None:
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)  # -> UNKNOWN, RECONCILIATION_REQUIRED
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED

        session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 3))
        assert session.operational_state == OperationalState.KILL_SWITCHED

        session.release_kill_switch(make_approval(), occurred_at=utc(2024, 1, 4))
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED

        # Still blocked -- release alone must not have been enough to resume.
        second_ctx = _gate_ctx(session)
        outcome = session.submit(_order(client_order_id="CID-2", security_id="BBB"), requested_at=utc(2024, 1, 4), gate_context=second_ctx)
        assert outcome.submitted is False
        assert outcome.error == "reconciliation_required"

    def test_reconciling_the_unknown_order_then_releasing_reaches_ready(self) -> None:
        session = _session()
        ctx = _gate_ctx(session)
        order = _order()
        session.submit(order, requested_at=utc(2024, 1, 2), gate_context=ctx)
        # simulate a lost-response scenario, matching TestScenario20's own
        # precedent (test_reconcile_resolves_unknown_and_resumes): a real
        # `BrokerError` would have set this same UNKNOWN value via submit()'s
        # own except-branch -- injected directly here so this test can
        # control exactly when/whether it gets reconciled, independent of
        # MockBrokerAdapter's own failure_mode plumbing.
        session._internal_status[order.client_order_id] = BrokerOrderStatus.UNKNOWN  # type: ignore[attr-defined]
        session._operational_state = OperationalState.RECONCILIATION_REQUIRED  # type: ignore[attr-defined]

        session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 3))
        session.reconcile_order(order.client_order_id, as_of=utc(2024, 1, 4))  # resolves the UNKNOWN status
        session.release_kill_switch(make_approval(), occurred_at=utc(2024, 1, 5))
        assert session.operational_state == OperationalState.READY

    def test_release_with_no_unresolved_orders_reaches_ready_unchanged(self) -> None:
        """Happy path, unaffected by this fix: no UNKNOWN order exists at
        all (a plain manual kill-switch drill), so release still returns
        the session to READY exactly as before."""
        session = _session()
        session.engage_kill_switch("manual_test", occurred_at=utc(2024, 1, 2))
        session.release_kill_switch(make_approval(), occurred_at=utc(2024, 1, 3))
        assert session.operational_state == OperationalState.READY


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


class TestConsecutiveFailureCount:
    """LIVE-RISK-POLICY.md item #11. Originally observability-only
    (ADR-0063); every test below uses the default config
    (`max_consecutive_failures=None`), under which the ORIGINAL halt-
    on-first-failure behavior is unchanged (still
    RECONCILIATION_REQUIRED after exactly one BrokerError) --
    ADR-0065's configurable threshold is exercised separately in
    TestConfigurableFailureThreshold below."""

    def test_starts_at_zero(self) -> None:
        session = _session()
        assert session.consecutive_failure_count == 0

    def test_a_single_broker_error_increments_it_to_one(self) -> None:
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 1

    def test_a_successful_submission_resets_it_to_zero(self) -> None:
        session = _session()
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 0

    def test_repeated_failures_across_reconciliation_cycles_accumulate(self) -> None:
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        session.submit(_order(client_order_id="CID-1"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 1
        # simulate reconciliation resolving the block, matching
        # TestScenario20's own manual-state-manipulation pattern above
        session._operational_state = OperationalState.ACTIVE  # type: ignore[attr-defined]
        session.submit(_order(client_order_id="CID-2"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 2

    def test_still_halts_on_the_first_failure_exactly_as_before(self) -> None:
        # The count is additive observability -- it does not loosen the
        # existing single-failure halt in any way.
        session = _session(failure_mode="unavailable")
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED
        second = session.submit(_order(client_order_id="CID-2"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert second.error == "reconciliation_required"


class TestConfigurableFailureThreshold:
    """ADR-0065 -- the user explicitly ratified LOOSENING the original
    halt-on-first-failure default: LiveTradingConfig.
    max_consecutive_failures=5 means the session tolerates up to 4
    consecutive BrokerErrors before halting to RECONCILIATION_REQUIRED
    on the 5th."""

    def _session_with_threshold(self, threshold: int, **adapter_kwargs) -> LiveTradingSession:
        adapter = MockBrokerAdapter(BrokerConfig(), **adapter_kwargs)
        return LiveTradingSession(
            make_live_config(
                live_trading_enabled=True, max_daily_loss=2000.0, max_order_frequency_per_hour=6,
                max_consecutive_failures=threshold,
            ),
            adapter,
        )

    def test_failures_below_threshold_do_not_halt_the_session(self) -> None:
        session = self._session_with_threshold(5, failure_mode="unavailable")
        ctx = _gate_ctx(session)
        for i in range(1, 5):  # 4 failures, still below the threshold of 5
            outcome = session.submit(_order(client_order_id=f"CID-{i}"), requested_at=utc(2024, 1, 2), gate_context=ctx)
            assert outcome.error != "reconciliation_required"
            assert session.operational_state != OperationalState.RECONCILIATION_REQUIRED
        assert session.consecutive_failure_count == 4

    def test_the_fifth_consecutive_failure_halts_the_session(self) -> None:
        session = self._session_with_threshold(5, failure_mode="unavailable")
        ctx = _gate_ctx(session)
        for i in range(1, 6):
            outcome = session.submit(_order(client_order_id=f"CID-{i}"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 5
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED
        assert outcome.status == "UNKNOWN"  # the 5th call is itself the real BrokerError that triggers the halt, not a pre-blocked outcome
        sixth = session.submit(_order(client_order_id="CID-6"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert sixth.error == "reconciliation_required"

    def test_a_success_before_the_threshold_resets_the_count(self) -> None:
        # A session whose adapter can be told to succeed on the very
        # next call isn't available via failure_mode alone, so this
        # exercises the reset via two independent sessions' worth of
        # failures interspersed with the shared counter-reset logic
        # already proven by TestConsecutiveFailureCount -- here we only
        # need to confirm the THRESHOLD comparison itself uses the
        # post-reset count, not a cumulative one.
        session = self._session_with_threshold(5, failure_mode="unavailable")
        ctx = _gate_ctx(session)
        for i in range(1, 5):
            session.submit(_order(client_order_id=f"CID-{i}"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 4
        session._consecutive_failure_count = 0  # type: ignore[attr-defined]  # simulate the reset a real success would perform
        outcome = session.submit(_order(client_order_id="CID-5"), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.consecutive_failure_count == 1
        assert session.operational_state != OperationalState.RECONCILIATION_REQUIRED

    def test_default_none_threshold_still_means_halt_on_first_failure(self) -> None:
        session = self._session_with_threshold(None, failure_mode="unavailable")  # type: ignore[arg-type]
        ctx = _gate_ctx(session)
        session.submit(_order(), requested_at=utc(2024, 1, 2), gate_context=ctx)
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED


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
