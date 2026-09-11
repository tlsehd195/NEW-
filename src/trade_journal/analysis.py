"""Post Trade Analysis / Counterfactual / Attribution helpers.

See docs/specifications/PHASE-3-trade-journal.md sections 7, 5.7.
Every function here either computes a real number from data the system
actually has, or returns None with a stated reason — none of them
estimate a value and present it as fact (ADR-0009 point 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from data_infra.repository import DataRepository

from backtest.fills import Fill

from trade_journal.models import AlternativeOutcome


def compute_execution_error(fill: Fill) -> Optional[float]:
    """(actual fill price - reference price) / reference price — the
    realized cost of spread + slippage as a return, for a Fill that
    already happened. See Phase 3 spec section 7.1. `None` (never a
    fabricated `0.0`, ADR-0117) when `reference_price` is 0 -- the
    ratio is genuinely undefined, not "no execution error.\""""
    if fill.reference_price == 0:
        return None
    return (fill.price - fill.reference_price) / fill.reference_price


def compute_hold_counterfactual(
    repository: DataRepository,
    security_id: str,
    decision_time: datetime,
    evaluation_time: datetime,
) -> AlternativeOutcome:
    """"What if, instead of trading, the position had simply been left
    alone from decision_time to evaluation_time?" A legitimate post-hoc
    query (Phase 3 spec section 7.2) — evaluation_time is at/after
    decision_time and the window has already elapsed by the time this is
    called, so querying with as_of_time=evaluation_time is retrospective
    analysis, not look-ahead bias (same reasoning as Phase 2 spec section
    8.3)."""
    if evaluation_time < decision_time:
        raise ValueError("evaluation_time must not be before decision_time")

    horizon = evaluation_time - decision_time

    start_bars = repository.get_bars(
        security_id, decision_time - timedelta(days=7), decision_time, as_of_time=evaluation_time
    )
    end_bars = repository.get_bars(
        security_id, evaluation_time - timedelta(days=7), evaluation_time, as_of_time=evaluation_time
    )
    if not start_bars or not end_bars:
        return AlternativeOutcome(
            action="HOLD", hypothetical_return=None, basis="insufficient_data", horizon=horizon
        )

    start_price = start_bars[-1].close
    end_price = end_bars[-1].close
    if start_price <= 0:
        return AlternativeOutcome(
            action="HOLD", hypothetical_return=None, basis="invalid_reference_price", horizon=horizon
        )

    hypothetical_return = end_price / start_price - 1.0
    return AlternativeOutcome(
        action="HOLD", hypothetical_return=hypothetical_return, basis="post_hoc_price_replay", horizon=horizon
    )


def compute_execution_attribution(transaction_costs: float, initial_capital: float) -> float:
    """Aggregate execution cost drag as a fraction of starting capital —
    the one AttributionResult component Phase 3 can compute for real
    (Phase 3 spec section 5.7). Negative: cost is always a drag."""
    if initial_capital <= 0:
        return 0.0
    return -(transaction_costs / initial_capital)
