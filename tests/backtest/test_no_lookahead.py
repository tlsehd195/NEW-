"""Category: No-lookahead test.

Verifies AsOfDataView (Phase 2 spec section 3.2) never surfaces data
beyond BacktestClock.current_time, for every data kind it exposes.
"""

from __future__ import annotations

from datetime import date, timedelta

from backtest_helpers import build_repository, checkpoint, make_bars, make_benchmark, make_membership, make_security, trading_days

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from data_infra.calendar import US_EQUITY


def _setup():
    days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
    closes = [100.0 + i for i in range(len(days))]
    bars = make_bars("AAA", days, closes)
    sec = make_security("AAA", "AAA")
    bench = make_benchmark(days, [4000.0 + i for i in range(len(days))])
    membership = make_membership("AAA", checkpoint(days[0]) - timedelta(days=1))
    repo = build_repository(bars=bars, securities=[sec], benchmarks=bench, universe_memberships=[membership])
    checkpoints = build_daily_checkpoints(US_EQUITY, days[0], days[-1])
    return repo, days, checkpoints


class TestNoLookahead:
    def test_get_bars_never_returns_future_bars(self) -> None:
        repo, days, checkpoints = _setup()
        clock = BacktestClock(checkpoints)
        clock.index = 2  # third trading day
        view = AsOfDataView(repo, clock)

        bars = view.get_bars("AAA", checkpoint(days[0]) - timedelta(days=1), checkpoint(days[-1]))
        latest_seen = max(b.timestamp for b in bars)
        assert latest_seen <= checkpoints[2]
        assert latest_seen.date() == days[2]  # nothing beyond "today"

    def test_advancing_clock_reveals_more_bars_monotonically(self) -> None:
        repo, days, checkpoints = _setup()
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)

        counts = []
        for i in range(len(checkpoints)):
            clock.index = i
            bars = view.get_bars("AAA", checkpoint(days[0]) - timedelta(days=1), checkpoint(days[-1]))
            counts.append(len(bars))
        assert counts == sorted(counts)  # never decreases
        assert counts[-1] == len(days)  # everything visible by the last checkpoint

    def test_get_corporate_actions_bounded_by_clock(self) -> None:
        from backtest_helpers import make_split

        repo, days, checkpoints = _setup()
        future_split = make_split("AAA", days[-1])  # available only at the very last checkpoint
        repo = build_repository(
            bars=repo.all_bars(),
            securities=[make_security("AAA", "AAA")],
            corporate_actions=[future_split],
        )
        clock = BacktestClock(checkpoints)
        clock.index = 0
        view = AsOfDataView(repo, clock)
        actions = view.get_corporate_actions(
            "AAA", checkpoint(days[0]) - timedelta(days=1), checkpoint(days[-1])
        )
        assert actions == []

    def test_get_benchmark_bounded_by_clock(self) -> None:
        repo, days, checkpoints = _setup()
        clock = BacktestClock(checkpoints)
        clock.index = 1
        view = AsOfDataView(repo, clock)
        points = view.get_benchmark("SP500", checkpoint(days[0]) - timedelta(days=1), checkpoint(days[-1]))
        assert all(p.timestamp <= checkpoints[1] for p in points)
        assert len(points) == 2

    def test_get_universe_bounded_by_clock(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 12))
        early_member = make_membership("AAA", checkpoint(days[0]) - timedelta(days=1))
        late_member = make_membership("BBB", checkpoint(days[5]))  # joins mid-window
        repo = build_repository(universe_memberships=[early_member, late_member])
        checkpoints = build_daily_checkpoints(US_EQUITY, days[0], days[-1])
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)

        clock.index = 1
        early_universe = view.get_universe("US", "SP500")
        assert early_universe == ["AAA"]

        clock.index = 6
        later_universe = view.get_universe("US", "SP500")
        assert set(later_universe) == {"AAA", "BBB"}

    def test_view_has_no_as_of_time_parameter_anywhere(self) -> None:
        # Structural guarantee (Phase 2 spec section 3.2): no method on
        # AsOfDataView accepts an as_of_time override.
        import inspect

        for name, method in inspect.getmembers(AsOfDataView, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            params = inspect.signature(method).parameters
            assert "as_of_time" not in params, f"{name} must not accept as_of_time"
