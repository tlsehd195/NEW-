"""Category: point-in-time leakage, future-data rejection, reproducibility
(Phase 5 spec section 3, 13).

Exercises `RegimeDetector` exclusively through `backtest.asof.AsOfDataView`
-- the same point-in-time-safe view a Strategy already receives -- to
verify a regime computed at an earlier checkpoint is never influenced by
data that only becomes available later.
"""

from __future__ import annotations

from datetime import date, timedelta

from regime_helpers import build_repository, checkpoint, make_bars, trading_days, view_at, high_volatility

from regime.config import RegimeConfig
from regime.detector import RegimeDetector, make_single_point_view
from regime.enums import SubjectKind, TrendState


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    closes = high_volatility(days)
    bars = make_bars("AAA", days, closes)
    repo = build_repository(bars=bars)
    return repo, days


class TestNoLookahead:
    def test_regime_at_an_earlier_checkpoint_is_unaffected_by_appending_later_bars(self) -> None:
        repo, days = _scenario()
        config = RegimeConfig(trend_long_window=30, volatility_percentile_window=30)
        cutoff_index = 60

        view_before = view_at(repo, days, cutoff_index)
        detector = RegimeDetector(config)
        before = detector.compute_composite(view_before, "AAA")

        # Append bars that only exist *after* the cutoff -- mutating the
        # underlying repository the same way live ingestion would.
        extra_days = trading_days(days[-1] + timedelta(days=1), days[-1] + timedelta(days=60))
        extra_closes = [100.0 + i for i in range(len(extra_days))]
        repo.append_bars(make_bars("AAA", extra_days, extra_closes))

        view_again = view_at(repo, days, cutoff_index)
        detector2 = RegimeDetector(config)
        after = detector2.compute_composite(view_again, "AAA")

        for axis in before.axes:
            assert before.axes[axis].state == after.axes[axis].state
            assert before.axes[axis].value == after.axes[axis].value

    def test_asofdataview_never_exposes_bars_beyond_the_current_checkpoint(self) -> None:
        """Defensive, structural check: RegimeDetector never receives a
        bar whose timestamp is after data.current_time, because
        AsOfDataView.get_bars is bound to the clock (ADR-0004 / Phase 2
        spec section 3.2) -- verified here by inspecting the bars the
        detector's own points would have been built from."""
        repo, days = _scenario()
        cutoff_index = 40
        view = view_at(repo, days, cutoff_index)
        bars = view.get_bars("AAA", checkpoint(days[0], 0), checkpoint(days[-1]))
        assert all(b.timestamp <= view.current_time for b in bars)

    def test_replay_at_the_same_as_of_time_is_deterministic(self) -> None:
        repo, days = _scenario()
        config = RegimeConfig(trend_long_window=30, volatility_percentile_window=30)
        cutoff_index = 90

        view1 = view_at(repo, days, cutoff_index)
        result1 = RegimeDetector(config).compute_composite(view1, "AAA")

        view2 = view_at(repo, days, cutoff_index)
        result2 = RegimeDetector(config).compute_composite(view2, "AAA")

        assert {axis: obs.state for axis, obs in result1.axes.items()} == {
            axis: obs.state for axis, obs in result2.axes.items()
        }
        assert {axis: obs.value for axis, obs in result1.axes.items()} == {
            axis: obs.value for axis, obs in result2.axes.items()
        }

    def test_standalone_repository_view_matches_backtest_clock_view(self) -> None:
        """`make_single_point_view` (used for standalone/replay regime
        computation, Phase 5 spec section 8) must produce byte-identical
        results to computing the same regime from inside a live
        multi-checkpoint BacktestClock -- both paths go through the exact
        same AsOfDataView/BacktestClock types."""
        repo, days = _scenario()
        config = RegimeConfig(trend_long_window=30, volatility_percentile_window=30)
        cutoff_index = 70

        backtest_view = view_at(repo, days, cutoff_index)
        via_backtest = RegimeDetector(config).compute_composite(backtest_view, "AAA")

        standalone_view = make_single_point_view(repo, checkpoint(days[cutoff_index]))
        via_standalone = RegimeDetector(config).compute_composite(standalone_view, "AAA")

        for axis in via_backtest.axes:
            assert via_backtest.axes[axis].state == via_standalone.axes[axis].state
            assert via_backtest.axes[axis].value == via_standalone.axes[axis].value

    def test_future_dated_query_is_structurally_impossible_through_asofdataview(self) -> None:
        """AsOfDataView has no parameter through which RegimeDetector
        (or any well-behaved caller) could request a later as_of_time --
        mirrors Phase 2's own no-lookahead guarantee (Phase 2 spec
        section 3.2), re-verified specifically for the regime code path."""
        import inspect

        from backtest.asof import AsOfDataView

        sig = inspect.signature(AsOfDataView.get_bars)
        assert "as_of_time" not in sig.parameters
