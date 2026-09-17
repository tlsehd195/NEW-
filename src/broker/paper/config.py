"""PaperTradingConfig: every threshold Paper Trading uses, kept out of
code -- the same discipline `broker.config.BrokerConfig` (Phase 13)
already established. `environment` is fixed to the literal string
`"paper"` and validated in `__post_init__` -- a structural guard so no
`PaperTradingConfig` can ever silently represent a live configuration
(instruction section 19, 21).

See docs/specifications/PHASE-15-paper-trading.md section 5.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from backtest.costs import VolumeScaledSlippageModel, TransactionCostModel

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class PaperTradingConfig:
    version: str = "paper_trading_config_v1"
    broker_id: str = "paper-broker"
    environment: str = "paper"  # structurally the only allowed value -- see __post_init__

    initial_cash: float = 1_000_000.0

    # -- Phase 2's own TransactionCostModel/FixedBpsSlippageModel fields,
    # reused rather than a new cost model class (instruction section 9/10).
    commission_fixed_per_trade: float = 1.0
    commission_per_share: float = 0.005
    spread_bps: float = 2.0
    slippage_bps: float = 5.0
    # External review (Session 38 continued): `backtest.costs.
    # VolumeScaledSlippageModel` already existed but `slippage_model()`
    # below never used it -- every Paper Trading fill got the SAME flat
    # slippage regardless of how large a bite it took out of that bar's
    # own liquidity, silently underpricing large/illiquid fills relative
    # to `max_participation`'s own 10%-of-volume cap. `slippage_bps`
    # above is reused as the impact model's flat `base_bps` (same
    # meaning at zero participation, so an existing `slippage_bps`
    # override still means the same thing); this field is the EXTRA bps
    # charged at 100% participation, matching `VolumeScaledSlippageModel`'s
    # own default.
    slippage_impact_coefficient_bps: float = 100.0

    max_participation: float = 0.10  # same default as backtest.fills.FillSimulator
    partial_fill_enabled: bool = True

    # External review (Session 38 continued): before ADR-0137 wired
    # `advance_simulation` into `run_cycle` at all, a still-open
    # (PENDING/PARTIAL_FILLED) order simply never retried. Retrying is
    # now unconditional, but nothing yet stops an order that STILL can't
    # fill (e.g. its security permanently drops below the participation
    # cap's liquidity, or leaves the universe) from sitting open forever
    # -- a real "zombie order" risk. `None` (the default) preserves the
    # exact pre-existing behavior: no TTL, an order stays open
    # indefinitely, matching every existing caller's expectations. A
    # caller that wants auto-cancellation sets a real day count; this is
    # opt-in because "how long is too long" is a real risk-policy
    # decision this config should not make silently on a caller's behalf.
    pending_order_ttl_days: Optional[int] = None

    # None | "rejected" | "timeout" | "auth" | "rate_limit" | "malformed" |
    # "unavailable" | "unknown_status" -- mirrors broker.mock.MockBrokerAdapter's
    # own `failure_mode` vocabulary (Phase 13), extended with the additional
    # modes instruction section 16 asks for.
    failure_mode: Optional[str] = None

    allow_short: bool = False
    maximum_order_quantity: Optional[float] = None
    maximum_notional: Optional[float] = None

    # Reserved -- no randomness is used by the current deterministic fill
    # model (participation-capped, no probabilistic component); kept so a
    # future probabilistic fill/failure model has an explicit, auditable
    # seed to depend on rather than system random state (instruction
    # section 17).
    seed: Optional[int] = None

    def __post_init__(self) -> None:
        if self.environment != "paper":
            raise ValueError(
                f"PaperTradingConfig.environment must be exactly 'paper', got {self.environment!r} "
                "-- a Paper Trading configuration can never represent a live environment"
            )
        if not self.broker_id:
            raise ValueError("PaperTradingConfig.broker_id must not be empty")
        if self.initial_cash < 0:
            raise ValueError("PaperTradingConfig.initial_cash must not be negative")
        if self.commission_fixed_per_trade < 0 or self.commission_per_share < 0:
            raise ValueError("PaperTradingConfig commission fields must not be negative")
        if self.spread_bps < 0 or self.slippage_bps < 0:
            raise ValueError("PaperTradingConfig.spread_bps/slippage_bps must not be negative")
        if self.slippage_impact_coefficient_bps < 0:
            raise ValueError("PaperTradingConfig.slippage_impact_coefficient_bps must not be negative")
        if not 0.0 < self.max_participation <= 1.0:
            raise ValueError("PaperTradingConfig.max_participation must be in (0, 1]")
        if self.maximum_order_quantity is not None and self.maximum_order_quantity <= 0:
            raise ValueError("PaperTradingConfig.maximum_order_quantity must be positive if set")
        if self.maximum_notional is not None and self.maximum_notional <= 0:
            raise ValueError("PaperTradingConfig.maximum_notional must be positive if set")
        if self.pending_order_ttl_days is not None and self.pending_order_ttl_days <= 0:
            raise ValueError("PaperTradingConfig.pending_order_ttl_days must be positive if set")
        allowed_failure_modes = {
            None, "rejected", "timeout", "auth", "rate_limit", "malformed", "unavailable", "unknown_status",
        }
        if self.failure_mode not in allowed_failure_modes:
            raise ValueError(f"PaperTradingConfig.failure_mode must be one of {allowed_failure_modes}")

    def transaction_cost_model(self) -> TransactionCostModel:
        return TransactionCostModel(
            fixed_per_trade=self.commission_fixed_per_trade, per_share=self.commission_per_share,
            spread_bps=self.spread_bps,
        )

    def slippage_model(self) -> VolumeScaledSlippageModel:
        return VolumeScaledSlippageModel(
            base_bps=self.slippage_bps, impact_coefficient_bps=self.slippage_impact_coefficient_bps,
        )

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_PAPER_TRADING_CONFIG = PaperTradingConfig()
