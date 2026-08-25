"""Category: Unit Test -- PositionSizer (Phase 8 spec sections 5, 6, 9).

Covers: normal position, zero confidence, high volatility, low
liquidity, cash shortage, existing position, maximum position limit,
risk budget exceeded, oversized target_weight_hint, invalid numeric
input, negative input, boundary values, plus a dedicated regression
test for the Phase 2 cash-exhaustion bug (instruction section 11).
"""

from __future__ import annotations

import math

from risk_helpers import FakePrediction, empty_portfolio, make_decision, make_regime_with_liquidity, portfolio_holding, utc

from backtest.portfolio import PortfolioView

from risk.config import PositionSizingConfig
from risk.enums import RiskCheckStatus
from risk.sizing import DeterministicPositionSizer

from trade_journal.enums import DecisionAction

T = utc(2024, 6, 1)


class TestNormalPosition:
    def test_normal_buy_produces_a_pass_with_nonzero_quantity(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.PASS
        assert result.reason == "normal_sizing"
        assert result.proposed_target_quantity > 0
        assert 0 < result.proposed_target_weight <= PositionSizingConfig().max_position_weight

    def test_full_confidence_at_reference_volatility_hits_the_configured_cap(self) -> None:
        sizer = DeterministicPositionSizer(PositionSizingConfig(max_position_weight=0.10, reference_volatility=0.20))
        decision = make_decision(T, confidence=1.0)
        result = sizer.size("AAA", T, decision, FakePrediction(0.20), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.PASS
        assert math.isclose(result.proposed_target_weight, 0.10, rel_tol=1e-6)


class TestConfidenceHandling:
    def test_zero_confidence_sizes_to_zero(self) -> None:
        sizer = DeterministicPositionSizer()
        decision = make_decision(T, confidence=0.0)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "sized_to_zero"
        assert result.proposed_target_weight == 0.0
        assert result.proposed_target_quantity == 0.0

    def test_missing_confidence_is_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        decision = make_decision(T, confidence=None)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.UNKNOWN
        assert result.reason == "invalid_confidence"


class TestVolatilityHandling:
    def test_high_volatility_rejects_outright(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.95), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "volatility_exceeds_limit"

    def test_missing_volatility_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(None), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "volatility_unavailable"

    def test_volatility_above_reference_scales_down_but_can_still_size(self) -> None:
        sizer = DeterministicPositionSizer(PositionSizingConfig(reference_volatility=0.10, max_volatility_for_full_size=0.80))
        result = sizer.size("AAA", T, make_decision(T, confidence=1.0), FakePrediction(0.40), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.PASS
        # scaled down from the unconstrained 0.10 cap by reference/actual = 0.10/0.40 = 0.25
        assert result.proposed_target_weight < PositionSizingConfig().max_position_weight


class TestLiquidityHandling:
    def test_low_liquidity_reduces_but_does_not_zero_out(self) -> None:
        sizer = DeterministicPositionSizer()
        regime = make_regime_with_liquidity(T, "AAA", "LOW")
        with_liquidity = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), regime, empty_portfolio(), current_price=50.0)
        without = DeterministicPositionSizer().size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert with_liquidity.status == RiskCheckStatus.PASS
        assert with_liquidity.proposed_target_weight < without.proposed_target_weight
        assert with_liquidity.proposed_target_weight > 0

    def test_unknown_liquidity_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        regime = make_regime_with_liquidity(T, "AAA", "UNKNOWN")
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), regime, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "liquidity_unknown"

    def test_normal_liquidity_does_not_affect_sizing(self) -> None:
        sizer = DeterministicPositionSizer()
        regime = make_regime_with_liquidity(T, "AAA", "NORMAL")
        with_regime = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), regime, empty_portfolio(), current_price=50.0)
        without = DeterministicPositionSizer().size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert with_regime.proposed_target_weight == without.proposed_target_weight


class TestCashHandling:
    def test_cash_shortage_reduces_the_position(self) -> None:
        sizer = DeterministicPositionSizer()
        poor = PortfolioView(as_of_time=T, cash=5_000.0, positions={}, portfolio_value=100_000.0)
        result = sizer.size("AAA", T, make_decision(T, confidence=0.95), FakePrediction(0.15), None, poor, current_price=50.0)
        assert result.status == RiskCheckStatus.REDUCE
        assert result.reason == "cash_shortage"
        assert result.proposed_target_quantity > 0

    def test_near_zero_cash_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        poor = PortfolioView(as_of_time=T, cash=1.0, positions={}, portfolio_value=100_000.0)
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, poor, current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "sized_to_zero"


class TestExistingPosition:
    def test_hold_is_a_pass_through_with_no_new_sizing(self) -> None:
        sizer = DeterministicPositionSizer()
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        decision = make_decision(T, action=DecisionAction.HOLD)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, held, current_price=95.0)
        assert result.status == RiskCheckStatus.PASS
        assert result.reason == "no_new_sizing_for_hold"
        assert result.proposed_target_quantity == 100.0

    def test_no_trade_is_a_pass_through(self) -> None:
        sizer = DeterministicPositionSizer()
        decision = make_decision(T, action=DecisionAction.NO_TRADE)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.PASS
        assert result.reason == "no_new_sizing_for_no_trade"
        assert result.proposed_target_quantity == 0.0

    def test_buy_with_an_unexpected_existing_position_is_unknown_not_a_crash(self) -> None:
        sizer = DeterministicPositionSizer()
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        decision = make_decision(T, action=DecisionAction.BUY)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, held, current_price=95.0)
        assert result.status == RiskCheckStatus.UNKNOWN
        assert result.reason == "unexpected_existing_position_for_buy"


class TestSellAndExit:
    def test_sell_fully_exits(self) -> None:
        sizer = DeterministicPositionSizer()
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        decision = make_decision(T, action=DecisionAction.SELL)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, held, current_price=95.0)
        assert result.status == RiskCheckStatus.PASS
        assert result.reason == "full_exit"
        assert result.proposed_target_weight == 0.0
        assert result.proposed_target_quantity == 0.0

    def test_exit_fully_exits(self) -> None:
        sizer = DeterministicPositionSizer()
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        decision = make_decision(T, action=DecisionAction.EXIT)
        result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, held, current_price=95.0)
        assert result.status == RiskCheckStatus.PASS
        assert result.reason == "full_exit"


class TestMaximumPositionLimit:
    def test_sizing_never_exceeds_the_configured_max_position_weight(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.05)
        sizer = DeterministicPositionSizer(config)
        decision = make_decision(T, confidence=1.0)
        result = sizer.size("AAA", T, decision, FakePrediction(0.05), None, empty_portfolio(), current_price=50.0)
        assert result.proposed_target_weight <= config.max_position_weight + 1e-9


class TestRiskBudget:
    def test_risk_budget_exceeded_reduces_the_position(self) -> None:
        sizer = DeterministicPositionSizer()
        decision = make_decision(T, confidence=1.0)
        full = sizer.size("AAA", T, decision, FakePrediction(0.10), None, empty_portfolio(), current_price=50.0, risk_budget=1.0)
        constrained = DeterministicPositionSizer().size(
            "AAA", T, decision, FakePrediction(0.10), None, empty_portfolio(), current_price=50.0, risk_budget=0.05,
        )
        assert constrained.status == RiskCheckStatus.REDUCE
        assert constrained.reason == "risk_budget_exceeded"
        assert constrained.proposed_target_weight < full.proposed_target_weight

    def test_invalid_risk_budget_is_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0, risk_budget=0.0)
        assert result.status == RiskCheckStatus.UNKNOWN
        assert result.reason == "invalid_risk_budget"

        result2 = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0, risk_budget=1.5)
        assert result2.status == RiskCheckStatus.UNKNOWN


class TestTargetWeightHintIsNotAuthoritative:
    def test_an_oversized_hint_does_not_leak_into_the_computed_weight(self) -> None:
        sizer = DeterministicPositionSizer()
        decision_low_hint = make_decision(T, confidence=0.9, target_weight_hint=0.01)
        decision_high_hint = make_decision(T, confidence=0.9, target_weight_hint=0.99)
        r1 = sizer.size("AAA", T, decision_low_hint, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        r2 = DeterministicPositionSizer().size("AAA", T, decision_high_hint, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert r1.proposed_target_weight == r2.proposed_target_weight
        assert r2.proposed_target_weight <= PositionSizingConfig().max_position_weight + 1e-9


class TestMissingData:
    def test_missing_decision_is_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, None, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.UNKNOWN
        assert result.reason == "decision_unavailable"

    def test_missing_portfolio_state_is_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, None, current_price=50.0)
        assert result.status == RiskCheckStatus.UNKNOWN
        assert result.reason == "portfolio_state_unavailable"

    def test_missing_price_data_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=None)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "missing_price_data"


class TestInvalidNumericInput:
    def test_nan_volatility_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(float("nan")), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "invalid_volatility"

    def test_infinite_volatility_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(float("inf")), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "invalid_volatility"

    def test_negative_volatility_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(-0.10), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "invalid_volatility"

    def test_negative_price_rejects(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, empty_portfolio(), current_price=-50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "missing_price_data"

    def test_nan_portfolio_value_is_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        bad_portfolio = PortfolioView(as_of_time=T, cash=100_000.0, positions={}, portfolio_value=float("nan"))
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.15), None, bad_portfolio, current_price=50.0)
        assert result.status == RiskCheckStatus.UNKNOWN
        assert result.reason == "invalid_portfolio_value"


class TestBoundaryValues:
    def test_volatility_exactly_at_the_full_size_cutoff_rejects(self) -> None:
        config = PositionSizingConfig(max_volatility_for_full_size=0.50)
        sizer = DeterministicPositionSizer(config)
        result = sizer.size("AAA", T, make_decision(T), FakePrediction(0.50), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "volatility_exceeds_limit"

    def test_confidence_of_exactly_one_is_valid(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T, confidence=1.0), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.PASS

    def test_confidence_of_exactly_zero_sizes_to_zero_not_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        result = sizer.size("AAA", T, make_decision(T, confidence=0.0), FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert result.status == RiskCheckStatus.REJECT
        assert result.reason == "sized_to_zero"


class TestDeterministicOutput:
    def test_replay_with_the_same_inputs_is_deterministic(self) -> None:
        sizer = DeterministicPositionSizer()
        decision = make_decision(T)
        r1 = sizer.size("AAA", T, decision, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        r2 = sizer.size("AAA", T, decision, FakePrediction(0.15), None, empty_portfolio(), current_price=50.0)
        assert r1.status == r2.status
        assert r1.reason == r2.reason
        assert r1.proposed_target_weight == r2.proposed_target_weight
        assert r1.proposed_target_quantity == r2.proposed_target_quantity

    def test_never_falls_through_to_an_undeclared_status(self) -> None:
        sizer = DeterministicPositionSizer()
        for action in DecisionAction:
            decision = make_decision(T, action=action)
            portfolio = empty_portfolio() if action == DecisionAction.BUY else portfolio_holding(T, "AAA")
            result = sizer.size("AAA", T, decision, FakePrediction(0.15), None, portfolio, current_price=50.0)
            assert isinstance(result.status, RiskCheckStatus)
            assert result.reason


class TestCashSafetyRegression:
    """Regression test for the exact bug Phase 2 discovered and fixed
    via `BuyAndHoldStrategy.COST_SAFETY_MARGIN` (instruction section 11:
    "baseline이 현금을 100% 소진해 수수료를 낼 여유가 없었던 문제 ...
    다시 발생하지 않도록 regression test를 반드시 추가한다").
    `PositionSizer` must never propose a position that would spend down
    to (or past) the last unit of cash, leaving nothing for transaction
    costs."""

    def test_sizing_always_leaves_the_configured_cost_safety_margin_of_cash_unspent(self) -> None:
        config = PositionSizingConfig(max_position_weight=1.0, cost_safety_margin=0.02)
        sizer = DeterministicPositionSizer(config)
        portfolio = empty_portfolio(cash=100_000.0)
        result = sizer.size("AAA", T, make_decision(T, confidence=1.0), FakePrediction(0.10, ), None, portfolio, current_price=100.0)
        spent = result.proposed_target_quantity * 100.0
        remaining_cash_ratio = (portfolio.cash - spent) / portfolio.cash
        assert remaining_cash_ratio >= config.cost_safety_margin - 1e-9

    def test_zero_cost_safety_margin_can_spend_all_cash_but_never_more(self) -> None:
        config = PositionSizingConfig(max_position_weight=1.0, cost_safety_margin=0.0)
        sizer = DeterministicPositionSizer(config)
        portfolio = empty_portfolio(cash=100_000.0)
        result = sizer.size("AAA", T, make_decision(T, confidence=1.0), FakePrediction(0.10), None, portfolio, current_price=100.0)
        spent = result.proposed_target_quantity * 100.0
        assert spent <= portfolio.cash + 1e-6
