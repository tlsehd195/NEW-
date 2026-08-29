"""Per-security P&L contribution / concentration analysis.

Added following the master instruction's "Symbol Contribution" /
"Leave-One-Out / Concentration Check" requirement: a backtest's
aggregate `PerformanceReport` (cumulative return, Sharpe, etc.) cannot
by itself answer "did a handful of outsized movers (e.g. NVDA, AVGO,
TSLA) drive this whole result, or was it broadly distributed across
the universe" -- a real question for judging how much a strategy's
apparent edge would generalize to a different symbol mix.

**Scope, stated precisely**: this is a CONTRIBUTION decomposition of a
single already-run backtest's actual closed trades and final open
positions (cheap -- no re-running anything). It is NOT a true
leave-one-out re-backtest (excluding each security and re-running the
full walk-forward to see how results change), which would require N
additional full backtest runs and is a materially more expensive
capability -- deliberately not built here. The master instruction's own
wording ("leave-one-symbol-out sensitivity 가능 여부") treats that as an
open question, not a hard requirement; this module answers the cheaper,
still-informative "where did the P&L actually come from" question
directly from data the backtest already produced.

No new dependency (pure stdlib), no strategy/signal-generation code
touched -- reads `PortfolioAccounting`'s already-existing
`closed_trades`/`positions`, same objects `backtest.metrics` already
reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Optional, Sequence

from backtest.portfolio import PortfolioAccounting

if TYPE_CHECKING:
    from backtest.fills import Fill


@dataclass(frozen=True)
class SecurityContribution:
    security_id: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    # None (not 0.0) when the portfolio's total P&L is exactly zero --
    # a share of zero is undefined, not honestly reportable as "0%".
    share_of_total_pnl: Optional[float]


@dataclass(frozen=True)
class ConcentrationReport:
    """`contributions` is sorted descending by `total_pnl`. Every
    Optional field here is `None` precisely when the underlying ratio
    is mathematically undefined (no trades, or all P&L exactly zero)
    -- never silently defaulted to 0.0, which would misreport "no
    concentration" when the real answer is "not computable"."""

    contributions: tuple
    total_pnl: float
    num_securities: int
    top_contributor: Optional[SecurityContribution]
    bottom_contributor: Optional[SecurityContribution]
    top_1_share_of_positive_pnl: Optional[float]
    top_3_share_of_positive_pnl: Optional[float]
    # Herfindahl-Hirschman Index over ABSOLUTE P&L shares (|pnl_i| / sum|pnl_j|),
    # not signed shares -- a large winner offset by a large loser is
    # still a concentrated result, not a diversified one, and signed
    # shares would let those cancel out and hide that. Ranges (1/N, 1.0];
    # 1/N (the equal_weight_share below) means perfectly even
    # distribution across N securities, 1.0 means one security alone
    # produced all the absolute P&L.
    herfindahl_index: Optional[float]
    # 1/N -- the "no concentration" reference point a single security's
    # share can be compared against.
    equal_weight_share: Optional[float]


def compute_contribution_report(
    portfolio: "PortfolioAccounting", final_prices: Mapping[str, float]
) -> ConcentrationReport:
    """`final_prices` value final open positions for unrealized P&L
    (same convention as `PortfolioAccounting.unrealized_pnl`) -- a
    security missing from `final_prices` falls back to its own
    average cost (zero unrealized P&L assumed), matching that method's
    existing behavior exactly."""
    realized_by_security: dict = {}
    for trade in portfolio.closed_trades:
        realized_by_security[trade.security_id] = (
            realized_by_security.get(trade.security_id, 0.0) + trade.realized_pnl
        )

    unrealized_by_security: dict = {}
    for security_id, pos in portfolio.positions.items():
        if pos.quantity == 0:
            continue
        price = final_prices.get(security_id, pos.average_cost)
        unrealized_by_security[security_id] = (price - pos.average_cost) * pos.quantity

    all_security_ids = sorted(set(realized_by_security) | set(unrealized_by_security))
    total_pnl = sum(realized_by_security.values()) + sum(unrealized_by_security.values())

    contributions = []
    for security_id in all_security_ids:
        realized = realized_by_security.get(security_id, 0.0)
        unrealized = unrealized_by_security.get(security_id, 0.0)
        total = realized + unrealized
        share = (total / total_pnl) if total_pnl != 0 else None
        contributions.append(
            SecurityContribution(
                security_id=security_id,
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                total_pnl=total,
                share_of_total_pnl=share,
            )
        )
    contributions.sort(key=lambda c: c.total_pnl, reverse=True)
    contributions_t = tuple(contributions)

    num_securities = len(all_security_ids)
    top_contributor = contributions_t[0] if contributions_t else None
    bottom_contributor = contributions_t[-1] if contributions_t else None

    positive = [c for c in contributions_t if c.total_pnl > 0]
    sum_positive = sum(c.total_pnl for c in positive)
    if sum_positive > 0 and positive:
        top_1_share = positive[0].total_pnl / sum_positive
        top_3_share = sum(c.total_pnl for c in positive[:3]) / sum_positive
    else:
        top_1_share = None
        top_3_share = None

    sum_abs = sum(abs(c.total_pnl) for c in contributions_t)
    if sum_abs > 0:
        hhi = sum((abs(c.total_pnl) / sum_abs) ** 2 for c in contributions_t)
    else:
        hhi = None

    equal_weight_share = (1.0 / num_securities) if num_securities > 0 else None

    return ConcentrationReport(
        contributions=contributions_t,
        total_pnl=total_pnl,
        num_securities=num_securities,
        top_contributor=top_contributor,
        bottom_contributor=bottom_contributor,
        top_1_share_of_positive_pnl=top_1_share,
        top_3_share_of_positive_pnl=top_3_share,
        herfindahl_index=hhi,
        equal_weight_share=equal_weight_share,
    )


def compute_contribution_report_from_fills(
    fills: Sequence["Fill"], initial_capital: float, final_prices: Mapping[str, float]
) -> ConcentrationReport:
    """Convenience entry point for a caller that only has a
    `BacktestResult` (which exposes `.fills` but not the internal
    `PortfolioAccounting` `BacktestEngine.run()` built and discarded) --
    replays `fills` through a fresh `PortfolioAccounting` via the exact
    same `apply_fill` bookkeeping the engine itself used, which
    deterministically reconstructs the same `closed_trades`/`positions`
    state, then delegates to `compute_contribution_report`. Does not
    touch `backtest.engine` itself."""
    portfolio = PortfolioAccounting(initial_capital)
    for fill in fills:
        portfolio.apply_fill(fill)
    return compute_contribution_report(portfolio, final_prices)
