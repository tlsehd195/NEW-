"""Category: Survivorship test -- point-in-time universe plumbing
(ADR-0224): a strategy built over every name ever in the index only sees
the names that are members on each date, may sell a name after it
leaves, and a held name that stops trading is settled to cash."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from backtest_helpers import build_repository, checkpoint, make_bars, make_membership, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.enums import OrderSide
from backtest.strategy import BuyAndHoldStrategy, OrderIntent


def _config(days, **overrides):
    return BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=10_000.0,
        universe=("US", "SP500"), **overrides,
    )


class _HoldWhateverHasBars:
    """Holds every name that has a bar today, sells whatever has none --
    the shape of every ranking strategy in strategy_research."""

    version = "hold_whatever_has_bars_v1"

    def __init__(self, security_ids):
        self._security_ids = list(security_ids)

    def generate_orders(self, as_of_time, data, portfolio):
        visible = {
            sid for sid in self._security_ids
            if data.get_bars(sid, as_of_time - timedelta(days=5), as_of_time)
        }
        intents = [
            OrderIntent(sid, OrderSide.SELL, pos.quantity)
            for sid, pos in portfolio.positions.items() if sid not in visible
        ]
        intents += [OrderIntent(sid, OrderSide.BUY, 10.0) for sid in sorted(visible) if portfolio.quantity_of(sid) == 0]
        return intents


class TestRestrictStrategyToUniverse:
    def test_non_member_is_invisible_and_leaver_is_sold_without_integrity_error(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        drop_day = days[8]
        bars = make_bars("OLD", days, [100.0] * len(days)) + make_bars("OUT", days, [50.0] * len(days))
        repo = build_repository(
            bars=bars,
            securities=[make_security("OLD", "OLD"), make_security("OUT", "OUT")],
            universe_memberships=[make_membership("OLD", checkpoint(days[0]) - timedelta(days=1), checkpoint(drop_day))],
        )
        result = BacktestEngine(
            repo, _config(days, restrict_strategy_to_universe=True), _HoldWhateverHasBars(["OLD", "OUT"])
        ).run()

        assert "OUT" not in {f.security_id for f in result.fills}
        sells = [f for f in result.fills if f.side == OrderSide.SELL]
        assert [f.security_id for f in sells] == ["OLD"]
        assert sells[0].execution_time.date() > drop_day
        assert not any(i.check == "universe_correctness" for i in result.integrity.issues)
        assert result.is_valid_performance

    def test_requires_a_dynamic_universe(self) -> None:
        with pytest.raises(ValueError):
            BacktestConfig(
                market="US_EQUITY", start_date=date(2024, 1, 2), end_date=date(2024, 1, 5),
                initial_capital=1.0, security_ids=("A",), restrict_strategy_to_universe=True,
            )


class TestStalePositionSettlement:
    def _run(self, settle_after):
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        last_trading_index = 6
        bars = make_bars("GONE", days[: last_trading_index + 1], [100.0] * last_trading_index + [80.0])
        repo = build_repository(
            bars=bars,
            securities=[make_security("GONE", "GONE")],
            universe_memberships=[make_membership("GONE", checkpoint(days[0]) - timedelta(days=1))],
        )
        config = _config(days, settle_after_missing_checkpoints=settle_after)
        return days, last_trading_index, BacktestEngine(repo, config, BuyAndHoldStrategy(["GONE"])).run()

    def test_settles_at_last_close_after_n_missing_checkpoints(self) -> None:
        days, last_index, result = self._run(settle_after=3)
        settled = [i for i in result.integrity.issues if i.check == "stale_position_settled"]
        assert len(settled) == 1
        assert settled[0].as_of_time.date() == days[last_index + 3]
        assert "80.0000" in settled[0].message
        assert result.is_valid_performance

        buy = next(f for f in result.fills if f.side == OrderSide.BUY)
        expected_final = 10_000.0 - buy.notional - buy.commission + buy.quantity * 80.0
        assert result.performance.cumulative_return == pytest.approx(expected_final / 10_000.0 - 1.0, rel=1e-9)

    def test_off_by_default_keeps_marking_at_cost(self) -> None:
        _, _, result = self._run(settle_after=None)
        assert not any(i.check == "stale_position_settled" for i in result.integrity.issues)
