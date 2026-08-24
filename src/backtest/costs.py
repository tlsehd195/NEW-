"""Transaction Cost & Slippage Model.

See docs/specifications/PHASE-2-backtesting.md section 7 and ADR-0007.

Invariant enforced throughout this module: spread and slippage only ever
move the effective price against the trader. No function here can return
a price more favorable than the reference price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backtest.enums import OrderSide


@dataclass(frozen=True)
class TransactionCostModel:
    """Commission + spread. Defaults are non-zero on purpose (Phase 2
    spec section 7 / ADR-0007 point 5) — a zero-cost run must be an
    explicit override, never the fallback a casual run lands on."""

    fixed_per_trade: float = 1.0
    per_share: float = 0.005
    spread_bps: float = 2.0

    def commission(self, quantity: float) -> float:
        if quantity <= 0:
            return 0.0
        return self.fixed_per_trade + self.per_share * quantity

    def apply_spread(self, reference_price: float, side: OrderSide) -> float:
        half_spread_fraction = (self.spread_bps / 2.0) / 10_000
        adjustment = reference_price * half_spread_fraction
        if side == OrderSide.BUY:
            return reference_price + adjustment  # pay slightly more
        return reference_price - adjustment  # receive slightly less


class SlippageModel(Protocol):
    def adjust(self, price: float, quantity: float, side: OrderSide, bar_volume: float) -> float:
        """Returns `price` adjusted further against the trader. `price`
        is the post-spread reference price; `bar_volume` is the execution
        bar's traded volume (Phase 2 spec section 6.2)."""
        ...


@dataclass(frozen=True)
class FixedBpsSlippageModel:
    bps: float = 5.0

    def adjust(self, price: float, quantity: float, side: OrderSide, bar_volume: float) -> float:
        adjustment = price * (self.bps / 10_000)
        return price + adjustment if side == OrderSide.BUY else price - adjustment


@dataclass(frozen=True)
class VolumeScaledSlippageModel:
    """Adds an impact term proportional to the order's participation rate
    (quantity filled / bar volume) on top of a flat base. A simple linear
    proxy for market impact — not a calibrated Almgren & Chriss model.
    Demonstrates the SlippageModel extension point (ADR-0007); a future,
    calibrated impact model can implement the same Protocol without any
    caller change."""

    base_bps: float = 5.0
    impact_coefficient_bps: float = 100.0  # extra bps at 100% participation

    def adjust(self, price: float, quantity: float, side: OrderSide, bar_volume: float) -> float:
        participation = quantity / bar_volume if bar_volume > 0 else 0.0
        total_bps = self.base_bps + self.impact_coefficient_bps * participation
        adjustment = price * (total_bps / 10_000)
        return price + adjustment if side == OrderSide.BUY else price - adjustment


DEFAULT_TRANSACTION_COST_MODEL = TransactionCostModel()
DEFAULT_SLIPPAGE_MODEL = FixedBpsSlippageModel()

# For diagnostic use only (Phase 2 spec section 7 point 5) — isolating
# strategy-signal quality from execution-cost effects. Never the default
# BacktestConfig falls back to.
ZERO_TRANSACTION_COST_MODEL = TransactionCostModel(fixed_per_trade=0.0, per_share=0.0, spread_bps=0.0)
ZERO_SLIPPAGE_MODEL = FixedBpsSlippageModel(bps=0.0)
