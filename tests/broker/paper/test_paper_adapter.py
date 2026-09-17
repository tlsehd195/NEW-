"""Category: Unit Test -- order lifecycle, fill calculation, partial
fill, idempotency, failure modes, cash/position accounting for
`PaperBrokerAdapter`.

ADR-0154: `submit_order` no longer attempts a fill synchronously (T+1
discipline, matching `backtest.engine.BacktestEngine`) -- an order is
always PENDING immediately after `submit_order` returns, and its first
fill attempt happens only via an explicit `advance_simulation` call.
Every test below that used to assert an immediate fill from
`submit_order` now submits, asserts PENDING, then calls
`advance_simulation` (at the same or a later `as_of`, as the scenario
requires) before asserting the real fill outcome."""

from __future__ import annotations

import pytest

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerAuthError, BrokerRateLimitError, BrokerTimeoutError, BrokerTransportError
from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.market_data import InMemoryPaperMarketDataSource

from backtest.enums import OrderSide


def _adapter(config=None, bars=()):
    config = config or make_paper_config()
    mds = InMemoryPaperMarketDataSource(list(bars))
    return PaperBrokerAdapter(config, mds), mds


class TestGetAccountCurrency:
    def test_paper_account_currency_is_usd_not_krw(self) -> None:
        # ADR-0117: Paper accounting is natively USD-denominated
        # (PortfolioAccounting/PriceBar price exclusively in USD,
        # ADR-0025/ADR-0026 -- see broker.paper.us_longterm_config's own
        # docstring) -- get_account used to hardcode currency="KRW",
        # mislabeling every real Paper account snapshot's currency.
        adapter, _ = _adapter()
        account = adapter.get_account(as_of=utc(2024, 1, 2))
        assert account.currency == "USD"


class TestSubmitOrderNeverFillsSynchronously:
    """ADR-0154: the core new contract -- `submit_order` never attempts
    a fill against the SAME `as_of`/bar it decided against (the same-bar
    leak this fix closes). This holds even when a bar is available and
    every other condition would previously have produced an immediate
    FILLED."""

    def test_submit_order_leaves_a_fillable_order_pending(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING
        assert response.filled_quantity is None
        # no fill applied yet -- no position exists
        assert adapter.get_positions(as_of=utc(2024, 1, 2)) == ()


class TestNormalFill:
    def test_market_order_fills_against_reference_bar(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING

        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates[-1].status == BrokerOrderStatus.FILLED
        assert updates[-1].filled_quantity == 10.0
        status = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 3))
        assert status.avg_fill_price is not None and status.avg_fill_price > 100.0  # BUY pays through spread+slippage

    def test_sell_price_is_below_reference(self) -> None:
        adapter, mds = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        buy = make_validated_order(client_order_id="CID-B", side=OrderSide.BUY, quantity=10.0)
        adapter.submit_order(buy, requested_at=utc(2024, 1, 2))
        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3)))
        adapter.advance_simulation(utc(2024, 1, 3))  # fills the BUY first

        sell = make_validated_order(client_order_id="CID-S", side=OrderSide.SELL, quantity=5.0)
        response = adapter.submit_order(sell, requested_at=utc(2024, 1, 3))
        assert response.status == BrokerOrderStatus.PENDING

        mds.register(make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4)))
        updates = adapter.advance_simulation(utc(2024, 1, 4))
        assert updates[-1].status == BrokerOrderStatus.FILLED
        status = adapter.get_order_status(sell.client_order_id, as_of=utc(2024, 1, 4))
        assert status.avg_fill_price < 100.0


class TestPartialFill:
    def test_low_volume_bar_produces_partial_fill_then_completes(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10),
            bars=[make_bar(timestamp=utc(2024, 1, 2), available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        order = make_validated_order(quantity=250.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING
        assert response.filled_quantity is None

        # First fill attempt (deferred, ADR-0154): still against the
        # same bar submission itself decided against -- no data has
        # moved forward yet, so this is the direct analogue of a T+1
        # fill landing on the very next available checkpoint.
        updates0 = adapter.advance_simulation(utc(2024, 1, 2))
        assert updates0[-1].status == BrokerOrderStatus.PARTIAL_FILLED
        assert updates0[-1].filled_quantity == 100.0

        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates[-1].status == BrokerOrderStatus.PARTIAL_FILLED
        assert updates[-1].filled_quantity == 200.0

        mds.register(make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4), volume=1_000.0))
        updates2 = adapter.advance_simulation(utc(2024, 1, 4))
        assert updates2[-1].status == BrokerOrderStatus.FILLED
        assert updates2[-1].filled_quantity == 250.0

    def test_partial_fill_disabled_fills_nothing_until_full_liquidity(self) -> None:
        adapter, _ = _adapter(
            config=make_paper_config(max_participation=0.10, partial_fill_enabled=False),
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        order = make_validated_order(quantity=250.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING
        assert response.filled_quantity is None

        # Same low-volume bar still can't fill the whole order even
        # once an attempt is actually made via advance_simulation.
        updates = adapter.advance_simulation(utc(2024, 1, 2))
        assert updates == ()
        status = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.PENDING

    def test_no_data_available_keeps_order_pending(self) -> None:
        adapter, _ = _adapter(bars=[])
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING
        assert response.filled_quantity is None


class TestPendingOrderTTL:
    """External review (Session 38 continued): before this, a still-open
    order that could never fill (e.g. its security permanently lost
    liquidity) stayed PENDING/PARTIAL_FILLED forever -- `advance_
    simulation` retries it every call with no way to give up.
    `PaperTradingConfig.pending_order_ttl_days` is opt-in (`None` by
    default) auto-cancellation past a real day count."""

    def test_ttl_none_leaves_a_stuck_order_pending_forever(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10, partial_fill_enabled=False),
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1.0)],
        )
        order = make_validated_order(quantity=1_000.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING

        mds.register(make_bar(available_time=utc(2024, 6, 1), volume=1.0))
        updates = adapter.advance_simulation(utc(2024, 6, 1))
        assert updates == ()  # still can't fill -- but never gives up either
        assert adapter.get_order_status(order.client_order_id, as_of=utc(2024, 6, 1)).status == BrokerOrderStatus.PENDING

    def test_order_older_than_ttl_is_auto_cancelled_instead_of_retried(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10, partial_fill_enabled=False, pending_order_ttl_days=30),
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1.0)],
        )
        order = make_validated_order(quantity=1_000.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING

        mds.register(make_bar(available_time=utc(2024, 2, 5), volume=1_000_000.0))  # 34 days later, ample liquidity now
        updates = adapter.advance_simulation(utc(2024, 2, 5))
        assert len(updates) == 1
        assert updates[0].status == BrokerOrderStatus.CANCELED
        assert adapter.get_order_status(order.client_order_id, as_of=utc(2024, 2, 5)).status == BrokerOrderStatus.CANCELED

    def test_order_younger_than_ttl_still_retries_normally(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10, partial_fill_enabled=False, pending_order_ttl_days=30),
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1.0)],
        )
        order = make_validated_order(quantity=1_000.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))

        mds.register(make_bar(available_time=utc(2024, 1, 20), volume=1_000_000.0))  # 18 days later -- within TTL
        updates = adapter.advance_simulation(utc(2024, 1, 20))
        assert len(updates) == 1
        assert updates[0].status == BrokerOrderStatus.FILLED  # retried and filled, not cancelled

    def test_a_filled_order_is_never_touched_by_ttl(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(pending_order_ttl_days=1),
            bars=[make_bar(available_time=utc(2024, 1, 2))],
        )
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING

        updates = adapter.advance_simulation(utc(2024, 1, 2))  # same day -- well within the 1-day TTL
        assert updates[-1].status == BrokerOrderStatus.FILLED

        updates2 = adapter.advance_simulation(utc(2024, 6, 1))  # far past the 1-day TTL
        assert updates2 == ()  # already FILLED -- advance_simulation skips it entirely


class TestParticipationCapSharedAcrossOrdersInTheSameBar:
    """External review, MEDIUM-2 (Session 38 continued): before this,
    `simulate_fill` recomputed `max_fillable = bar.volume *
    max_participation` fresh on every call, so two different orders
    against the same (security_id, bar) each independently got the
    full participation share -- doubling the real cap for that bar.

    ADR-0154: both orders below are submitted (left PENDING) and then
    attempt their fills together in ONE `advance_simulation` call --
    the direct analogue of two orders sharing one T+1 checkpoint's cap."""

    def test_second_order_gets_zero_once_the_first_consumed_the_whole_cap(self) -> None:
        adapter, _ = _adapter(
            config=make_paper_config(max_participation=0.10),
            bars=[make_bar(timestamp=utc(2024, 1, 2), available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        first = make_validated_order(client_order_id="CID-1", quantity=100.0)
        adapter.submit_order(first, requested_at=utc(2024, 1, 2))
        second = make_validated_order(client_order_id="CID-2", quantity=50.0)
        adapter.submit_order(second, requested_at=utc(2024, 1, 2))

        adapter.advance_simulation(utc(2024, 1, 2))
        status1 = adapter.get_order_status("CID-1", as_of=utc(2024, 1, 2))
        assert status1.status == BrokerOrderStatus.FILLED
        assert status1.filled_quantity == 100.0  # the whole 10% cap of this bar's 1,000 volume

        status2 = adapter.get_order_status("CID-2", as_of=utc(2024, 1, 2))
        assert status2.status == BrokerOrderStatus.PENDING  # no participation cap left on this bar
        assert status2.filled_quantity is None

    def test_second_order_gets_only_the_remaining_share_of_the_cap(self) -> None:
        adapter, _ = _adapter(
            config=make_paper_config(max_participation=0.10),
            bars=[make_bar(timestamp=utc(2024, 1, 2), available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        first = make_validated_order(client_order_id="CID-1", quantity=60.0)
        adapter.submit_order(first, requested_at=utc(2024, 1, 2))
        second = make_validated_order(client_order_id="CID-2", quantity=100.0)
        adapter.submit_order(second, requested_at=utc(2024, 1, 2))

        adapter.advance_simulation(utc(2024, 1, 2))
        status1 = adapter.get_order_status("CID-1", as_of=utc(2024, 1, 2))
        assert status1.status == BrokerOrderStatus.FILLED
        assert status1.filled_quantity == 60.0

        # Only 100 - 60 = 40 of the 100-share cap remains for this bar.
        status2 = adapter.get_order_status("CID-2", as_of=utc(2024, 1, 2))
        assert status2.status == BrokerOrderStatus.PARTIAL_FILLED
        assert status2.filled_quantity == 40.0

    def test_a_later_bar_gets_a_fresh_cap(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10),
            bars=[make_bar(timestamp=utc(2024, 1, 2), available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        first = make_validated_order(client_order_id="CID-1", quantity=100.0)
        adapter.submit_order(first, requested_at=utc(2024, 1, 2))
        adapter.advance_simulation(utc(2024, 1, 2))  # consumes day-1's whole cap

        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        second = make_validated_order(client_order_id="CID-2", quantity=100.0)
        adapter.submit_order(second, requested_at=utc(2024, 1, 3))
        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates[-1].status == BrokerOrderStatus.FILLED
        assert updates[-1].filled_quantity == 100.0  # a different bar -- its own, unconsumed cap


class TestIdempotency:
    def test_duplicate_submission_returns_same_logical_order(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        r1 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        r2 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert r1.status == r2.status == BrokerOrderStatus.PENDING

        updates = adapter.advance_simulation(utc(2024, 1, 2))
        assert updates[-1].status == BrokerOrderStatus.FILLED
        assert updates[-1].filled_quantity == 10.0

        # a duplicate submission after the fill still replays idempotently
        r3 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert r3.status == BrokerOrderStatus.FILLED
        assert r3.filled_quantity == 10.0

        # no double fill -- position reflects exactly one fill of 10 shares
        positions = adapter.get_positions(as_of=utc(2024, 1, 2))
        assert positions[0].quantity == 10.0


class TestCancellation:
    def test_cancel_open_order(self) -> None:
        adapter, _ = _adapter(bars=[])  # no data -- stays PENDING
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        response = adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.CANCELED
        status = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.CANCELED

    def test_cannot_cancel_filled_order(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        adapter.advance_simulation(utc(2024, 1, 2))  # fills the order
        response = adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED
        assert response.error_code == "already_filled"

    def test_cancel_unknown_order_id(self) -> None:
        adapter, _ = _adapter(bars=[])
        response = adapter.cancel_order("CID-NEVER-SUBMITTED", requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN


class TestFailureModes:
    def test_rejected_mode_rejects_new_orders(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="rejected"), bars=[make_bar(available_time=utc(2024, 1, 2))])
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.REJECTED
        assert response.error_code == "simulated_rejection"

    def test_timeout_mode_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="timeout"))
        with pytest.raises(BrokerTimeoutError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))

    def test_auth_mode_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="auth"))
        with pytest.raises(BrokerAuthError):
            adapter.get_account(as_of=utc(2024, 1, 2))

    def test_rate_limit_mode_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="rate_limit"))
        with pytest.raises(BrokerRateLimitError):
            adapter.get_positions(as_of=utc(2024, 1, 2))

    def test_unavailable_mode_raises_on_every_call(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="unavailable"))
        with pytest.raises(BrokerTransportError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        with pytest.raises(BrokerTransportError):
            adapter.get_account(as_of=utc(2024, 1, 2))

    def test_malformed_mode_returns_unknown_never_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="malformed"), bars=[make_bar(available_time=utc(2024, 1, 2))])
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN
        assert response.error_code == "malformed_response"
        # no fill was ever applied
        assert adapter.get_positions(as_of=utc(2024, 1, 2)) == ()

    def test_unknown_status_mode_never_confirms_fill_via_status_query(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="unknown_status"), bars=[make_bar(available_time=utc(2024, 1, 2))])
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING  # submission itself succeeds, fill is deferred

        updates = adapter.advance_simulation(utc(2024, 1, 2))
        assert updates[-1].status == BrokerOrderStatus.FILLED  # the deferred fill really happens...

        status = adapter.get_order_status("CID-000001", as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.UNKNOWN  # ...but status queries cannot confirm it
        assert status.status != BrokerOrderStatus.FILLED


class TestCapabilities:
    def test_capabilities_do_not_claim_limit_order_support(self) -> None:
        adapter, _ = _adapter()
        capabilities = adapter.get_capabilities(as_of=utc(2024, 1, 2))
        from broker.enums import BrokerCapability, CapabilityStatus

        assert capabilities.status_of(BrokerCapability.LIMIT_ORDER) == CapabilityStatus.UNSUPPORTED
        assert capabilities.is_enabled(BrokerCapability.MARKET_ORDER)
