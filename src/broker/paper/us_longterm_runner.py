"""run_buy_and_hold_paper_session: the deterministic, non-polling
"runner" instruction section 15/16 asks for -- ties the existing Buy &
Hold reference baseline (ADR-0028) to `PaperTradingSession` over an
explicit, caller-supplied decision schedule.

**Never reads wall-clock time.** Every timestamp (`buy_time`, and any
future extension's decision schedule) is supplied explicitly by the
caller, exactly like every other point-in-time-safe entry point in this
project (`data_infra.provider.IngestionRunner.run`,
`backtest.total_return.build_total_return_benchmark_points`). No
`while True`/daemon loop is built here -- this function runs one
Buy & Hold allocation and returns; a future phase can wrap it in a real
scheduler if that is ever decided.

Deliberately reuses the existing Decision->Risk->Broker lineage
boundary rather than inventing a new one -- and, as of the fix below,
genuinely goes THROUGH it rather than around it.

**Fixed (external audit, 2026-09-24)**: this module used to construct a
`risk.models.RiskCheckedPosition` directly with a hardcoded
`status=PASS`, bypassing the real `risk.engine.PortfolioRiskEngine`
entirely -- every portfolio-level limit (max single-position weight,
max sector weight, max gross exposure, minimum cash ratio, max order
notional, max drawdown) went silently unchecked for this strategy, the
only registered `PaperStrategyKind` where that was true.

**Why this module still never imports `risk.engine`/`risk.sizing`/
`decision.*` itself**: `tests/broker/test_broker_boundary.py` enforces,
for real, exactly the boundary this module's own docstring already
claimed to respect -- the Broker layer never calls Decision/
PositionSizer/RiskEngine directly (instruction section 20). The actual
fix therefore takes the shape that boundary requires: this module
computes the SAME deterministic equal-weight target it always has
(there is no predictive signal to size against, so fabricating a
`decision.models.DecisionOutput`/`predict.models.PredictionOutput` to
route through `risk.sizing.PositionSizer` would trade one kind of
fabrication for another), then hands `(security_id, as_of_time,
target_weight, target_quantity, portfolio_state)` to a caller-supplied
`risk_check` callback and uses whatever `risk.models.RiskCheckedPosition`
it returns -- this module never constructs a `PositionSizingResult`
or references `DecisionAction` itself, so it stays exactly as ignorant
of the Decision/Risk layer's own types as `broker.validation.
build_validated_order` already is. The real caller (`orchestration.
paper_runner.build_buy_and_hold_risk_check`) builds the real
`risk.models.PositionSizingResult` (with `decision_action=DecisionAction.
BUY`) and calls the real `risk.engine.PortfolioRiskEngine.assess` --
orchestration already legitimately imports both, the same as `run_cycle`
already does via its own sizer. Then calls the real, unmodified
`broker.validation.build_validated_order` and
`broker.paper.session.PaperTradingSession.submit` -- no new order
construction path.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Sequence

from backtest.portfolio import PortfolioView, PositionView

from broker.models import BrokerOrderResponse
from broker.paper.market_data import PaperMarketDataSource
from broker.paper.models import PaperFillRecord
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.repository import BrokerRequestRepository, BrokerResponseRepository
from broker.validation import build_validated_order

from risk.enums import RiskCheckStatus
from risk.models import RiskCheckedPosition

from trade_journal.enums import TradeProvenance

RiskCheckCallback = Callable[[str, datetime, float, float, PortfolioView], RiskCheckedPosition]


@dataclass(frozen=True)
class BuyAndHoldOrderOutcome:
    security_id: str
    quantity: float
    response: BrokerOrderResponse
    fills: tuple[PaperFillRecord, ...]


@dataclass(frozen=True)
class BuyAndHoldRunResult:
    buy_time: datetime
    orders: tuple[BuyAndHoldOrderOutcome, ...]
    skipped_symbols: tuple[str, ...] = field(default_factory=tuple)
    skip_reasons: dict = field(default_factory=dict)


_COST_SAFETY_MARGIN = 0.02  # mirrors risk.config.PositionSizingConfig.cost_safety_margin's own reasoning


def run_buy_and_hold_paper_session(
    security_ids: Sequence[str],
    market_data: PaperMarketDataSource,
    session: PaperTradingSession,
    *,
    buy_time: datetime,
    configuration_version: str,
    risk_check: RiskCheckCallback,
    lot_size: float = 1.0,
    request_repository: Optional[BrokerRequestRepository] = None,
    response_repository: Optional[BrokerResponseRepository] = None,
) -> BuyAndHoldRunResult:
    """Allocates the session's current cash equally across
    `security_ids` at `buy_time`, one MARKET BUY order per symbol,
    floored to a whole `lot_size` multiple of shares -- then never
    trades again (true buy & hold, matching ADR-0028's low-turnover
    baseline selection). A symbol with no reference bar available at
    `buy_time` (`market_data.get_reference_bar` returns `None`) is
    skipped, never a fabricated fill at a guessed price -- recorded in
    `skipped_symbols`/`skip_reasons`, not silently dropped.

    **`risk_check` is required, not optional (external audit fix,
    2026-09-24)**: called as `risk_check(security_id, buy_time,
    target_weight, target_quantity, portfolio_state)` for the equal-
    weight target computed for each symbol -- `orchestration.
    paper_runner.build_buy_and_hold_risk_check` builds the real one
    (submits a real `risk.models.PositionSizingResult` to a real
    `risk.engine.PortfolioRiskEngine`, the same one `orchestration.
    paper_runner.run_cycle` uses), which can genuinely REJECT the
    target (skipped, same as any other skip reason) or REDUCE it (the
    returned `RiskCheckedPosition.final_target_quantity` is used,
    re-floored to `lot_size`) -- portfolio-level limits (max single-
    position weight, max sector weight, max gross exposure, minimum
    cash ratio, max order notional) now apply to this strategy exactly
    like every other one, where before they silently did not. This
    module takes the callback rather than a `risk.engine.
    PortfolioRiskEngine` directly, and never references `risk.engine`/
    `risk.sizing`/`decision.*` itself, to respect `tests/broker/
    test_broker_boundary.py`'s real, enforced "Broker never calls
    Decision/PositionSizer/RiskEngine directly" invariant -- see this
    module's own docstring above. The running portfolio state fed to
    `risk_check` is built locally from each symbol ALREADY allocated
    earlier in this same call (this function's own bar-priced
    `average_cost`/`market_value` -- no new data source), since this
    strategy's very first allocation never has pre-existing positions
    to look up elsewhere.

    `request_repository`/`response_repository` are optional (default
    `None`, preserving the original `session.submit()`-only behavior
    when omitted) -- when supplied, each order is submitted through
    `broker.pipeline.submit_validated_order` instead, so the standard
    `broker_requests`/`broker_responses` audit trail
    `monitoring.collectors.collect_broker` reads is populated exactly
    once per real order, with no separate/duplicate submission needed
    to also produce it."""
    account = session.adapter.get_account(as_of=buy_time)
    if not account.available or account.cash is None:
        return BuyAndHoldRunResult(
            buy_time=buy_time, orders=(),
            skipped_symbols=tuple(security_ids),
            skip_reasons={sid: "account_unavailable" for sid in security_ids},
        )

    orders: list[BuyAndHoldOrderOutcome] = []
    skipped: list[str] = []
    skip_reasons: dict = {}
    remaining = len(security_ids)
    # ADR-0154: tracked locally, never re-read from `session.adapter.
    # get_account` inside the loop. Before ADR-0154, `submit_order`
    # filled synchronously, so a re-query here already reflected every
    # order submitted earlier in this same loop, and dividing the
    # actual remaining cash by the actual remaining symbol count at
    # each step kept the allocation honestly equal-weight net of real
    # transaction costs. Now that fills are deferred (T+1) -- a fill
    # only lands on a LATER `advance_simulation` call, never
    # synchronously at `submit_order` -- `get_account` would hand every
    # symbol in this loop the SAME undiminished cash, since none of
    # this call's own orders has actually debited anything yet. This
    # local tracker reserves each submitted order's estimated notional
    # (quantity * reference price, before commission/slippage -- the
    # same reference price `usable_cash` below was already computed
    # from, not a new fabricated figure) so the next symbol's split is
    # still computed net of it, preserving the original equal-weight
    # allocation intent exactly.
    available_cash = account.cash
    # Running positions for symbols already allocated earlier in this
    # same call -- the real risk engine's exposure/concentration/sector
    # checks need to see them, and this strategy's positions table is
    # otherwise empty (its very first allocation, by construction: the
    # caller only invokes this once, before any order exists).
    positions_so_far: dict[str, PositionView] = {}

    for security_id in security_ids:
        cash_for_this_symbol = available_cash / remaining
        remaining -= 1

        bar = market_data.get_reference_bar(security_id, as_of=buy_time)
        if bar is None or bar.close <= 0:
            skipped.append(security_id)
            skip_reasons[security_id] = "no_reference_price_available"
            continue

        usable_cash = cash_for_this_symbol * (1.0 - _COST_SAFETY_MARGIN)  # leaves room for commission/spread
        target_quantity = math.floor((usable_cash / bar.close) / lot_size) * lot_size
        if target_quantity <= 0:
            skipped.append(security_id)
            skip_reasons[security_id] = "insufficient_cash_for_one_lot"
            continue

        portfolio_value = available_cash + sum(p.market_value for p in positions_so_far.values())
        portfolio_state = PortfolioView(
            as_of_time=buy_time, cash=available_cash, positions=dict(positions_so_far), portfolio_value=portfolio_value,
        )
        target_weight = (target_quantity * bar.close) / portfolio_value if portfolio_value > 0 else 0.0
        risk_checked = risk_check(security_id, buy_time, target_weight, target_quantity, portfolio_state)
        if risk_checked.status not in (RiskCheckStatus.PASS, RiskCheckStatus.REDUCE):
            skipped.append(security_id)
            skip_reasons[security_id] = f"risk_check_rejected:{risk_checked.reason}"
            continue

        # The engine works in continuous weight space -- its own
        # (possibly clamped) final_target_quantity is re-floored to a
        # whole lot_size multiple, the same discipline the naive
        # pre-check target_quantity above already applied.
        quantity = math.floor((risk_checked.final_target_quantity or 0.0) / lot_size) * lot_size
        if quantity <= 0:
            skipped.append(security_id)
            skip_reasons[security_id] = f"sized_to_zero_after_risk_limit:{risk_checked.reason}"
            continue
        # build_validated_order reads final_target_quantity straight off
        # the RiskCheckedPosition it is given -- must be the re-floored
        # quantity above, not the engine's own possibly-fractional clamp.
        risk_checked = dataclasses.replace(risk_checked, final_target_quantity=quantity)

        validation = build_validated_order(risk_checked, current_quantity=0.0, configuration_version=configuration_version)
        if validation.validated_order is None:
            skipped.append(security_id)
            skip_reasons[security_id] = f"order_validation_rejected:{validation.reason}"
            continue

        if request_repository is not None or response_repository is not None:
            response = submit_validated_order(
                session.adapter, validation.validated_order, execution_mode="PAPER", requested_at=buy_time,
                configuration_version=configuration_version,
                request_repository=request_repository, response_repository=response_repository,
            )
            fills = session.capture(validation.validated_order.client_order_id, as_of=buy_time)
        else:
            response, fills = session.submit(validation.validated_order, requested_at=buy_time)
        orders.append(BuyAndHoldOrderOutcome(security_id=security_id, quantity=quantity, response=response, fills=fills))
        available_cash -= quantity * bar.close
        positions_so_far[security_id] = PositionView(
            security_id=security_id, quantity=quantity, average_cost=bar.close, market_value=quantity * bar.close,
        )

    return BuyAndHoldRunResult(buy_time=buy_time, orders=tuple(orders), skipped_symbols=tuple(skipped), skip_reasons=skip_reasons)
