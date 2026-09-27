"""Category: Regression test -- the research buy-and-hold baseline must
be (almost) fully invested, not mostly cash (ADR-0223).

With whole shares, $10k split over 203 names is ~$48 a name, so every
name priced above that got 0 shares, and names not yet listed at the
first checkpoint kept their slice as cash for the whole run."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy, buy_and_hold_baseline

_PRICES = {"AAA": 20.0, "BBB": 500.0, "CCC": 1_000.0}


def _run(strategy, security_ids, bars_by_symbol, days, capital=1_000.0):
    bars = [bar for symbol_bars in bars_by_symbol.values() for bar in symbol_bars]
    repo = build_repository(bars=bars, securities=[make_security(s, s) for s in security_ids])
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1],
        initial_capital=capital, security_ids=tuple(security_ids),
    )
    return BacktestEngine(repo, config, strategy).run()


def _invested(result, prices):
    return sum(f.quantity * prices[f.security_id] for f in result.fills if f.side.value == "BUY")


class TestFractionalBuyAndHold:
    def test_whole_shares_leave_expensive_names_uninvested(self) -> None:
        """The old behaviour, kept as the default for other callers."""
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = {s: make_bars(s, days, [p] * len(days)) for s, p in _PRICES.items()}
        result = _run(BuyAndHoldStrategy(list(_PRICES)), list(_PRICES), bars, days)
        assert {f.security_id for f in result.fills} == {"AAA"}

    def test_fractional_buys_every_name_and_invests_nearly_all_cash(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = {s: make_bars(s, days, [p] * len(days)) for s, p in _PRICES.items()}
        result = _run(buy_and_hold_baseline(list(_PRICES), 1_000.0), list(_PRICES), bars, days)
        assert {f.security_id for f in result.fills} == set(_PRICES)
        assert not [o for o in result.orders if o.status.value == "REJECTED"]
        assert _invested(result, _PRICES) > 0.9 * 1_000.0

    def test_cash_is_split_only_across_names_with_a_price(self) -> None:
        """A name with no bar yet (a later IPO) must not strand its slice."""
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = {s: make_bars(s, days, [p] * len(days)) for s, p in _PRICES.items() if s != "CCC"}
        result = _run(buy_and_hold_baseline(list(_PRICES), 1_000.0), list(_PRICES), bars, days)
        assert {f.security_id for f in result.fills} == {"AAA", "BBB"}
        assert _invested(result, _PRICES) > 0.9 * 1_000.0

    def test_margin_covers_one_fixed_commission_per_name(self) -> None:
        """$1 per trade on 200 names is 2% of $10k: the plain 2% margin
        alone would leave the last orders short of cash."""
        names = [f"S{i:03d}" for i in range(200)]
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        bars = {s: make_bars(s, days, [75.0] * len(days)) for s in names}
        result = _run(buy_and_hold_baseline(names, 10_000.0), names, bars, days, capital=10_000.0)
        assert len({f.security_id for f in result.fills}) == 200
        assert _invested(result, {s: 75.0 for s in names}) > 0.9 * 10_000.0
