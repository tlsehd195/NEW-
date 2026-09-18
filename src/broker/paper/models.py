"""Paper Trading's own persisted types. Deliberately thin wrappers
around types Phase 2/13 already established
(`broker.models.ValidatedOrder`, `backtest.fills.Fill`) rather than a
parallel order/fill representation -- instruction section 28: "Paper
전용 shortcut으로 core trading logic을 복제하지 않는다."

See docs/specifications/PHASE-15-paper-trading.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from broker.enums import BrokerOrderStatus
from broker.models import ValidatedOrder

from backtest.fills import Fill

from data_infra.models import CorporateAction


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class PaperOrderRecord:
    """The ground truth of one accepted-or-rejected order submission.
    `initial_status` is the outcome of `PaperBrokerAdapter.submit_order`'s
    own logic *before* any `advance_simulation` call -- current status
    for an open order is always re-derived from `initial_status` plus
    the order's accumulated fills, never stored redundantly."""

    validated_order: ValidatedOrder
    requested_at: datetime
    initial_status: BrokerOrderStatus
    rejection_reason: Optional[str]
    configuration_version: str

    def __post_init__(self) -> None:
        _require_aware("PaperOrderRecord.requested_at", self.requested_at)
        if self.initial_status == BrokerOrderStatus.REJECTED and not self.rejection_reason:
            raise ValueError("PaperOrderRecord.initial_status == REJECTED requires a rejection_reason")
        if self.initial_status != BrokerOrderStatus.REJECTED and self.rejection_reason is not None:
            raise ValueError("PaperOrderRecord.rejection_reason must be None unless initial_status == REJECTED")


@dataclass(frozen=True)
class PaperFillRecord:
    """One simulated fill -- wraps `backtest.fills.Fill` (Phase 2)
    directly rather than re-deriving an equivalent shape, plus the
    identity/lineage fields Paper Trading's own audit trail needs."""

    fill_id: str
    client_order_id: str
    fill: Fill
    configuration_version: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.fill_id or not self.client_order_id:
            raise ValueError("PaperFillRecord requires non-empty fill_id/client_order_id")
        _require_aware("PaperFillRecord.recorded_at", self.recorded_at)


@dataclass(frozen=True)
class PaperAppliedCorporateActionRecord:
    """One corporate action already applied to a Paper Trading account's
    `backtest.portfolio.PortfolioAccounting` -- wraps the original
    `data_infra.models.CorporateAction` directly (same reasoning as
    `PaperFillRecord` wrapping `backtest.fills.Fill`: the original object
    already carries every field a replay needs -- security_id,
    action_type, details, provenance -- so re-deriving an equivalent
    shape would only risk drifting out of sync with it), plus the real
    `applied_at` timestamp this record was actually applied at during a
    live cycle (the `as_of_time` `PaperTradingSession.apply_corporate_
    actions` was called with). `applied_at` is what a restart's merge-
    sort-by-time replay (`PaperTradingSession.restore`) orders this
    record against `PaperFillRecord.fill.execution_time`, and what a
    replayed `apply()` call passes back through as its own `as_of_time`
    argument -- so `backtest.portfolio.CashFlowRecord.as_of_time` (for a
    dividend) stays the real historical moment rather than collapsing to
    a restore-time batch timestamp.

    `source_record_id` (== `action.provenance.source_record_id`) is the
    dedup key -- the SAME field `backtest.corporate_actions.
    CorporateActionApplier` already uses for its own in-process
    idempotency set, kept consistent here for the persisted ledger."""

    action: CorporateAction
    applied_at: datetime

    def __post_init__(self) -> None:
        _require_aware("PaperAppliedCorporateActionRecord.applied_at", self.applied_at)

    @property
    def source_record_id(self) -> str:
        return self.action.provenance.source_record_id
