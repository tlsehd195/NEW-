"""Standalone rule-based factor score functions for Signal IC
diagnosis -- deliberately NOT full `Strategy` implementations (no
order generation, no rebalance-timing, no position sizing). Lets a
factor's raw predictive power be tested cheaply via
`signal_ic.compute_ic_series` before any full strategy is built around
it, matching the pipeline-stage separation (`DATA -> FEATURES ->
... -> SIGNAL -> ... -> PORTFOLIO CONSTRUCTION`) `docs/research/
ML-RESEARCH-PROTOCOL.md` section 11 already establishes for a future
ML signal. Reuses the exact same `trim_to_lookback`/
`annualized_volatility` building blocks the existing strategies use,
so a factor found to carry real IC here can graduate into a full
Strategy using primitives already proven correct, rather than new,
untested ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from backtest.asof import AsOfDataView
from backtest.metrics import annualized_volatility, compute_returns

from strategy_research._dates import trim_to_lookback


def low_volatility_score(
    security_id: str, as_of_time: datetime, data: AsOfDataView, *, lookback_days: int = 126,
) -> Optional[float]:
    """HYPOTHESIS -- the "low-volatility anomaly" (e.g. Ang, Hodrick,
    Xing & Zhang 2006; Baker, Bradley & Wurgler 2011): securities with
    LOWER trailing realized volatility tend to have relatively BETTER
    risk-adjusted forward returns than a naive risk-return tradeoff
    would predict. A well-documented, independently pre-existing
    candidate -- not invented in reaction to the momentum score's
    near-zero IC finding (that finding is exactly why this is worth
    testing next, but the hypothesis itself predates it by decades).

    Score is the NEGATIVE of trailing annualized volatility, so a
    higher score means lower (hypothesized more attractive) volatility
    -- matches this module's and `_momentum_score`'s convention that a
    higher score ranks a security as more attractive.

    `lookback_days` is trimmed via `trim_to_lookback` from a
    calendar-day-padded fetch, the same discipline ADR-0038 already
    applied to every other lookback-windowed score in this package --
    built correctly the first time here, not as a later fix."""
    bars = trim_to_lookback(
        data.get_bars(security_id, as_of_time - timedelta(days=int(lookback_days * 1.6)), as_of_time),
        lookback_days,
    )
    if len(bars) < 2:
        return None
    closes = [b.adjusted_close or b.close for b in bars]
    returns = compute_returns(closes)
    if len(returns) < 2:
        return None
    vol = annualized_volatility(returns)
    return -vol
