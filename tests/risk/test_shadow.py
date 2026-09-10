"""Category: shadow-evaluation harness (Session 36 continued -- the
fifth of 5 items found comparing this project against dragon1086/
prism-insight). Demonstrated against the concrete first candidate,
ADR-0093's reentry-cooldown proposal (5 trading days, PROPOSED not
ratified) -- exercising exactly the "does the shadow policy ever affect
the real decision" guarantee this module exists for.
"""

from __future__ import annotations

import pytest
from risk_helpers import FakePrediction, empty_portfolio, make_decision, utc

from risk.config import RiskConfig
from risk.engine import DeterministicPortfolioRiskEngine
from risk.enums import RiskCheckStatus
from risk.shadow import (
    InMemoryShadowEvaluationRepository,
    ShadowEvaluationRecord,
    ShadowIdAllocator,
    evaluate_in_shadow,
)
from risk.sizing import DeterministicPositionSizer

T = utc(2024, 6, 1)


def _sized_buy():
    sizer = DeterministicPositionSizer()
    decision = make_decision(T, confidence=0.9)
    return sizer.size("AAA", T, decision, FakePrediction(0.10), None, empty_portfolio(), current_price=50.0)


class TestEvaluateInShadow:
    def test_real_result_is_unaffected_by_the_shadow_engine(self) -> None:
        """The central guarantee: whatever the shadow engine would have
        done, the REAL result returned is byte-identical to calling
        real_engine.assess(...) alone."""
        sizing = _sized_buy()
        real_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))
        shadow_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        allocator = ShadowIdAllocator()

        standalone = real_engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 30)},
        )
        real_result, evaluation = evaluate_in_shadow(
            real_engine, shadow_engine, security_id="AAA", as_of_time=T, sizing_result=sizing,
            portfolio_state=empty_portfolio(), policy_name="reentry_cooldown_days=5",
            shadow_id=allocator.allocate(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 30)},
        )
        assert real_result.status == standalone.status == RiskCheckStatus.PASS
        assert real_result.reason == standalone.reason

    def test_diverged_true_when_the_shadow_policy_would_have_rejected(self) -> None:
        sizing = _sized_buy()
        real_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))
        shadow_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))

        real_result, evaluation = evaluate_in_shadow(
            real_engine, shadow_engine, security_id="AAA", as_of_time=T, sizing_result=sizing,
            portfolio_state=empty_portfolio(), policy_name="reentry_cooldown_days=5",
            shadow_id="SHADOW-000001", current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 30)},  # 2 days before T -- within a 5-day cooldown
        )
        assert real_result.status == RiskCheckStatus.PASS  # the real, currently-ratified policy is unaffected
        assert evaluation.real_status == RiskCheckStatus.PASS
        assert evaluation.shadow_status == RiskCheckStatus.REJECT
        assert evaluation.shadow_reason == "reentry_cooldown_breached"
        assert evaluation.diverged is True

    def test_diverged_false_when_both_agree(self) -> None:
        sizing = _sized_buy()
        real_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))
        shadow_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))

        real_result, evaluation = evaluate_in_shadow(
            real_engine, shadow_engine, security_id="AAA", as_of_time=T, sizing_result=sizing,
            portfolio_state=empty_portfolio(), policy_name="reentry_cooldown_days=5",
            shadow_id="SHADOW-000001", current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 1)},  # well outside any plausible cooldown
        )
        assert evaluation.diverged is False
        assert evaluation.real_status == evaluation.shadow_status == RiskCheckStatus.PASS

    def test_evaluation_is_persisted_when_a_repository_is_supplied(self) -> None:
        sizing = _sized_buy()
        real_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))
        shadow_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        repo = InMemoryShadowEvaluationRepository()

        evaluate_in_shadow(
            real_engine, shadow_engine, security_id="AAA", as_of_time=T, sizing_result=sizing,
            portfolio_state=empty_portfolio(), policy_name="reentry_cooldown_days=5",
            shadow_id="SHADOW-000001", repository=repo, current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 30)},
        )
        stored = repo.list_evaluations()
        assert len(stored) == 1
        assert stored[0].shadow_id == "SHADOW-000001"
        assert stored[0].diverged is True

    def test_no_repository_supplied_still_returns_the_evaluation(self) -> None:
        sizing = _sized_buy()
        real_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))
        shadow_engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))

        _real, evaluation = evaluate_in_shadow(
            real_engine, shadow_engine, security_id="AAA", as_of_time=T, sizing_result=sizing,
            portfolio_state=empty_portfolio(), policy_name="reentry_cooldown_days=5",
            shadow_id="SHADOW-000001", current_price=50.0,
        )
        assert isinstance(evaluation, ShadowEvaluationRecord)


class TestInMemoryShadowEvaluationRepository:
    def test_list_evaluations_filters_by_policy_name(self) -> None:
        repo = InMemoryShadowEvaluationRepository()
        repo.record(ShadowEvaluationRecord(
            shadow_id="SHADOW-000001", as_of_time=T, security_id="AAA", policy_name="reentry_cooldown_days=5",
            real_status=RiskCheckStatus.PASS, real_reason="risk_checks_passed",
            shadow_status=RiskCheckStatus.REJECT, shadow_reason="reentry_cooldown_breached", diverged=True,
        ))
        repo.record(ShadowEvaluationRecord(
            shadow_id="SHADOW-000002", as_of_time=T, security_id="BBB", policy_name="reentry_cooldown_days=10",
            real_status=RiskCheckStatus.PASS, real_reason="risk_checks_passed",
            shadow_status=RiskCheckStatus.PASS, shadow_reason="risk_checks_passed", diverged=False,
        ))
        assert len(repo.list_evaluations(policy_name="reentry_cooldown_days=5")) == 1
        assert len(repo.list_evaluations(security_id="BBB")) == 1
        assert len(repo.list_evaluations(diverged_only=True)) == 1
        assert len(repo.list_evaluations()) == 2

    def test_evaluation_record_rejects_empty_ids(self) -> None:
        with pytest.raises(ValueError):
            ShadowEvaluationRecord(
                shadow_id="", as_of_time=T, security_id="AAA", policy_name="reentry_cooldown_days=5",
                real_status=RiskCheckStatus.PASS, real_reason="ok",
                shadow_status=RiskCheckStatus.PASS, shadow_reason="ok", diverged=False,
            )
        with pytest.raises(ValueError):
            ShadowEvaluationRecord(
                shadow_id="SHADOW-000001", as_of_time=T, security_id="AAA", policy_name="",
                real_status=RiskCheckStatus.PASS, real_reason="ok",
                shadow_status=RiskCheckStatus.PASS, shadow_reason="ok", diverged=False,
            )

    def test_evaluation_record_requires_timezone_aware_as_of_time(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError):
            ShadowEvaluationRecord(
                shadow_id="SHADOW-000001", as_of_time=datetime(2024, 6, 1), security_id="AAA",
                policy_name="reentry_cooldown_days=5",
                real_status=RiskCheckStatus.PASS, real_reason="ok",
                shadow_status=RiskCheckStatus.PASS, shadow_reason="ok", diverged=False,
            )


class TestShadowIdAllocator:
    def test_ids_are_monotonic(self) -> None:
        allocator = ShadowIdAllocator()
        assert allocator.allocate() == "SHADOW-000001"
        assert allocator.allocate() == "SHADOW-000002"
