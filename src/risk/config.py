"""PositionSizingConfig / RiskConfig: every threshold `PositionSizer` and
`PortfolioRiskEngine` use, kept out of code -- the same discipline
`DecisionConfig` (Phase 7), `RegimeConfig` (Phase 5), and
`PredictionConfig` (Phase 6) already established. No default value here
is claimed to be financially optimal (instruction section 6, 22: "특정
숫자가 투자 전략상 최적이라고 주장하지 않는다") -- these are round,
illustrative starting points, exactly like `DecisionConfig`'s own
defaults.

See docs/specifications/PHASE-8-position-sizing-and-risk.md sections 5,
6, 7, 12.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class PositionSizingConfig:
    version: str = "position_sizing_config_v1"

    # -- the single-position hard cap PositionSizer itself will never
    # propose above, independent of (and a first line of defense before)
    # PortfolioRiskEngine's own, separately configured max_position_weight --
    max_position_weight: float = 0.10

    # -- inverse-volatility scaling: expected_volatility at or above
    # reference_volatility scales the proposed weight down; at or above
    # max_volatility_for_full_size the position is sized to zero outright --
    reference_volatility: float = 0.20
    max_volatility_for_full_size: float = 0.80
    min_volatility_scale: float = 0.10  # floor on the inverse-vol multiplier -- never scales below this

    # -- a LOW liquidity regime state (Phase 5's LIQUIDITY axis, when
    # supplied) halves the proposed weight; UNKNOWN liquidity rejects
    # outright (instruction section 9: "required liquidity information
    # unknown" is a fail-closed trigger) --
    low_liquidity_scale: float = 0.50

    # -- reserves a small buffer of cash so a fully-sized position never
    # leaves zero room for transaction costs -- directly mirrors
    # backtest.strategy.BuyAndHoldStrategy.COST_SAFETY_MARGIN, the fix for
    # the exact cash-exhaustion problem instruction section 11 calls out
    # by name; see tests/risk/test_sizing.py::TestCashSafetyRegression --
    cost_safety_margin: float = 0.02

    lot_size: float = 1.0  # quantity is floored to a multiple of this

    def __post_init__(self) -> None:
        if not 0.0 < self.max_position_weight <= 1.0:
            raise ValueError("max_position_weight must be in (0, 1]")
        if self.reference_volatility <= 0:
            raise ValueError("reference_volatility must be positive")
        if self.max_volatility_for_full_size <= 0:
            raise ValueError("max_volatility_for_full_size must be positive")
        if not 0.0 < self.min_volatility_scale <= 1.0:
            raise ValueError("min_volatility_scale must be in (0, 1]")
        if not 0.0 < self.low_liquidity_scale <= 1.0:
            raise ValueError("low_liquidity_scale must be in (0, 1]")
        if not 0.0 <= self.cost_safety_margin < 1.0:
            raise ValueError("cost_safety_margin must be in [0, 1)")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


@dataclass(frozen=True)
class RiskConfig:
    version: str = "risk_config_v1"

    # -- single_position_limit: an independent, portfolio-level hard cap
    # re-checked here regardless of what PositionSizer already applied
    # (defense in depth -- PortfolioRiskEngine is the final authority) --
    max_position_weight: float = 0.10

    # -- gross_exposure_limit / concentration_limit --
    max_gross_exposure: float = 1.0
    concentration_limit: float = 0.25

    # -- max_order_notional: an absolute per-order dollar/currency-unit
    # cap, independent of every weight-based limit above (ADR-0062
    # session continued) -- closes LIVE-RISK-POLICY.md item #10, which
    # previously had no field anywhere in risk.*/broker.live.* (only
    # weight-based limits and quantity validation existed). `None`
    # means "not enforced," same as every other Optional limit here --
    # a human must explicitly set a value for it to have any effect --
    max_order_notional: Optional[float] = None

    # -- cash_minimum: the portfolio must always retain at least this
    # fraction of portfolio_value as cash after any new BUY --
    minimum_cash_ratio: float = 0.05

    # -- drawdown_limit / portfolio_volatility_limit / turnover_limit:
    # `None` means "not enforced" (no configured limit, distinct from
    # "enforced but the data to check it is currently unavailable" --
    # see docs/decisions/ADR-0014 for the distinction this phase draws
    # between the two) --
    max_drawdown: Optional[float] = 0.20
    max_portfolio_volatility: Optional[float] = 0.30
    max_turnover: Optional[float] = None

    # -- liquidity_limit: enforced whenever a liquidity_state is supplied
    # to PortfolioRiskEngine.assess(); if the caller omits it entirely,
    # the check is simply not run for that call (distinct from the
    # regime axis itself reporting UNKNOWN, which always rejects) --
    enforce_liquidity_limit: bool = True

    # -- sector_limit: enforcement path now exists (ADR-0062,
    # PortfolioRiskEngine.assess's opt-in sector_by_security parameter --
    # SecurityMaster itself still has no sector field, so the caller
    # must supply the mapping per call, e.g. sourced from data_infra.
    # universe's own real sector data, ADR-0058). None here still means
    # "not enforced" -- a human must explicitly set a value, same as
    # max_turnover's own precedent --
    max_sector_weight: Optional[float] = None
    # -- factor_limit: still intentionally left unconfigured.
    # No factor-exposure data source exists anywhere in this project
    # (instruction section 12: "현재 데이터가 지원하지 않는 constraint는
    # 억지로 구현하지 않는다") -- kept here as a documented extension
    # point, unchanged by ADR-0062 --
    max_factor_exposure: Optional[float] = None

    # -- reentry_cooldown: found comparing this project against an
    # external repository (dragon1086/prism-insight), Session 36
    # continued. `None` means "not enforced," same convention as
    # max_turnover/max_sector_weight -- a human must explicitly set a
    # value for this to have any effect. Unlike liquidity_state/
    # sector_by_security's own opt-in parameters, "this security has no
    # recorded recent exit" is the OVERWHELMINGLY common, legitimate
    # case (a fresh entry, or a long-held position), not a data gap --
    # so `PortfolioRiskEngine.assess`'s own `last_exit_time_by_security`
    # parameter mirrors `liquidity_state`'s "enforced only when the
    # caller supplies it for this call, simply skipped otherwise"
    # pattern, NOT `sector_by_security`'s fail-closed-on-missing-entry
    # pattern -- deliberately, since fail-closed here would reject every
    # first-time BUY whenever a caller has not wired up exit history,
    # which is not what a reentry-cooldown limit is meant to do. See
    # ADR-0093 and LIVE-RISK-POLICY.md item #16 for the full account,
    # including the still-unratified proposed number --
    reentry_cooldown_days: Optional[int] = None

    # -- minimum number of historical portfolio-value points required
    # before drawdown/portfolio_volatility are computed at all; below
    # this, those fields are honestly None/UNKNOWN rather than computed
    # from too little data --
    min_history_for_volatility: int = 5

    def __post_init__(self) -> None:
        if not 0.0 < self.max_position_weight <= 1.0:
            raise ValueError("max_position_weight must be in (0, 1]")
        if not 0.0 < self.max_gross_exposure:
            raise ValueError("max_gross_exposure must be positive")
        if not 0.0 < self.concentration_limit <= 1.0:
            raise ValueError("concentration_limit must be in (0, 1]")
        if self.max_order_notional is not None and self.max_order_notional <= 0:
            raise ValueError("max_order_notional must be positive when configured")
        if not 0.0 <= self.minimum_cash_ratio < 1.0:
            raise ValueError("minimum_cash_ratio must be in [0, 1)")
        if self.max_drawdown is not None and not 0.0 < self.max_drawdown <= 1.0:
            raise ValueError("max_drawdown must be in (0, 1] when configured")
        if self.max_portfolio_volatility is not None and self.max_portfolio_volatility <= 0:
            raise ValueError("max_portfolio_volatility must be positive when configured")
        if self.max_turnover is not None and self.max_turnover <= 0:
            raise ValueError("max_turnover must be positive when configured")
        if self.reentry_cooldown_days is not None and self.reentry_cooldown_days <= 0:
            raise ValueError("reentry_cooldown_days must be positive when configured")
        if self.min_history_for_volatility < 2:
            raise ValueError("min_history_for_volatility must be >= 2")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_POSITION_SIZING_CONFIG = PositionSizingConfig()
DEFAULT_RISK_CONFIG = RiskConfig()
