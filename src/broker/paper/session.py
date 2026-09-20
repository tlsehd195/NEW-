"""PaperTradingSession: the orchestration layer that wraps a
`PaperBrokerAdapter` call with persistence (mirrors
`broker.pipeline.submit_validated_order`'s "call the adapter, persist
what happened" separation, Phase 13) and can rebuild an adapter's full
in-memory state from repositories after a restart (instruction section
17, 27).

The adapter itself never persists anything -- `PaperTradingSession` is
the only place `broker.paper.*` writes to a repository, so restart
safety lives here rather than inside the deterministic simulation core.

See docs/specifications/PHASE-15-paper-trading.md section 9, 14.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from broker.models import BrokerOrderResponse, OrderStatusObservation, ValidatedOrder
from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.config import PaperTradingConfig
from broker.paper.market_data import PaperMarketDataSource
from broker.paper.models import PaperAppliedCorporateActionRecord, PaperFillRecord, PaperOrderRecord
from broker.paper.repository import (
    InMemoryPaperCorporateActionRepository,
    InMemoryPaperFillRepository,
    InMemoryPaperOrderRepository,
    PaperCorporateActionRepository,
    PaperFillRepository,
    PaperOrderRepository,
)
from broker.repository import InMemoryOrderStatusEventRepository, OrderStatusEventRepository

from data_infra.models import CorporateAction


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value


@dataclass(frozen=True)
class AccountSummary:
    """A plain, read-only snapshot for callers (Trade Journal bridging,
    ad hoc Monitoring observation) that do not need the full adapter --
    never persisted itself, always re-derived on demand from the
    adapter's own `get_account`/`get_positions`."""

    as_of_time: datetime
    cash: float
    positions: dict  # security_id -> BrokerPosition


class PaperTradingSession:
    def __init__(
        self,
        config: PaperTradingConfig,
        market_data_source: PaperMarketDataSource,
        *,
        order_repository: Optional[PaperOrderRepository] = None,
        fill_repository: Optional[PaperFillRepository] = None,
        status_repository: Optional[OrderStatusEventRepository] = None,
        corporate_action_repository: Optional[PaperCorporateActionRepository] = None,
    ) -> None:
        self.config = config
        self.adapter = PaperBrokerAdapter(config, market_data_source)
        self._order_repository = order_repository or InMemoryPaperOrderRepository()
        self._fill_repository = fill_repository or InMemoryPaperFillRepository()
        self._status_repository = status_repository or InMemoryOrderStatusEventRepository()
        self._corporate_action_repository = corporate_action_repository or InMemoryPaperCorporateActionRepository()
        self._fill_record_ids = _IdAllocator("PAPERFILLREC")

    def _persist_new_fills(self, *, recorded_at: datetime) -> tuple[PaperFillRecord, ...]:
        persisted = []
        for client_order_id, fill_id, fill in self.adapter.pop_new_fills():
            record = PaperFillRecord(
                fill_id=fill_id, client_order_id=client_order_id, fill=fill,
                configuration_version=self.config.configuration_version(), recorded_at=recorded_at,
            )
            self._fill_repository.record(record)
            persisted.append(record)
        return tuple(persisted)

    def capture(self, client_order_id: str, *, as_of: datetime) -> tuple[PaperFillRecord, ...]:
        """Persists whatever `broker.paper.*`-specific state the adapter
        currently holds for `client_order_id` -- the order record (if
        new), its latest status, and any fills generated since the last
        `capture()`/`submit()`/`advance()` call. Exists separately from
        `submit()` so a caller that drives the adapter through
        `broker.pipeline.submit_validated_order` directly (to also get
        the generic `broker_requests`/`broker_responses` audit trail,
        Phase 13) can still sync Paper's own richer state afterward,
        without this session re-submitting the order itself."""
        order_record = self.adapter.get_order_record(client_order_id)
        if order_record is not None:
            self._order_repository.record(order_record)

        status = self.adapter.get_order_status(client_order_id, as_of=as_of)
        self._status_repository.record(status)

        return self._persist_new_fills(recorded_at=as_of)

    def submit(self, order: ValidatedOrder, *, requested_at: datetime) -> tuple[BrokerOrderResponse, tuple[PaperFillRecord, ...]]:
        response = self.adapter.submit_order(order, requested_at=requested_at)
        fills = self.capture(order.client_order_id, as_of=requested_at)
        return response, fills

    def advance(self, as_of: datetime) -> tuple[tuple[OrderStatusObservation, ...], tuple[PaperFillRecord, ...]]:
        updates = self.adapter.advance_simulation(as_of)
        for observation in updates:
            self._status_repository.record(observation)
        fills = self._persist_new_fills(recorded_at=as_of)
        return updates, fills

    def apply_corporate_actions(self, actions: Sequence[CorporateAction], as_of_time: datetime) -> list[str]:
        """Applies `actions` to `self.adapter`'s own accounting, exactly
        once each, EVER, across every process this session's persisted
        `corporate_action_repository` has ever seen -- the piece
        `broker.paper.adapter.PaperBrokerAdapter.apply_corporate_actions`
        cannot provide by itself, since a fresh adapter's own
        `CorporateActionApplier._applied` set is empty every restart
        (ADR-0155).

        Filters `actions` down to those whose `provenance.
        source_record_id` is NOT already in `self._corporate_action_
        repository` (a real persisted lookup, not the adapter's
        in-process set), applies only the remaining ones, then persists
        EVERY one of them regardless of whether `CorporateActionApplier.
        apply()` returned a warning for it -- `apply()` itself already
        adds every action's key to its own `_applied` set even on a
        warning/unhandled-type path (e.g. MERGER, or an unparseable
        ratio), so "never retry, whether it succeeded or only warned" is
        the existing, correct idempotency contract this mirrors at the
        persisted-ledger level too. Returns whatever warnings `apply()`
        produced for the newly-applied subset."""
        remaining = [
            action for action in actions
            if self._corporate_action_repository.get(action.provenance.source_record_id) is None
        ]
        warnings = self.adapter.apply_corporate_actions(remaining, as_of_time)
        for action in remaining:
            self._corporate_action_repository.record(
                PaperAppliedCorporateActionRecord(action=action, applied_at=as_of_time)
            )
        return warnings

    def cancel(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse:
        response = self.adapter.cancel_order(client_order_id, requested_at=requested_at)
        self.capture(client_order_id, as_of=requested_at)
        return response

    def account_summary(self, *, as_of: datetime) -> AccountSummary:
        account = self.adapter.get_account(as_of=as_of)
        positions = {p.security_id: p for p in self.adapter.get_positions(as_of=as_of)}
        return AccountSummary(as_of_time=as_of, cash=account.cash if account.cash is not None else 0.0, positions=positions)

    @classmethod
    def restore(
        cls,
        config: PaperTradingConfig,
        market_data_source: PaperMarketDataSource,
        *,
        order_repository: PaperOrderRepository,
        fill_repository: PaperFillRepository,
        status_repository: OrderStatusEventRepository,
        corporate_action_repository: PaperCorporateActionRepository,
        as_of: datetime,
    ) -> "PaperTradingSession":
        """Rebuilds a fresh `PaperBrokerAdapter`'s entire in-memory state
        by replaying every persisted order (chronological by
        `requested_at`), and then every persisted fill AND every
        persisted applied-corporate-action record TOGETHER, in ONE
        merged chronological sequence -- never re-running failure_mode
        or cash-check logic, only reproducing what already happened
        (instruction section 17, 27).

        **Why fills and corporate actions must be interleaved, not
        replayed as two separate batches (ADR-0155):** `backtest.
        portfolio.PortfolioAccounting.apply_split`/`apply_dividend` is a
        silent no-op against a position that does not exist yet, or that
        is currently flat (`if pos is None or pos.quantity == 0: return`)
        -- correct behavior for a real corporate action arriving while a
        real account genuinely holds nothing in that security. But it
        means REPLAY ORDER is not a stylistic choice: if every persisted
        corporate action were replayed first, in one batch, before any
        fill, a split that occurred while THIS replay had not yet
        reached the fill that actually established the position (because
        that fill is chronologically LATER in real history, even though
        both are being replayed in the same `restore()` call) would
        silently no-op and never get retroactively applied -- the
        position would end up un-split-adjusted, silently wrong, with no
        error. Replaying strictly in real chronological order (this
        method merge-sorts `fill_repository.list_all()`, keyed by each
        record's own `fill.execution_time`, together with
        `corporate_action_repository.list_all()`, keyed by its own real
        `applied_at`) reproduces exactly what actually happened: a fill
        dated before a split gets adjusted BY that split when the split
        is replayed at its own correct position afterward; a fill dated
        after a split already reflects the real, already-adjusted
        market price/quantity (a fill is never itself retroactively
        adjusted -- only a pre-existing position held at the moment a
        split/dividend occurs needs `apply_split`/`apply_dividend`
        called on it, at the right moment in the sequence).

        Each corporate action is replayed via `adapter.
        apply_corporate_actions([action], as_of_time=record.applied_at)`
        -- one call per record, at its own real historical timestamp,
        never batched with a collapsed restore-time timestamp (so a
        replayed dividend's `CashFlowRecord.as_of_time` stays the real
        historical moment, not this restore call's own `as_of`).

        **Exact-timestamp tie-break (ADR-0159, external review): an
        action always replays before a fill sharing its exact
        timestamp.** `orchestration.paper_runner.run_cycle` (ADR-0158)
        applies a cycle's corporate actions and that SAME cycle's T+1
        fill against the identical `as_of_time` -- the real overlap
        case ADR-0158 fixed live produces exactly this tie
        (`fill.execution_time == action.applied_at`), not just a
        theoretical one. Sorting by timestamp alone and relying on
        Python's `sorted` stability would replay the fill first (fills
        are built into this list before actions), the OPPOSITE of
        ADR-0158's live order -- silently reintroducing the same
        double-adjustment/wrong-dividend/missed-dividend corruption
        ADR-0158 closed, but only on the restart-replay path. The
        explicit `(timestamp, 0 if action else 1)` sort key below makes
        replay order match live order exactly, including on a tie."""
        session = cls(
            config, market_data_source, order_repository=order_repository,
            fill_repository=fill_repository, status_repository=status_repository,
            corporate_action_repository=corporate_action_repository,
        )
        for order_record in order_repository.list_all():
            session.adapter.restore_order(order_record)

        fill_records = fill_repository.list_all()
        action_records = corporate_action_repository.list_all()
        # ADR-0159 (external review, 5th verification report): sorting
        # by timestamp alone left an exact tie (fill.execution_time ==
        # action.applied_at -- the precise same-cycle overlap ADR-0158
        # fixed on the LIVE path) to Python's `sorted`'s own stability,
        # which replayed the fill first (it appears first in this list)
        # -- the opposite of ADR-0158's live order (action, then fill).
        # A real overlap cycle produces exactly this tie, since run_cycle
        # passes the SAME as_of_time to both `apply_corporate_actions`
        # and `session.advance`'s fill. The explicit tie-break below
        # matches the live order exactly: on equal timestamps, an action
        # always replays before a fill.
        replay_items = sorted(
            [("fill", r.fill.execution_time, r) for r in fill_records]
            + [("action", r.applied_at, r) for r in action_records],
            key=lambda item: (item[1], 0 if item[0] == "action" else 1),
        )
        for kind, _, record in replay_items:
            if kind == "fill":
                session.adapter.restore_fill(record.fill_id, record.client_order_id, record.fill)
            else:
                session.adapter.apply_corporate_actions([record.action], as_of_time=record.applied_at)

        cancelled_ids = {
            obs.client_order_id for obs in status_repository.list_all()
            if obs.broker_id == config.broker_id and obs.status.value == "CANCELED"
        }
        for client_order_id in cancelled_ids:
            session.adapter.restore_cancellation(client_order_id)

        # Independent audit finding (Step 8, P3, "R2" -- "restart
        # amnesia"): an order rejected at FILL time (never at submit
        # time -- a submit-time rejection's PaperOrderRecord.
        # initial_status is already REJECTED when first persisted, so
        # restore_order above already reproduces it correctly) is only
        # ever recorded that way via an in-memory PaperOrderRecord
        # mutation this same process made -- order_repository keeps that
        # order's ORIGINAL, now-stale PENDING record forever (see
        # PaperBrokerAdapter.restore_rejection's own docstring for the
        # full mechanism). Computed the same way `cancelled_ids` already
        # is, from the real, persisted status observations -- the
        # specific ORIGINAL rejection_reason string (e.g.
        # "insufficient_cash") is not itself persisted per-observation
        # anywhere and is honestly not reconstructed here; only
        # `initial_status` (what actually gates `_attempt_fill`'s own
        # retry guard) needs to be correct to stop the real "retries
        # forever" bug this fixes.
        rejected_ids = {
            obs.client_order_id for obs in status_repository.list_all()
            if obs.broker_id == config.broker_id and obs.status.value == "REJECTED"
        } - cancelled_ids
        for client_order_id in rejected_ids:
            session.adapter.restore_rejection(client_order_id, "restored_as_rejected_from_status_history")

        # Session 37 (ADR-0115, external review N-6): seeds the
        # adapter's observation_id allocator past every id this prior
        # process already persisted, so `rebuild_status_history` below
        # cannot generate a colliding id -- see
        # `restore_observation_id_watermark`'s own docstring.
        for observation in status_repository.list_all():
            session.adapter.restore_observation_id_watermark(observation.observation_id)

        session.adapter.rebuild_status_history(as_of)
        return session
