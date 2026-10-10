"""Dry-run order plan for the SMA overlay (ADR-0239).

Pure arithmetic: turns a target exposure (1.0 = hold SPY, 0.0 = cash) into a
printed plan of share quantities. It imports no broker code and places
nothing; `dry_run` is always True.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OrderPlan:
    side: Optional[str]  # "BUY", "SELL", or None when no trade is needed
    total_shares: float
    estimated_notional_usd: float
    chunks: tuple[float, ...]  # share quantities, each within the per-order cap
    target_shares: float
    capital_usd: float
    price_usd: float
    note: str
    dry_run: bool = True


def build_order_plan(
    *,
    target_exposure: float,
    capital_usd: float,
    price_usd: float,
    held_shares: float,
    max_order_notional_usd: float,
    fractional: bool,
) -> OrderPlan:
    if price_usd <= 0 or capital_usd < 0 or held_shares < 0 or max_order_notional_usd <= 0:
        raise ValueError("price, caps must be positive; capital and holdings non-negative")
    if not 0.0 <= target_exposure <= 1.0:
        raise ValueError("target_exposure must be within [0, 1]")

    raw_target = target_exposure * capital_usd / price_usd
    # Round down so the plan never spends more than the target value.
    target = math.floor(raw_target * 10_000) / 10_000 if fractional else float(math.floor(raw_target))
    delta = target - held_shares
    if not fractional:
        delta = float(math.trunc(delta))
    if abs(delta) < 1e-9:
        return OrderPlan(None, 0.0, 0.0, (), target, capital_usd, price_usd, "no trade needed")

    side = "BUY" if delta > 0 else "SELL"
    total = abs(delta)
    unit = 1.0 if not fractional else 0.0001
    max_shares = max(unit, math.floor(max_order_notional_usd / price_usd / unit) * unit)
    chunks: list[float] = []
    remaining = total
    while remaining > 1e-9:
        qty = min(max_shares, remaining)
        chunks.append(round(qty, 4))
        remaining -= qty
    note = "whole shares only; leftover cash stays in the account" if not fractional else "fractional shares"
    if max_shares * price_usd > max_order_notional_usd + 1e-9:
        note += "; a single share exceeds the per-order cap"
    return OrderPlan(side, round(total, 4), round(total * price_usd, 2), tuple(chunks), target, capital_usd, price_usd, note)
