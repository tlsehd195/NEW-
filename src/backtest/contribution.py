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

from backtest.corporate_actions import CorporateActionApplier
from backtest.portfolio import PortfolioAccounting

if TYPE_CHECKING:
    from backtest.fills import Fill
    from data_infra.models import CorporateAction


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
    fills: Sequence["Fill"],
    initial_capital: float,
    final_prices: Mapping[str, float],
    corporate_actions: Sequence["CorporateAction"],
) -> ConcentrationReport:
    """Convenience entry point for a caller that only has a
    `BacktestResult` (which exposes `.fills` but not the internal
    `PortfolioAccounting` `BacktestEngine.run()` built and discarded) --
    replays `fills` through a fresh `PortfolioAccounting` via the exact
    same `apply_fill` bookkeeping the engine itself used, which
    deterministically reconstructs the same `closed_trades`/`positions`
    state, then delegates to `compute_contribution_report`.

    **`corporate_actions` is required, not optional (an external audit,
    2026-09-24, caught the bug this parameter fixes)**: `fills` alone
    are NOT enough to reconstruct the engine's real portfolio state --
    `BacktestEngine.run()` also applies SPLIT/DIVIDEND events via
    `CorporateActionApplier` between fills, which changes a position's
    `quantity`/`average_cost` without producing a `Fill`. Replaying only
    `fills` silently desynchronizes from the engine's real state the
    moment a split occurs mid-holding: e.g. buy 100sh@10, a 2:1 split
    (engine: 200sh@5), then sell 200sh@6 -- the engine's real
    `realized_pnl` is `+199.0`, but replaying fills alone (pre-fix)
    computed `-801.0` for that trade (`(6-10)*200`, plus running the
    position negative since only 100sh were ever "bought" in the
    fill-only replay) -- a sign-flipped, wrong-by-1000 result, silently
    reported as the real concentration/contribution breakdown. Passing
    `()` when the caller has independently confirmed no corporate
    action occurred across every `fills` security's holding period is
    fine; passing it by accident/omission is exactly the bug this
    signature change makes impossible to do unnoticed.

    Corporate actions are applied in chronological order, interleaved
    with `fills` by comparing each action's `effective_time or
    event_time` against each fill's `execution_time` -- the same
    "corporate action before the next portfolio event" ordering
    `BacktestEngine.run()` itself uses (`backtest.corporate_actions.
    CorporateActionApplier`). Actions with neither `effective_time` nor
    `event_time` set are skipped (cannot be ordered; `CorporateAction`
    guarantees `available_time` but that is a disclosure timestamp, not
    a real-world effective date -- silently guessing one would risk
    applying a split on the wrong side of a fill). Does not touch
    `backtest.engine` itself."""
    portfolio = PortfolioAccounting(initial_capital)
    applier = CorporateActionApplier()

    def _action_time(action: "CorporateAction"):
        return action.effective_time or action.event_time

    orderable_actions = [a for a in corporate_actions if _action_time(a) is not None]
    orderable_actions.sort(key=_action_time)
    fills_sorted = sorted(fills, key=lambda f: f.execution_time)

    action_idx = 0
    for fill in fills_sorted:
        while action_idx < len(orderable_actions) and _action_time(orderable_actions[action_idx]) <= fill.execution_time:
            action = orderable_actions[action_idx]
            applier.apply([action], portfolio, max(action.available_time, _action_time(action)))
            action_idx += 1
        portfolio.apply_fill(fill)
    while action_idx < len(orderable_actions):
        action = orderable_actions[action_idx]
        applier.apply([action], portfolio, max(action.available_time, _action_time(action)))
        action_idx += 1

    return compute_contribution_report(portfolio, final_prices)
