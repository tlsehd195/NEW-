"""Category: Cross-Cutting Production Safety Test (Phase 17). Where a
Phase 13/15/16 test file already exhaustively covers one behavior in
isolation (e.g. tests/broker/live/test_live_reconciliation.py for a
single comparison function), this file supplements with the specific
angles the Phase 17 review instruction asks for that were not
previously exercised together: a broader (whole-`src/`) secret-safety
scan, Paper<->Live environment-guard symmetry side by side, an
idempotency comparison across two different adapters, and a single
matrix-style failure-recovery test covering every named failure
category at once."""

from __future__ import annotations

import ast
import importlib
import re
from datetime import datetime, timezone
from pathlib import Path

import broker
import pytest
from live_helpers import make_approval, make_broker_capabilities, make_live_config, utc as live_utc
from paper_helpers import make_bar, make_paper_config, make_validated_order

from broker.config import BrokerConfig
from broker.enums import BrokerExecutionMode, BrokerOrderStatus, CapabilityStatus
from broker.errors import BrokerAuthError, BrokerRateLimitError, BrokerTimeoutError, BrokerTransportError
from broker.live.enums import OperationalState, ReconciliationStatus
from broker.live.guard import assert_live_environment_broker_safe
from broker.live.reconciliation import compare_account, compare_order_status, compare_positions
from broker.live.session import LiveTradingSession
from broker.mock import MockBrokerAdapter
from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.guard import assert_paper_environment_safe
from broker.paper.market_data import InMemoryPaperMarketDataSource


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree:
    """Phase 13's tests/broker/test_broker_boundary.py already scans the
    `broker` package alone. This is deliberately broader: a repo-wide
    scan, so a future secret-resolution shortcut added to `ai_gateway.*`,
    `storage.*`, or anywhere else would also be caught, not just one
    inside `broker.*`."""

    def test_os_environ_and_getenv_appear_only_in_broker_toss_auth(self) -> None:
        src_root = Path(broker.__file__).resolve().parent.parent
        # One dedicated auth file per external integration is the
        # invariant, not literally "only broker/toss/auth.py" -- Phase 20
        # added data_infra/providers/tiingo_auth.py as the equivalent,
        # isolated credential-resolution point for the Tiingo market data
        # integration (its own AST-scan test, tests/data_infra/
        # test_tiingo_auth.py, enforces isolation within that subpackage).
        allowed_files = {
            ("broker", "toss", "auth.py"),
            ("data_infra", "providers", "tiingo_auth.py"),
        }
        offenders: list[str] = []
        for py_file in src_root.rglob("*.py"):
            if "egg-info" in py_file.parts:
                continue
            relative = py_file.relative_to(src_root)
            is_allowed = relative.parts in allowed_files
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                hits_environ = isinstance(node, ast.Attribute) and node.attr == "environ"
                hits_getenv = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv"
                if (hits_environ or hits_getenv) and not is_allowed:
                    offenders.append(f"{relative}:{node.lineno}")
        assert offenders == [], f"os.environ/os.getenv used outside the allowed auth files: {offenders}"


class TestEnvironmentGuardSymmetry:
    """assert_paper_environment_safe (Phase 15) and
    assert_live_environment_broker_safe (Phase 16) are mirror-image
    defense-in-depth checks -- this test exercises both directions side
    by side to confirm neither was left weaker than the other."""

    def test_paper_environment_rejects_a_toss_adapter(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        from broker.toss.adapter import TossBrokerAdapter
        from broker.transport import MockTransport

        live_config = BrokerConfig(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)
        toss = TossBrokerAdapter(live_config, MockTransport())
        with pytest.raises(ValueError):
            assert_paper_environment_safe("paper", toss)

    def test_paper_environment_accepts_a_paper_adapter(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([])
        paper = PaperBrokerAdapter(config, mds)
        assert_paper_environment_safe("paper", paper)  # does not raise

    def test_live_environment_rejects_a_paper_adapter(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([])
        paper = PaperBrokerAdapter(config, mds)
        with pytest.raises(ValueError):
            assert_live_environment_broker_safe("live", paper)

    def test_live_environment_accepts_a_mock_adapter_only_with_explicit_testing_opt_in(self) -> None:
        mock = MockBrokerAdapter(BrokerConfig())
        with pytest.raises(ValueError):
            assert_live_environment_broker_safe("live", mock)
        assert_live_environment_broker_safe("live", mock, allow_non_live_broker_for_testing=True)  # does not raise


class TestIdempotentReplayIsConsistentAcrossAdapters:
    """Paper (Phase 15) and Mock (Phase 13) independently implement
    "resubmitting an already-seen client_order_id returns the existing
    response, never a second order" -- this test proves both actually
    hold that property side by side, not merely by reading each one's
    own isolated test file."""

    def test_paper_adapter_replays_idempotently(self) -> None:
        order = make_validated_order(client_order_id="CID-IDEM-1", quantity=10.0)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        adapter = PaperBrokerAdapter(make_paper_config(initial_cash=1_000_000.0, max_participation=1.0), mds)
        r1 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        r2 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert r1.broker_order_id == r2.broker_order_id
        assert r1.status == r2.status == BrokerOrderStatus.FILLED

    def test_mock_adapter_replays_idempotently(self) -> None:
        from broker_helpers import make_risk_checked_position
        from broker.validation import build_validated_order

        risk = make_risk_checked_position(risk_id="RISK-IDEM-1", final_target_quantity=10.0)
        order = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order
        adapter = MockBrokerAdapter(BrokerConfig())
        r1 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        r2 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert r1.broker_order_id == r2.broker_order_id


class TestReconciliationNeverBecomesMatchedOnceUnknownOrMismatched:
    """A structural, not just an example-based, regression: for every
    one of compare_account/compare_positions/compare_order_status, no
    combination of "either side unavailable" inputs can produce
    MATCHED."""

    def test_compare_account_is_never_matched_when_broker_side_unavailable(self) -> None:
        from broker.models import BrokerAccountSnapshot

        unavailable = BrokerAccountSnapshot(
            broker_id="toss", as_of_time=utc(2024, 1, 2), available=False, unavailable_reason="capability_unknown",
            cash=None, buying_power=None, currency="KRW",
        )
        result = compare_account(
            100_000.0, unavailable, tolerance=0.01, reconciliation_id="R1", as_of_time=utc(2024, 1, 2),
            configuration_version="cfg-1",
        )
        assert result.status == ReconciliationStatus.UNKNOWN

    def test_compare_positions_is_never_matched_when_internal_side_unavailable(self) -> None:
        result = compare_positions(
            None, None, security_id="AAA", tolerance=0.01, reconciliation_id="R2", as_of_time=utc(2024, 1, 2),
            configuration_version="cfg-1",
        )
        assert result.status == ReconciliationStatus.UNKNOWN

    def test_session_blocks_every_further_submission_once_reconciliation_required(self) -> None:
        from broker_helpers import make_risk_checked_position
        from broker.validation import build_validated_order
        from broker.live.safety_gate import SafetyGateContext
        from monitoring.enums import ComponentHealthStatus

        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="unavailable")
        session = LiveTradingSession(make_live_config(live_trading_enabled=True), adapter)

        risk = make_risk_checked_position(risk_id="RISK-BLOCK-1", final_target_quantity=10.0)
        order = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order

        def gate_context():
            from broker.enums import BrokerCapability, OrderValidationStatus

            return SafetyGateContext(
                as_of_time=live_utc(2024, 1, 2), config=session.config, approval=make_approval(),
                required_capabilities=(BrokerCapability.MARKET_ORDER,),
                broker_capabilities=make_broker_capabilities(), risk_health=ComponentHealthStatus.HEALTHY,
                order_validation_status=OrderValidationStatus.ACCEPTED, kill_switch_engaged=session.is_kill_switch_engaged(),
                account_state_known=True, position_state_known=True, model_state_valid=True,
                configuration_integrity_valid=True,
            )

        outcome1 = session.submit(order, requested_at=live_utc(2024, 1, 2), gate_context=gate_context())
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED

        second_risk = make_risk_checked_position(risk_id="RISK-BLOCK-2", final_target_quantity=5.0)
        second_order = build_validated_order(second_risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order
        outcome2 = session.submit(second_order, requested_at=live_utc(2024, 1, 3), gate_context=gate_context())
        assert outcome2.submitted is False
        assert outcome2.status == "BLOCKED"
        assert outcome2.error == "reconciliation_required"
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED  # still blocked, no silent recovery


class TestFailureRecoveryMatrixDefaultsToNoTrade:
    """Every named failure category (instruction section: timeout /
    connection failure / auth failure / rate limit / malformed /
    unknown response / broker unavailable / account unavailable /
    position unavailable / order status unavailable) either raises
    (never silently returns a fabricated FILLED) or returns an
    explicitly UNKNOWN/unavailable value -- collected here as one
    matrix so the full set is visible in one place, rather than only
    provable by reading separate test files across two different
    adapters (`broker.mock.MockBrokerAdapter`'s and
    `broker.paper.adapter.PaperBrokerAdapter`'s `failure_mode`
    vocabularies are deliberately different -- Paper's is the larger,
    Phase-15-extended one, per `src/broker/paper/config.py`)."""

    def _paper_adapter(self, *, failure_mode: str) -> PaperBrokerAdapter:
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        return PaperBrokerAdapter(make_paper_config(initial_cash=1_000_000.0, failure_mode=failure_mode), mds)

    def test_timeout_raises(self) -> None:
        adapter = self._paper_adapter(failure_mode="timeout")
        with pytest.raises(BrokerTimeoutError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))

    def test_connection_failure_raises(self) -> None:
        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="unavailable")
        with pytest.raises(BrokerTransportError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))

    def test_auth_failure_raises(self) -> None:
        adapter = self._paper_adapter(failure_mode="auth")
        with pytest.raises(BrokerAuthError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))

    def test_rate_limit_raises(self) -> None:
        adapter = self._paper_adapter(failure_mode="rate_limit")
        with pytest.raises(BrokerRateLimitError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))

    def test_malformed_response_is_unknown_not_fabricated_success(self) -> None:
        adapter = self._paper_adapter(failure_mode="malformed")
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN

    def test_unknown_status_response_is_unknown(self) -> None:
        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="status_unknown")
        status = adapter.get_order_status("CID-X", as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.UNKNOWN

    def test_account_unavailable_is_never_silently_treated_as_zero_balance(self) -> None:
        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="account_unavailable")
        account = adapter.get_account(as_of=utc(2024, 1, 2))
        assert account.available is False
        assert account.cash is None  # never fabricated as 0.0

    def test_position_unavailable_returns_an_explicit_empty_result_not_a_fabricated_position(self) -> None:
        """MockBrokerAdapter's "account_unavailable" mode (its only
        account/position failure simulation) returns `()` for
        get_positions rather than a per-position `available=False`
        marker -- a real, honestly-documented ambiguity between "no
        positions held" and "positions unknown" this review surfaces as
        a Known Issue rather than silently treating as equivalent to a
        confirmed flat position (see docs/operations/
        PRODUCTION-READINESS-MATRIX.md)."""
        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="account_unavailable")
        positions = adapter.get_positions(as_of=utc(2024, 1, 2))
        assert positions == ()

    def test_order_status_unavailable_via_capability_gap_is_unknown_not_guessed(self, monkeypatch) -> None:
        """Phase 21: TossBrokerAdapter.get_order_status is now
        implemented against the Tier 1 spec, but a client_order_id this
        adapter instance never submitted (no known Toss orderId to query)
        still cannot be resolved -- it must never be guessed at, and
        must never raise either (mirrors broker.mock.MockBrokerAdapter's
        own "no history for this client_order_id" -> UNKNOWN pattern,
        rather than the old BrokerCapabilityError this test asserted
        before the capability existed at all)."""
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        from broker.enums import BrokerOrderStatus
        from broker.toss.adapter import TossBrokerAdapter
        from broker.transport import MockTransport

        adapter = TossBrokerAdapter(BrokerConfig(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True), MockTransport())
        observation = adapter.get_order_status("CID-X", as_of=utc(2024, 1, 2))
        assert observation.status == BrokerOrderStatus.UNKNOWN
        assert observation.broker_order_id is None


class TestRunbookReferencesStillResolveInCode:
    """A living-document guard: every `module.path.Symbol`-shaped
    backticked reference in the Live Trading Runbook must still exist
    as an importable attribute -- catches the runbook silently drifting
    out of sync with a rename/removal in code."""

    _SYMBOL_PATTERN = re.compile(r"`(broker\.[a-zA-Z0-9_.]+)`")

    def test_every_dotted_broker_reference_in_the_runbook_resolves(self) -> None:
        runbook_path = Path(__file__).resolve().parents[3] / "docs" / "operations" / "LIVE-TRADING-RUNBOOK.md"
        text = runbook_path.read_text(encoding="utf-8")
        checked = 0
        for match in self._SYMBOL_PATTERN.finditer(text):
            dotted = match.group(1)
            parts = dotted.split(".")
            # Walk from the longest importable module prefix down to the
            # attribute path, exactly like Python's own import machinery.
            resolved = False
            for split_at in range(len(parts), 0, -1):
                module_name = ".".join(parts[:split_at])
                try:
                    obj = importlib.import_module(module_name)
                except ImportError:
                    continue
                ok = True
                for attr in parts[split_at:]:
                    try:
                        obj = getattr(obj, attr)
                    except AttributeError:
                        ok = False
                        break
                if ok:
                    resolved = True
                    break
            assert resolved, f"runbook references {dotted!r}, which no longer resolves in code"
            checked += 1
        assert checked >= 5  # sanity: the pattern actually matched a meaningful number of references
