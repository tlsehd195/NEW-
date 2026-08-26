"""Category: Risk Policy Completeness Test (Phase 17 -- Production
Safety Review, Section 9). Pins the classification in
docs/operations/LIVE-RISK-POLICY.md against the actual field values in
code, so a future silent change to any of these defaults is caught as
a test failure rather than only a stale document."""

from __future__ import annotations

from broker.live.config import LiveTradingConfig
from broker.live.kill_switch import KillSwitchTriggerContext
from risk.config import PositionSizingConfig, RiskConfig


class TestUndefinedPolicyItemsDefaultToNotEnforced:
    """#1, #6, #7 -- None means "not enforced," never a silently
    invented number."""

    def test_daily_loss_limit_is_undefined_by_default(self) -> None:
        assert LiveTradingConfig().max_daily_loss is None

    def test_turnover_limit_is_undefined_by_default(self) -> None:
        assert RiskConfig().max_turnover is None

    def test_order_frequency_limit_is_undefined_by_default(self) -> None:
        assert LiveTradingConfig().max_order_frequency_per_hour is None


class TestInheritedPolicyItemsMatchPhase8Defaults:
    """#2, #3, #4, #9 -- these values exist and are enforced, but were
    set by Phase 8 for backtesting/paper trading, not decided fresh for
    Live capital. This test only pins that they still exist and are
    still the same Phase 8 values -- it makes no claim they are correct
    for real money."""

    def test_max_drawdown_is_the_phase_8_default(self) -> None:
        assert RiskConfig().max_drawdown == 0.20

    def test_max_position_weight_is_the_phase_8_default(self) -> None:
        assert RiskConfig().max_position_weight == 0.10
        assert PositionSizingConfig().max_position_weight == 0.10

    def test_max_gross_exposure_is_the_phase_8_default(self) -> None:
        assert RiskConfig().max_gross_exposure == 1.0

    def test_minimum_cash_ratio_is_the_phase_8_default(self) -> None:
        assert RiskConfig().minimum_cash_ratio == 0.05

    def test_liquidity_limit_enforcement_flag_is_on_by_default(self) -> None:
        assert RiskConfig().enforce_liquidity_limit is True


class TestBlockingPolicyItemsHaveNoField:
    """#5, #10, #11 -- structurally confirmed absent, not merely unset.
    A future addition of any of these fields should prompt updating
    docs/operations/LIVE-RISK-POLICY.md, which this test's failure
    would flag."""

    def test_risk_config_has_no_max_order_notional_field(self) -> None:
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(RiskConfig)}
        assert "max_order_notional" not in field_names

    def test_live_trading_config_has_no_max_consecutive_failures_field(self) -> None:
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(LiveTradingConfig)}
        assert "max_consecutive_failures" not in field_names

    def test_risk_config_sector_weight_is_unenforceable_placeholder(self) -> None:
        assert RiskConfig().max_sector_weight is None


class TestDataHealthTriggerIsNowWired:
    """#13 -- this phase's own addition; confirms the field exists with
    a safe default so no pre-Phase-17 caller silently breaks."""

    def test_data_health_field_exists_and_defaults_to_none(self) -> None:
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(KillSwitchTriggerContext)}
        assert "data_health" in field_names
        default = next(f for f in dataclasses.fields(KillSwitchTriggerContext) if f.name == "data_health").default
        assert default is None
