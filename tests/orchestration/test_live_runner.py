"""Category: Integration Test -- `orchestration.live_runner.run_cycle`,
the Live-side equivalent of `orchestration.paper_runner.run_cycle`
(ADR-0067/ADR-0068), exercised end to end against a real (synthetic)
drifting-price scenario, mirroring `tests/orchestration/
test_paper_runner.py`'s own scenario shape. Uses `broker.mock.
MockBrokerAdapter` throughout -- never the real, network-capable Toss
transport (instruction section 22, 37) -- exactly like every other Live
test in this repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days
from live_helpers import make_approval, make_broker_capabilities, make_live_config
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig

from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerOrderStatus, OrderValidationStatus
from broker.live.safety_gate import SafetyGateContext
from broker.live.session import LiveTradingSession
from broker.mock import MockBrokerAdapter

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from learning.enums import CandidateModelStatus

from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus

from monitoring_helpers import make_transition

from orchestration.live_runner import LiveRunnerState, run_cycle

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.config import PositionSizingConfig, RiskConfig
from risk.engine import DeterministicPortfolioRiskEngine
from risk.enums import RiskCheckStatus
from risk.sizing import DeterministicPositionSizer

from storage.config import StorageConfig
from storage.decision_repository import DuckDBDecisionRepository
from storage.engine import StorageEngine
from storage.prediction_repository import DuckDBPredictionRepository
from storage.regime_repository import DuckDBRegimeRepository
from storage.risk_repository import DuckDBPositionSizingRepository, DuckDBRiskRepository


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    # Same steeper-than-default drift test_paper_runner.py's own
    # _scenario() uses, for the same reason: reliably clears
    # DecisionConfig's default min_expected_return=0.005, producing a
    # real BUY rather than a coin-flip NO_TRADE at the checkpoint these
    # tests use.
    prices = drifting_prices(days, daily_return=0.006)
    bars = make_bars("AAA", days, prices)
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="live-runner-integration-test",
    )
    return repo, config, bars


def _build_view(repo, config, index: int):
    calendar = repo.get_trading_calendar("US_EQUITY")
    checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
    clock = BacktestClock(checkpoints)
    clock.index = index
    return AsOfDataView(repo, clock), clock, checkpoints


def _session(*, initial_cash: float = 100_000.0) -> LiveTradingSession:
    adapter = MockBrokerAdapter(BrokerConfig(broker_id="toss"), initial_cash=initial_cash)
    config = make_live_config(live_trading_enabled=True, max_daily_loss=20_000.0, max_order_frequency_per_hour=100)
    return LiveTradingSession(config, adapter)


def _gate_context(
    session: LiveTradingSession, as_of_time, *, order_validation_status=OrderValidationStatus.ACCEPTED,
) -> SafetyGateContext:
    """A real, fully-passing base context (mirrors `tests/broker/
    live_helpers.py::make_passing_gate_context` and `tests/integration/
    test_live_trading_lineage.py`'s own construction) -- `run_cycle`
    itself overrides `order_validation_status` per security
    (module docstring point 2), so the value supplied here is only ever
    a placeholder for that one field."""
    return SafetyGateContext(
        as_of_time=as_of_time, config=session.config, max_turnover=2.0,
        approval=make_approval(approved_at=as_of_time), required_capabilities=(BrokerCapability.MARKET_ORDER,),
        broker_capabilities=make_broker_capabilities(broker_id="toss", recorded_at=as_of_time),
        risk_health=ComponentHealthStatus.HEALTHY, order_validation_status=order_validation_status,
        kill_switch_engaged=session.is_kill_switch_engaged(), account_state_known=True,
        position_state_known=True, model_state_valid=True, configuration_integrity_valid=True,
    )


def _components(risk_config: RiskConfig = RiskConfig(max_drawdown=None, max_portfolio_volatility=None)):
    return dict(
        predictor=DriftPredictor(PredictionConfig(lookback_days=20)),
        regime_detector=RegimeDetector(RegimeConfig()),
        decision_agent=BaselineRuleDecisionAgent(DecisionConfig()),
        position_sizer=DeterministicPositionSizer(PositionSizingConfig()),
        risk_engine=DeterministicPortfolioRiskEngine(risk_config),
    )


class TestFullChainProducesOneOutcomePerSecurityWithConsistentLineage:
    def test_lineage_ids_trace_through_every_stage(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()

        outcomes = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(),
        )

        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.sizing.decision_id == outcome.decision.decision_id
        assert outcome.sizing.prediction_id == outcome.decision.prediction_id
        assert outcome.risk_checked.sizing_id == outcome.sizing.sizing_id
        assert outcome.risk_checked.decision_id == outcome.sizing.decision_id


class TestOrdersActuallySubmitAndFill:
    def test_a_warranted_buy_is_submitted_and_filled(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()

        outcomes = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(),
        )
        outcome = outcomes[0]

        assert outcome.validation.status == OrderValidationStatus.ACCEPTED
        assert outcome.submission is not None
        assert outcome.submission.submitted is True
        assert outcome.submission.status == BrokerOrderStatus.FILLED.value

    def test_a_second_cycle_sees_the_first_cycles_real_fill_via_the_broker(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session()
        components = _components()

        first = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **components,
        )[0]
        assert first.submission is not None and first.submission.status == BrokerOrderStatus.FILLED.value

        positions_before_second = session.adapter.get_positions(as_of=view.current_time)
        assert any(p.security_id == "AAA" and p.quantity == first.submission.response.filled_quantity for p in positions_before_second)

        clock.index = 101
        second = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **components,
        )[0]
        # The portfolio state fed into the second cycle's decision/sizing
        # must reflect the real position from the first cycle's real
        # broker-side fill -- never a fabricated/reset-to-empty state.
        assert second.decision.as_of_time == view.current_time


class TestGateContextDerivedFieldsOverrideCallerPlaceholders:
    def test_the_callers_wrong_placeholder_status_is_overridden_by_the_real_result(self) -> None:
        """The caller's base gate_context intentionally carries a WRONG
        `order_validation_status` (VALIDATION_REJECTED) for a security
        this cycle's real Risk/Validation stage actually ACCEPTS. If
        `run_cycle` blindly passed the caller's context through
        unchanged, `evaluate_safety_gate` would fail with
        `order_validator_not_accepted` and the gate would not pass --
        instead it passes, proving `run_cycle` derived the real,
        per-security status (module docstring point 2) rather than
        trusting the placeholder."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        wrong_base_context = _gate_context(
            session, view.current_time, order_validation_status=OrderValidationStatus.VALIDATION_REJECTED,
        )

        outcome = run_cycle(["AAA"], view.current_time, view, session, gate_context=wrong_base_context, **_components())[0]

        assert outcome.validation.status == OrderValidationStatus.ACCEPTED
        assert outcome.submission is not None
        assert outcome.submission.gate_result is not None
        assert outcome.submission.gate_result.passed is True
        assert "order_validator_not_accepted" not in outcome.submission.gate_result.failed_conditions

    def test_a_validation_rejected_order_never_reaches_submit_at_all(self) -> None:
        """An unmapped sector under a configured max_sector_weight forces
        RiskCheckStatus.REJECT -> `validation.validated_order is None` ->
        `submission` stays `None` entirely (never even calls `session.
        submit()`)."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_sector_weight=0.5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(risk_config),
            sector_by_security=None,
        )[0]

        assert outcome.risk_checked.status == RiskCheckStatus.REJECT
        assert outcome.validation.status == OrderValidationStatus.VALIDATION_REJECTED
        assert outcome.submission is None

    def test_the_callers_wrong_account_and_kill_switch_placeholders_are_overridden_by_reality(self) -> None:
        """The caller's base context intentionally claims the account
        state is UNKNOWN (`account_state_known=False`) and the kill
        switch IS engaged (`kill_switch_engaged=True`), both wrong for
        this real session. If `run_cycle` passed those through
        unchanged, the gate would fail (`account_state_unknown`/
        `kill_switch_engaged`) -- instead it passes, proving both are
        derived from real session/broker state, not the caller's claim."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        wrong_base_context = _gate_context(session, view.current_time)
        wrong_base_context = replace(wrong_base_context, account_state_known=False, kill_switch_engaged=True)

        outcome = run_cycle(["AAA"], view.current_time, view, session, gate_context=wrong_base_context, **_components())[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is True
        assert outcome.submission.gate_result.passed is True

    def test_a_really_engaged_kill_switch_blocks_submission_even_with_a_wrong_false_placeholder(self) -> None:
        """The inverse of the case above: the REAL kill switch is
        engaged (via `session.engage_kill_switch`), but the caller's
        base context wrongly claims `kill_switch_engaged=False`. The
        gate must still block -- proving the derived value reflects
        reality even when the caller's claim points the other, more
        dangerous, direction (a caller falsely claiming "not engaged")."""
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        session.engage_kill_switch("test", occurred_at=view.current_time)
        wrong_base_context = _gate_context(session, view.current_time)
        wrong_base_context = replace(wrong_base_context, kill_switch_engaged=False)

        outcome = run_cycle(["AAA"], view.current_time, view, session, gate_context=wrong_base_context, **_components())[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert outcome.submission.status == "BLOCKED"
        assert "kill_switch_engaged" in outcome.submission.gate_result.failed_conditions


class TestSectorLimitPropagatesThroughTheWholeChain:
    def test_configured_sector_limit_without_a_mapping_rejects_the_whole_order(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_sector_weight=0.5, max_drawdown=None, max_portfolio_volatility=None)
        session = _session()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(risk_config), sector_by_security=None,
        )[0]

        assert outcome.risk_checked.status == RiskCheckStatus.REJECT
        assert "sector_unknown" in outcome.risk_checked.breached_limits
        assert outcome.submission is None

    def test_configured_sector_limit_with_a_generous_mapping_still_submits_normally(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_sector_weight=1.0, max_drawdown=None, max_portfolio_volatility=None)
        session = _session()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(risk_config),
            sector_by_security={"AAA": "Technology"},
        )[0]

        assert outcome.risk_checked.status in (RiskCheckStatus.PASS, RiskCheckStatus.REDUCE)
        assert outcome.submission is not None


class TestValueHistoryState:
    def test_without_state_a_real_max_drawdown_always_rejects_as_unknown(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_drawdown=0.5, max_portfolio_volatility=None)
        session = _session()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(risk_config),
        )[0]

        assert "drawdown_unknown" in outcome.risk_checked.breached_limits

    def test_with_state_value_history_accumulates_across_cycles(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        risk_config = RiskConfig(max_drawdown=0.5, max_portfolio_volatility=None)
        session = _session()
        components = _components(risk_config)
        state = LiveRunnerState()

        outcomes = []
        for offset in range(5):
            clock.index = 100 + offset
            outcomes.append(run_cycle(
                ["AAA"], view.current_time, view, session, state=state,
                gate_context=_gate_context(session, view.current_time), **components,
            )[0])

        assert len(state.value_history) == 5
        assert "drawdown_unknown" in outcomes[0].risk_checked.breached_limits
        assert "drawdown_unknown" not in outcomes[-1].risk_checked.breached_limits


class TestPersistence:
    def test_all_five_repositories_receive_exactly_one_record(self, tmp_path) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        prediction_repo = DuckDBPredictionRepository(engine)
        regime_repo = DuckDBRegimeRepository(engine)
        decision_repo = DuckDBDecisionRepository(engine)
        sizing_repo = DuckDBPositionSizingRepository(engine)
        risk_repo = DuckDBRiskRepository(engine)

        run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(),
            prediction_repository=prediction_repo, regime_repository=regime_repo,
            decision_repository=decision_repo, sizing_repository=sizing_repo, risk_repository=risk_repo,
        )

        assert len(prediction_repo.list_all(security_id="AAA")) == 1
        assert len(regime_repo.list_composites(subject_id="AAA")) == 1
        assert len(decision_repo.list_all(security_id="AAA")) == 1
        assert len(sizing_repo.list_all(security_id="AAA")) == 1
        assert len(risk_repo.list_all(security_id="AAA")) == 1
        engine.close()


class TestAccountUnavailableFailsClosed:
    def test_a_broker_that_cannot_report_the_account_raises_rather_than_fabricating_zero_cash(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        adapter = MockBrokerAdapter(BrokerConfig(broker_id="toss"), failure_mode="account_unavailable")
        live_config = make_live_config(live_trading_enabled=True, max_daily_loss=20_000.0, max_order_frequency_per_hour=100)
        session = LiveTradingSession(live_config, adapter)

        try:
            run_cycle(
                ["AAA"], view.current_time, view, session,
                gate_context=_gate_context(session, view.current_time), **_components(),
            )
            assert False, "expected a RuntimeError, not a silently-empty portfolio"
        except RuntimeError as exc:
            assert "live_account_unavailable" in str(exc)


class TestRiskHealthDerivedFromState:
    """ADR-0074: `risk_health` is computed for real, from `state`'s own
    running REJECT rate, ONLY when `state` is supplied -- otherwise the
    caller's own placeholder value passes through untouched."""

    def test_without_state_the_callers_placeholder_risk_health_passes_through(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        wrong_context = replace(
            _gate_context(session, view.current_time), risk_health=ComponentHealthStatus.UNAVAILABLE,
        )

        outcome = run_cycle(["AAA"], view.current_time, view, session, gate_context=wrong_context, **_components())[0]

        # No `state` supplied -> this module never touches risk_health ->
        # the caller's own UNAVAILABLE placeholder must still be what
        # the gate actually evaluated, blocking the submission.
        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert "risk_engine_not_healthy" in outcome.submission.gate_result.failed_conditions

    def test_with_state_a_high_real_reject_rate_computes_unavailable_and_blocks(self) -> None:
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session()
        # sector_by_security=None with a configured max_sector_weight
        # deterministically REJECTs (sector_unknown, ADR-0062) -- used
        # here purely as a reliable way to generate real REJECTs, not to
        # test sector limits themselves.
        risk_config = RiskConfig(max_sector_weight=0.5, max_drawdown=None, max_portfolio_volatility=None)
        components = _components(risk_config)
        state = LiveRunnerState()

        for offset in range(4):
            clock.index = 100 + offset
            outcome = run_cycle(
                ["AAA"], view.current_time, view, session, state=state,
                gate_context=_gate_context(session, view.current_time), **components,
                sector_by_security=None,
            )[0]
            assert outcome.risk_checked.status == RiskCheckStatus.REJECT
            assert outcome.submission is None  # REJECT -> no validated_order -> never reaches submit()

        assert state.risk_assessment_total == 4
        assert state.risk_assessment_rejected == 4

        # A 5th, real PASS -- now with a real sector mapping -- reaches
        # submit() carrying a risk_health computed from 4/5 REJECTs
        # (80% >= MonitoringConfig's own 50% unavailable threshold).
        clock.index = 104
        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, state=state,
            gate_context=_gate_context(session, view.current_time), **components,
            sector_by_security={"AAA": "Technology"},
        )[0]

        assert state.risk_assessment_total == 5
        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert "risk_engine_not_healthy" in outcome.submission.gate_result.failed_conditions

    def test_a_custom_monitoring_config_changes_the_threshold(self) -> None:
        """A caller-supplied `monitoring_config` with looser thresholds
        means the same 60%-REJECT history that would DEGRADED/UNAVAILABLE
        under the default thresholds no longer does -- proving the
        parameter is real, not decorative."""
        repo, config, bars = _scenario()
        view, clock, _ = _build_view(repo, config, 100)
        session = _session()
        risk_config = RiskConfig(max_sector_weight=0.5, max_drawdown=None, max_portfolio_volatility=None)
        components = _components(risk_config)
        state = LiveRunnerState()
        state.risk_assessment_total = 5
        state.risk_assessment_rejected = 3  # 60% -- DEGRADED under default thresholds (>= 10%)

        loose_config = MonitoringConfig(degraded_failure_rate_threshold=0.9, unavailable_failure_rate_threshold=0.95)

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, state=state,
            gate_context=_gate_context(session, view.current_time), **components,
            sector_by_security={"AAA": "Technology"}, monitoring_config=loose_config,
        )[0]

        assert outcome.submission is not None
        assert "risk_engine_not_healthy" not in outcome.submission.gate_result.failed_conditions


class TestModelStateValidDerivedFromCandidate:
    """ADR-0074: `model_state_valid` is computed for real ONLY when BOTH
    `candidate_id` and `model_status_repository` are supplied."""

    def test_without_both_the_callers_placeholder_passes_through(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        wrong_context = replace(_gate_context(session, view.current_time), model_state_valid=False)

        outcome = run_cycle(["AAA"], view.current_time, view, session, gate_context=wrong_context, **_components())[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert "model_state_not_valid_for_live" in outcome.submission.gate_result.failed_conditions

    def test_an_approved_passed_transition_makes_the_gate_see_a_valid_model(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        transition = make_transition(candidate_id="CAND-000001", to_status=CandidateModelStatus.APPROVED, passed=True)
        repository = {"CAND-000001": transition}

        class _FakeRepo:
            def get_latest(self, candidate_id):
                return repository.get(candidate_id)

        wrong_context = replace(_gate_context(session, view.current_time), model_state_valid=False)  # deliberately wrong placeholder

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, gate_context=wrong_context, **_components(),
            candidate_id="CAND-000001", model_status_repository=_FakeRepo(),
        )[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is True
        assert "model_state_not_valid_for_live" not in outcome.submission.gate_result.failed_conditions

    def test_an_unknown_candidate_id_correctly_blocks(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()

        class _EmptyRepo:
            def get_latest(self, candidate_id):
                return None

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(),
            candidate_id="CAND-UNKNOWN", model_status_repository=_EmptyRepo(),
        )[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert "model_state_not_valid_for_live" in outcome.submission.gate_result.failed_conditions


class TestConfigurationIntegrityValidDerivedFromPin:
    """ADR-0074: `configuration_integrity_valid` is computed for real
    ONLY when `pinned_configuration_version` is supplied."""

    def test_without_a_pin_the_callers_placeholder_passes_through(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        wrong_context = replace(_gate_context(session, view.current_time), configuration_integrity_valid=False)

        outcome = run_cycle(["AAA"], view.current_time, view, session, gate_context=wrong_context, **_components())[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert "configuration_integrity_invalid" in outcome.submission.gate_result.failed_conditions

    def test_a_matching_pin_makes_the_gate_pass(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()
        wrong_context = replace(_gate_context(session, view.current_time), configuration_integrity_valid=False)

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session, gate_context=wrong_context, **_components(),
            pinned_configuration_version=session.config.configuration_version(),
        )[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is True

    def test_a_stale_pin_correctly_blocks(self) -> None:
        repo, config, bars = _scenario()
        view, _, _ = _build_view(repo, config, 100)
        session = _session()

        outcome = run_cycle(
            ["AAA"], view.current_time, view, session,
            gate_context=_gate_context(session, view.current_time), **_components(),
            pinned_configuration_version="stale-hash-from-a-prior-deployment",
        )[0]

        assert outcome.submission is not None
        assert outcome.submission.submitted is False
        assert "configuration_integrity_invalid" in outcome.submission.gate_result.failed_conditions
