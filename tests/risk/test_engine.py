"""Category: Unit Test -- PortfolioRiskEngine (Phase 8 spec sections 7,
8, 9, 10).

Covers: normal portfolio, position concentration, cash violation,
drawdown violation, exposure violation, turnover violation, liquidity
violation, unknown portfolio state, unknown risk input, invalid
configuration, NaN, infinite values.
"""

from __future__ import annotations

import pytest

from risk_helpers import FakePrediction, empty_portfolio, make_decision, portfolio_holding, utc

from backtest.portfolio import PortfolioView

from risk.config import PositionSizingConfig, RiskConfig
from risk.enums import RiskCheckStatus
from risk.engine import DeterministicPortfolioRiskEngine
from risk.sizing import DeterministicPositionSizer

from trade_journal.enums import DecisionAction

T = utc(2024, 6, 1)


def _sized_buy(*, confidence: float = 0.9, volatility: float = 0.10, price: float = 50.0, portfolio: PortfolioView = None, config: PositionSizingConfig = None):
    sizer = DeterministicPositionSizer(config or PositionSizingConfig())
    decision = make_decision(T, confidence=confidence)
    return sizer.size("AAA", T, decision, FakePrediction(volatility), None, portfolio or empty_portfolio(), current_price=price)


class TestNormalPortfolio:
    def test_normal_buy_passes_with_no_breached_limits(self) -> None:
        engine = DeterministicPortfolioRiskEngine()
        sizing = _sized_buy()
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=[100_000.0] * 6)
        assert checked.status == RiskCheckStatus.PASS
        assert checked.breached_limits == ()
        assert checked.final_target_weight == sizing.proposed_target_weight
        assert checked.risk_state is not None
        assert checked.risk_state.portfolio_value == 100_000.0

    def test_hold_and_no_trade_are_never_blocked_by_risk_limits(self) -> None:
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=0.01))  # a limit that would obviously block a BUY
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        sizer = DeterministicPositionSizer()
        hold_decision = make_decision(T, action=DecisionAction.HOLD)
        sizing = sizer.size("AAA", T, hold_decision, FakePrediction(0.10), None, held, current_price=95.0)
        checked = engine.assess("AAA", T, sizing, held, current_price=95.0, value_history=None)
        assert checked.status == RiskCheckStatus.PASS
        assert checked.reason == "no_new_risk_limit_applicable"

    def test_sell_full_exit_is_never_blocked(self) -> None:
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=0.01))
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        sizer = DeterministicPositionSizer()
        sell_decision = make_decision(T, action=DecisionAction.SELL)
        sizing = sizer.size("AAA", T, sell_decision, FakePrediction(0.10), None, held, current_price=95.0)
        checked = engine.assess("AAA", T, sizing, held, current_price=95.0, value_history=None)
        assert checked.status == RiskCheckStatus.PASS


class TestConcentrationLimit:
    def test_concentration_limit_clamps_a_large_proposed_weight(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.90)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, config=config)
        engine = DeterministicPortfolioRiskEngine(
            RiskConfig(max_position_weight=1.0, concentration_limit=0.20, max_gross_exposure=1.0, max_drawdown=None, max_portfolio_volatility=None)
        )
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0)
        assert checked.status == RiskCheckStatus.REDUCE
        assert "concentration" in checked.breached_limits
        assert checked.final_target_weight <= 0.20 + 1e-9


class TestCashMinimumViolation:
    def test_cash_minimum_breach_reduces_the_position(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.90, cost_safety_margin=0.0)
        # tight cash: portfolio only has 20% cash, minimum_cash_ratio requires 15% retained
        portfolio = PortfolioView(as_of_time=T, cash=20_000.0, positions={}, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=portfolio, config=config)
        engine = DeterministicPortfolioRiskEngine(RiskConfig(minimum_cash_ratio=0.15, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, portfolio, current_price=50.0)
        assert checked.status in (RiskCheckStatus.REDUCE, RiskCheckStatus.REJECT)
        assert "cash_minimum" in checked.breached_limits

    def test_cash_already_below_minimum_rejects_outright(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.90, cost_safety_margin=0.0)
        portfolio = PortfolioView(as_of_time=T, cash=1_000.0, positions={}, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=portfolio, config=config)
        engine = DeterministicPortfolioRiskEngine(RiskConfig(minimum_cash_ratio=0.50, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, portfolio, current_price=50.0)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.final_target_weight == 0.0


class TestDrawdownViolation:
    def test_drawdown_beyond_limit_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=0.10))
        history = [100_000.0, 95_000.0, 80_000.0, 70_000.0, 60_000.0, 55_000.0]
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=history)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "drawdown_limit_breached"

    def test_drawdown_unknown_when_configured_but_no_history_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=0.10))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=None)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "drawdown_unknown"

    def test_drawdown_not_configured_skips_the_check_entirely(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=None)
        assert checked.status == RiskCheckStatus.PASS


class TestExposureViolation:
    def test_gross_exposure_limit_reduces_new_buy(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.90)
        held = portfolio_holding(T, "BBB", quantity=1000.0, average_cost=90.0, cash=1_000.0, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=held, config=config)
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_gross_exposure=0.95, concentration_limit=1.0, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, held, current_price=50.0)
        assert checked.status in (RiskCheckStatus.REDUCE, RiskCheckStatus.REJECT)
        if checked.status == RiskCheckStatus.REDUCE:
            assert "gross_exposure" in checked.breached_limits

    def test_gross_exposure_already_at_cap_rejects_outright(self) -> None:
        held = portfolio_holding(T, "BBB", quantity=1000.0, average_cost=100.0, cash=50_000.0, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=held, config=PositionSizingConfig(max_position_weight=0.90))
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_position_weight=1.0, max_gross_exposure=1.0, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, held, current_price=50.0)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "gross_exposure_limit_breached"


class TestMaxOrderNotional:
    """LIVE-RISK-POLICY.md item #10 -- an absolute dollar cap,
    independent of every weight-based limit."""

    def test_notional_beyond_cap_clamps_the_position(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.90)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, config=config)
        engine = DeterministicPortfolioRiskEngine(
            RiskConfig(max_position_weight=1.0, concentration_limit=1.0, max_order_notional=5_000.0, max_drawdown=None, max_portfolio_volatility=None)
        )
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0)
        assert checked.status == RiskCheckStatus.REDUCE
        assert "max_order_notional" in checked.breached_limits
        assert checked.final_target_weight * 100_000.0 <= 5_000.0 + 1e-6

    def test_notional_within_cap_is_not_affected(self) -> None:
        config = PositionSizingConfig(max_position_weight=0.05)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, config=config)
        engine = DeterministicPortfolioRiskEngine(
            RiskConfig(max_order_notional=90_000.0, max_drawdown=None, max_portfolio_volatility=None)
        )
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0)
        assert "max_order_notional" not in checked.breached_limits

    def test_not_configured_skips_the_check(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_order_notional=None, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0)
        assert "max_order_notional" not in checked.breached_limits


class TestTurnoverViolation:
    def test_turnover_beyond_limit_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_turnover=0.50, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, turnover=0.90)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "turnover_limit_breached"

    def test_turnover_unknown_when_configured_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_turnover=0.50, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, turnover=None)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "turnover_unknown"

    def test_turnover_not_configured_skips_the_check(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_turnover=None, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, turnover=None)
        assert checked.status == RiskCheckStatus.PASS


class TestSectorLimit:
    """ADR-0062: sector_by_security is caller-supplied and opt-in --
    SecurityMaster itself still has no sector field. Same fail-closed-
    when-configured pattern TestTurnoverViolation already established."""

    def test_sector_limit_reduces_a_new_buy_that_would_exceed_it(self) -> None:
        held = portfolio_holding(T, "BBB", quantity=500.0, average_cost=100.0, cash=50_000.0, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=held, config=PositionSizingConfig(max_position_weight=0.90))
        engine = DeterministicPortfolioRiskEngine(
            RiskConfig(
                max_sector_weight=0.60, max_position_weight=1.0, max_gross_exposure=1.0, concentration_limit=1.0,
                minimum_cash_ratio=0.0, max_drawdown=None, max_portfolio_volatility=None,
            )
        )
        checked = engine.assess("AAA", T, sizing, held, current_price=50.0, sector_by_security={"AAA": "Tech", "BBB": "Tech"})
        assert checked.status in (RiskCheckStatus.REDUCE, RiskCheckStatus.REJECT)
        assert "sector_limit" in checked.breached_limits

    def test_sector_already_at_cap_rejects_outright(self) -> None:
        held = portfolio_holding(T, "BBB", quantity=1000.0, average_cost=100.0, cash=50_000.0, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=held, config=PositionSizingConfig(max_position_weight=0.90))
        engine = DeterministicPortfolioRiskEngine(
            RiskConfig(
                max_sector_weight=1.0, max_position_weight=1.0, max_gross_exposure=2.0, concentration_limit=1.0,
                minimum_cash_ratio=0.0, max_drawdown=None, max_portfolio_volatility=None,
            )
        )
        checked = engine.assess("AAA", T, sizing, held, current_price=50.0, sector_by_security={"AAA": "Tech", "BBB": "Tech"})
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "sector_limit_breached"

    def test_sector_unknown_when_configured_but_no_mapping_supplied_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_sector_weight=0.50, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, sector_by_security=None)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "sector_unknown"

    def test_sector_unknown_when_this_security_missing_from_the_mapping_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_sector_weight=0.50, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, sector_by_security={"BBB": "Tech"})
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "sector_unknown"

    def test_sector_not_configured_skips_the_check_even_without_a_mapping(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_sector_weight=None, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, sector_by_security=None)
        assert checked.status == RiskCheckStatus.PASS

    def test_sector_exposure_is_populated_on_risk_state_only_when_a_mapping_is_supplied(self) -> None:
        held = portfolio_holding(T, "BBB", quantity=500.0, average_cost=100.0, cash=50_000.0, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=held, config=PositionSizingConfig(max_position_weight=0.90))
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=None, max_portfolio_volatility=None))
        without_mapping = engine.assess("AAA", T, sizing, held, current_price=50.0)
        assert without_mapping.risk_state.sector_exposure is None
        with_mapping = engine.assess("AAA", T, sizing, held, current_price=50.0, sector_by_security={"BBB": "Tech"})
        assert with_mapping.risk_state.sector_exposure == {"Tech": pytest.approx(0.5)}

    def test_a_security_absent_from_the_mapping_is_excluded_from_every_sector_total(self) -> None:
        held = portfolio_holding(T, "BBB", quantity=500.0, average_cost=100.0, cash=50_000.0, portfolio_value=100_000.0)
        sizing = _sized_buy(confidence=1.0, volatility=0.05, portfolio=held, config=PositionSizingConfig(max_position_weight=0.90))
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, held, current_price=50.0, sector_by_security={})
        assert checked.risk_state.sector_exposure == {}


class TestLiquidityViolation:
    def test_low_liquidity_state_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, liquidity_state="LOW")
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "liquidity_limit_breached"

    def test_unknown_liquidity_state_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, liquidity_state="UNKNOWN")
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "liquidity_unknown"

    def test_omitted_liquidity_state_is_not_gated(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, liquidity_state=None)
        assert checked.status == RiskCheckStatus.PASS

    def test_liquidity_enforcement_can_be_disabled(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(enforce_liquidity_limit=False, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, liquidity_state="LOW")
        assert checked.status == RiskCheckStatus.PASS


class TestReentryCooldown:
    """Session 36 continued -- found comparing this project against an
    external repository (dragon1086/prism-insight). `last_exit_time_by_
    security` is caller-supplied and opt-in, mirroring `liquidity_state`
    (enforced only when the caller supplies it for THIS call, simply
    skipped otherwise) rather than `sector_by_security` (fail-closed
    when configured but the mapping/entry is missing) -- deliberately,
    since "this security has no recorded recent exit" is the ordinary
    case (a fresh entry), not a data gap. See RiskConfig.
    reentry_cooldown_days's own docstring."""

    def test_a_recent_exit_within_the_cooldown_window_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 29)},  # 3 days before T (2024-06-01)
        )
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "reentry_cooldown_breached"
        assert "reentry_cooldown" in checked.breached_limits

    def test_an_exit_exactly_at_the_cooldown_boundary_is_no_longer_blocked(self) -> None:
        """`days_since_exit < reentry_cooldown_days` is a strict `<` --
        `reentry_cooldown_days=5` means "wait AT LEAST 5 days," so
        exactly 5 days since exit has already cleared the cooldown
        (PASS), while one day short of it (4 days) still rejects."""
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))

        at_boundary = engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 27)},  # exactly 5 days before T
        )
        assert at_boundary.status == RiskCheckStatus.PASS

        just_inside = engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 28)},  # 4 days before T -- still within cooldown
        )
        assert just_inside.status == RiskCheckStatus.REJECT
        assert just_inside.reason == "reentry_cooldown_breached"

    def test_an_exit_past_the_cooldown_window_does_not_reject(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 20)},  # well past 5 days before T
        )
        assert checked.status == RiskCheckStatus.PASS

    def test_a_security_absent_from_the_mapping_is_not_gated(self) -> None:
        """The ordinary case: this security was never exited (or the
        caller has no record of it) -- must PASS, not fail closed, since
        that is not the same as "cooldown data is unavailable" the way a
        missing sector entry is."""
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"BBB": utc(2024, 5, 30)},
        )
        assert checked.status == RiskCheckStatus.PASS

    def test_omitted_mapping_entirely_is_not_gated(self) -> None:
        """Mirrors `test_omitted_liquidity_state_is_not_gated` -- a
        caller that has not wired up exit-history tracking at all sees
        no change in behavior, even with reentry_cooldown_days set."""
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, last_exit_time_by_security=None)
        assert checked.status == RiskCheckStatus.PASS

    def test_not_configured_skips_the_check_even_with_a_recent_exit_supplied(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=None, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess(
            "AAA", T, sizing, empty_portfolio(), current_price=50.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 31)},
        )
        assert checked.status == RiskCheckStatus.PASS

    def test_hold_and_sell_are_never_blocked_by_the_cooldown(self) -> None:
        held = portfolio_holding(T, "AAA", quantity=100.0, average_cost=90.0)
        sizer = DeterministicPositionSizer()
        hold_decision = make_decision(T, action=DecisionAction.HOLD)
        sizing = sizer.size("AAA", T, hold_decision, FakePrediction(0.10), None, held, current_price=95.0)
        engine = DeterministicPortfolioRiskEngine(RiskConfig(reentry_cooldown_days=5, max_drawdown=None, max_portfolio_volatility=None))
        checked = engine.assess(
            "AAA", T, sizing, held, current_price=95.0,
            last_exit_time_by_security={"AAA": utc(2024, 5, 31)},
        )
        assert checked.status == RiskCheckStatus.PASS
        assert checked.reason == "no_new_risk_limit_applicable"


class TestUnknownPortfolioState:
    def test_missing_portfolio_state_is_unknown(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine()
        checked = engine.assess("AAA", T, sizing, None, current_price=50.0)
        assert checked.status == RiskCheckStatus.UNKNOWN
        assert checked.reason == "portfolio_state_unavailable"
        assert checked.risk_state is None


class TestUnknownRiskInput:
    def test_missing_sizing_result_is_unknown(self) -> None:
        engine = DeterministicPortfolioRiskEngine()
        checked = engine.assess("AAA", T, None, empty_portfolio(), current_price=50.0)
        assert checked.status == RiskCheckStatus.UNKNOWN
        assert checked.reason == "sizing_result_unavailable"
        assert checked.risk_state is not None  # still computable from portfolio_state alone

    def test_upstream_unknown_sizing_propagates_as_unknown(self) -> None:
        sizer = DeterministicPositionSizer()
        sizing = sizer.size("AAA", T, None, FakePrediction(0.10), None, empty_portfolio(), current_price=50.0)
        engine = DeterministicPortfolioRiskEngine()
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0)
        assert checked.status == RiskCheckStatus.UNKNOWN

    def test_upstream_reject_propagates_as_reject(self) -> None:
        sizer = DeterministicPositionSizer()
        sizing = sizer.size("AAA", T, make_decision(T), FakePrediction(0.95), None, empty_portfolio(), current_price=50.0)
        assert sizing.status == RiskCheckStatus.REJECT
        engine = DeterministicPortfolioRiskEngine()
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == sizing.reason


class TestInvalidConfiguration:
    def test_position_sizing_config_rejects_out_of_range_max_weight(self) -> None:
        with pytest.raises(ValueError):
            PositionSizingConfig(max_position_weight=1.5)
        with pytest.raises(ValueError):
            PositionSizingConfig(max_position_weight=0.0)

    def test_risk_config_rejects_out_of_range_minimum_cash_ratio(self) -> None:
        with pytest.raises(ValueError):
            RiskConfig(minimum_cash_ratio=1.0)
        with pytest.raises(ValueError):
            RiskConfig(minimum_cash_ratio=-0.1)

    def test_risk_config_rejects_invalid_drawdown_limit(self) -> None:
        with pytest.raises(ValueError):
            RiskConfig(max_drawdown=1.5)

    def test_risk_config_rejects_too_small_min_history(self) -> None:
        with pytest.raises(ValueError):
            RiskConfig(min_history_for_volatility=1)

    def test_risk_config_rejects_non_positive_reentry_cooldown_days(self) -> None:
        with pytest.raises(ValueError):
            RiskConfig(reentry_cooldown_days=0)
        with pytest.raises(ValueError):
            RiskConfig(reentry_cooldown_days=-1)


class TestNaNAndInfiniteValues:
    def test_nan_portfolio_value_is_unknown(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine()
        bad_portfolio = PortfolioView(as_of_time=T, cash=100_000.0, positions={}, portfolio_value=float("nan"))
        checked = engine.assess("AAA", T, sizing, bad_portfolio, current_price=50.0)
        assert checked.status == RiskCheckStatus.UNKNOWN
        assert checked.reason == "invalid_portfolio_value"

    def test_infinite_cash_is_unknown(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine()
        bad_portfolio = PortfolioView(as_of_time=T, cash=float("inf"), positions={}, portfolio_value=100_000.0)
        checked = engine.assess("AAA", T, sizing, bad_portfolio, current_price=50.0)
        assert checked.status == RiskCheckStatus.UNKNOWN
        assert checked.reason == "invalid_portfolio_value"


class TestPortfolioVolatilityViolation:
    def test_high_volatility_history_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_portfolio_volatility=0.05, max_drawdown=None))
        # a wildly swinging value series -> high annualized volatility
        history = [100_000.0, 130_000.0, 90_000.0, 140_000.0, 80_000.0, 150_000.0]
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=history)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "portfolio_volatility_limit_breached"

    def test_portfolio_volatility_unknown_when_configured_but_no_history_rejects(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine(RiskConfig(max_portfolio_volatility=0.05, max_drawdown=None))
        checked = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=None)
        assert checked.status == RiskCheckStatus.REJECT
        assert checked.reason == "portfolio_volatility_unknown"


class TestDeterministicOutput:
    def test_replay_with_the_same_inputs_is_deterministic(self) -> None:
        sizing = _sized_buy()
        engine = DeterministicPortfolioRiskEngine()
        c1 = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=[100_000.0] * 6)
        c2 = engine.assess("AAA", T, sizing, empty_portfolio(), current_price=50.0, value_history=[100_000.0] * 6)
        assert c1.status == c2.status
        assert c1.reason == c2.reason
        assert c1.final_target_weight == c2.final_target_weight
