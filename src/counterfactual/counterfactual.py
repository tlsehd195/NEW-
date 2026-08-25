"""Counterfactual Analysis.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 3.
Phase 3's HOLD counterfactual (`trade_journal.analysis.
compute_hold_counterfactual`) is imported and reused unchanged. This
module adds the CASH alternative and the assembly/comparison helpers
around both.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from data_infra.repository import DataRepository

from trade_journal.analysis import compute_hold_counterfactual
from trade_journal.enums import DecisionAction
from trade_journal.models import AlternativeOutcome, CounterfactualRecord, TradeRecord

_SECONDS_PER_YEAR = 365.25 * 86400


def compute_cash_counterfactual(
    decision_time: datetime,
    evaluation_time: datetime,
    risk_free_rate: float = 0.0,
) -> AlternativeOutcome:
    """"What if, instead of trading, the capital had simply sat in cash
    from decision_time to evaluation_time?"

    No DataRepository call is made -- the result is a pure function of
    the two timestamps and the caller-supplied risk_free_rate. This
    system has no risk-free-rate data source anywhere; every existing
    risk_free_rate parameter (backtest.metrics.sharpe_ratio/sortino_ratio)
    already defaults to 0.0 and nothing overrides it, so 0.0 is kept as
    the default here too rather than inventing a new assumption
    (ADR-0016 point 3)."""
    if evaluation_time < decision_time:
        raise ValueError("evaluation_time must not be before decision_time")

    horizon = evaluation_time - decision_time
    hypothetical_return = risk_free_rate * (horizon.total_seconds() / _SECONDS_PER_YEAR)
    basis = "cash_baseline_zero_rate" if risk_free_rate == 0.0 else "cash_baseline_explicit_rate"
    return AlternativeOutcome(
        action="CASH", hypothetical_return=hypothetical_return, basis=basis, horizon=horizon
    )


def build_counterfactual_record(
    repository: DataRepository,
    trade: TradeRecord,
    selected_action: DecisionAction,
    decision_time: datetime,
    evaluation_time: datetime,
    *,
    risk_free_rate: float = 0.0,
    computed_at: Optional[datetime] = None,
) -> CounterfactualRecord:
    """Assembles the HOLD (Phase 3) and CASH (Phase 10) alternatives into
    a trade_journal.models.CounterfactualRecord -- the exact Phase 3
    type, unmodified (ADR-0016 point 1)."""
    hold = compute_hold_counterfactual(repository, trade.security_id, decision_time, evaluation_time)
    cash = compute_cash_counterfactual(decision_time, evaluation_time, risk_free_rate=risk_free_rate)
    return CounterfactualRecord(
        trade_id=trade.trade_id,
        selected_action=selected_action,
        alternatives=(hold, cash),
        computed_at=computed_at,
    )


def compute_counterfactual_advantage(
    trade: TradeRecord, alternative: AlternativeOutcome
) -> Optional[float]:
    """The realized advantage of the action actually selected over one
    alternative that was not taken: trade.realized_return -
    alternative.hypothetical_return. None when either side is not a real
    number yet (e.g. an unrealized/open trade) -- never estimated
    (PROJECT_MASTER_PLAN.md section 33)."""
    if trade.realized_return is None or alternative.hypothetical_return is None:
        return None
    return trade.realized_return - alternative.hypothetical_return
