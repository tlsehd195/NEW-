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
boundary rather than inventing a new one: this module constructs a
`risk.models.RiskCheckedPosition` directly (the same "the reference
strategy's already-risk-checked decision" pattern
`tests/integration/test_paper_trading_real_market_data.py` and
`tests/broker/broker_helpers.py` already establish for test/reference
scenarios), then calls the real, unmodified
`broker.validation.build_validated_order` and
`broker.paper.session.PaperTradingSession.submit` -- no new order
construction path, no bypass of existing validation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from broker.models import BrokerOrderResponse
from broker.paper.market_data import PaperMarketDataSource
from broker.paper.models import PaperFillRecord
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.repository import BrokerRequestRepository, BrokerResponseRepository
from broker.validation import build_validated_order

from data_infra.versioning import compute_data_version

from risk.enums import RiskCheckStatus
from risk.models import RiskCheckedPosition

from trade_journal.enums import TradeProvenance


def _synthetic_id(prefix: str, *, buy_time: datetime, security_id: str) -> str:
    """These risk/sizing/decision ids are never persisted to any table
    of their own (this function's whole "lineage" for a buy_and_hold
    order is synthetic, folded only into `compute_client_order_id`'s
    hash) -- so there is no real sequence to seed a restart-safe
    counter from. A per-call `-000001`-style counter (the previous
    implementation) collided across calls: every invocation of this
    function re-minted the SAME id for a given symbol's position in
    `security_ids`, so a second call sharing the same `buy_time` (a
    legitimate retry with no persisted order yet, or two similarly
    configured buy_and_hold strategies run in the same process)
    produced the exact same `client_order_id`, and the paper adapter's
    own idempotent-submit logic then silently treated the second,
    genuinely-intended buy as a replay of the first. Deriving the id
    from `(buy_time, security_id)` instead is naturally unique per
    real economic event and needs no counter/seeding at all."""
    digest = compute_data_version({"buy_time": buy_time.isoformat(), "security_id": security_id})
    return f"{prefix}-{digest[:12]}"


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

    for security_id in security_ids:
        # Re-fetched fresh before each symbol (never a single up-front
        # split): commission/spread on each fill consumes slightly more
        # cash than quantity * price, so a fixed initial_cash / N share
        # computed once would overspend by the time later symbols are
        # reached. Dividing the *actual remaining* cash by the *actual
        # remaining* symbol count at each step keeps the allocation
        # honestly equal-weight net of real transaction costs, never
        # producing a fabricated "should have been enough" rejection.
        current_cash = session.adapter.get_account(as_of=buy_time).cash or 0.0
        cash_for_this_symbol = current_cash / remaining
        remaining -= 1

        bar = market_data.get_reference_bar(security_id, as_of=buy_time)
        if bar is None or bar.close <= 0:
            skipped.append(security_id)
            skip_reasons[security_id] = "no_reference_price_available"
            continue

        usable_cash = cash_for_this_symbol * (1.0 - _COST_SAFETY_MARGIN)  # leaves room for commission/spread
        quantity = math.floor((usable_cash / bar.close) / lot_size) * lot_size
        if quantity <= 0:
            skipped.append(security_id)
            skip_reasons[security_id] = "insufficient_cash_for_one_lot"
            continue

        risk_checked = RiskCheckedPosition(
            risk_id=_synthetic_id("RISK-BAH", buy_time=buy_time, security_id=security_id),
            security_id=security_id, as_of_time=buy_time,
            status=RiskCheckStatus.PASS, reason="buy_and_hold_initial_allocation", breached_limits=(),
            final_target_weight=None, final_target_quantity=quantity,
            sizing_id=_synthetic_id("SIZE-BAH", buy_time=buy_time, security_id=security_id),
            decision_id=_synthetic_id("DEC-BAH", buy_time=buy_time, security_id=security_id), prediction_id=None,
            risk_state=None, risk_version="buy_and_hold_reference_runner_v1",
            feature_version="buy_and_hold_reference_runner_v1", provenance=TradeProvenance.PAPER_TRADING,
        )
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

    return BuyAndHoldRunResult(buy_time=buy_time, orders=tuple(orders), skipped_symbols=tuple(skipped), skip_reasons=skip_reasons)
