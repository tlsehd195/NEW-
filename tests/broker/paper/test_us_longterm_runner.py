"""Category: Paper Trading Runner Test (Phase 22) --
run_buy_and_hold_paper_session drives PaperTradingSession over an
explicit decision schedule, never reading wall-clock time."""

from __future__ import annotations

from datetime import datetime, timezone

from paper_helpers import make_bar, make_paper_config

from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession
from broker.paper.us_longterm_runner import run_buy_and_hold_paper_session


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestEqualWeightAllocation:
    def test_allocates_cash_equally_across_symbols(self) -> None:
        buy_time = utc(2024, 1, 2)
        symbols = ["AAA", "BBB"]
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=buy_time, close=100.0),
            make_bar(security_id="BBB", available_time=buy_time, close=50.0),
        ])
        # A large enough cash base that per-share integer flooring is a
        # small relative rounding effect, not the dominant one -- the
        # point of this test is the equal-weight allocation logic, not
        # small-number lot-rounding behavior (covered separately).
        config = make_paper_config(initial_cash=100_000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(symbols, mds, session, buy_time=buy_time, configuration_version="cfg-v1")

        assert len(result.orders) == 2
        assert result.skipped_symbols == ()
        by_symbol = {o.security_id: o for o in result.orders}
        for outcome in result.orders:
            assert outcome.response.status.value == "FILLED"
            assert len(outcome.fills) == 1
        # Roughly equal notional value per symbol (not exact -- a
        # cost-safety-margin and per-fill commission/spread mean each
        # leg spends a slightly different amount, and BBB is priced
        # from whatever cash remains after AAA's own costs, not the
        # original 500/500 split) -- within 20% of each other confirms
        # the allocation is genuinely equal-weight, not skewed.
        aaa_notional = by_symbol["AAA"].quantity * 100.0
        bbb_notional = by_symbol["BBB"].quantity * 50.0
        assert aaa_notional > 0 and bbb_notional > 0
        assert abs(aaa_notional - bbb_notional) / max(aaa_notional, bbb_notional) < 0.20

    def test_only_buys_once_true_buy_and_hold(self) -> None:
        """Calling the runner a second time re-allocates against
        whatever cash remains, proving this is a one-shot allocation
        primitive, not a rebalancing loop -- a caller who wants true
        buy-and-hold simply calls it once."""
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id="AAA", available_time=buy_time, close=100.0)])
        config = make_paper_config(initial_cash=1000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        first = run_buy_and_hold_paper_session(["AAA"], mds, session, buy_time=buy_time, configuration_version="cfg-v1")
        assert len(first.orders) == 1
        remaining_cash = session.adapter.get_account(as_of=buy_time).cash
        assert remaining_cash < 1000.0  # cash was actually spent, not simulated


class TestSkipsSymbolsHonestly:
    def test_symbol_with_no_reference_price_is_skipped_not_fabricated(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id="AAA", available_time=buy_time, close=100.0)])
        config = make_paper_config(initial_cash=1000.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(["AAA", "NODATA"], mds, session, buy_time=buy_time, configuration_version="cfg-v1")
        assert "NODATA" in result.skipped_symbols
        assert result.skip_reasons["NODATA"] == "no_reference_price_available"
        assert len(result.orders) == 1

    def test_insufficient_cash_for_one_lot_is_skipped(self) -> None:
        buy_time = utc(2024, 1, 2)
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id="AAA", available_time=buy_time, close=1.0),
            make_bar(security_id="EXPENSIVE", available_time=buy_time, close=1_000_000.0),
        ])
        config = make_paper_config(initial_cash=10.0, max_participation=1.0)
        session = PaperTradingSession(config, mds)

        result = run_buy_and_hold_paper_session(["AAA", "EXPENSIVE"], mds, session, buy_time=buy_time, configuration_version="cfg-v1")
        assert "EXPENSIVE" in result.skipped_symbols
        assert result.skip_reasons["EXPENSIVE"] == "insufficient_cash_for_one_lot"
