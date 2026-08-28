"""Phase 25 walk-forward evaluation tests (instruction section 24,
categories C/D/E/F/G/H/I/J/K/M). SYNTHETIC FIXTURE ONLY (`research_helpers`,
`backtest_helpers`) -- pipeline-correctness tests, never a real-data
evidence claim (instruction rule 0.4). Real-data results live in
`docs/research/STRATEGY-VALIDATION-REPORT.md`, produced by
`scripts/run_long_horizon_validation.py`, never by this test module.

Category R (restart persistence) is explicitly N/A this phase: neither
`run_walk_forward_evaluation` nor `evidence.py` adds any new
`DataRepository` persistence -- both are pure read-side/computation
code over an already-existing repository. `test_duckdb_backed_research_pipeline.py`
(Phase 23/24) already covers restart survival for the persistence layer
these functions read through, unmodified.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from backtest_helpers import make_bars, make_dividend, make_security, make_split, trading_days
from research_helpers import days_to_utc, synthetic_multi_year_repository

from backtest.strategy import BuyAndHoldStrategy
from data_infra.calendar import US_EQUITY
from data_infra.repository import InMemoryDataRepository

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy
from strategy_research.walk_forward_evaluation import run_walk_forward_evaluation

_UNIVERSE = ("TRENDUP", "TRENDDOWN", "CYCLICAL")


def _small_repo(start=date(2020, 1, 2), end=date(2022, 6, 1)):
    return synthetic_multi_year_repository(start, end, symbols=_UNIVERSE)


class TestFoldOrderingAndNonOverlap:
    """Categories D (window ordering) and E (no overlap)."""

    def test_folds_are_sequential_and_chronologically_non_decreasing(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        assert aggregate.fold_count >= 2, "sanity check: this window must produce multiple folds"
        indices = [f.fold_index for f in aggregate.folds]
        assert indices == sorted(indices) == list(range(len(indices)))
        test_starts = [f.test_start for f in aggregate.folds]
        assert test_starts == sorted(test_starts)

    def test_consecutive_fold_test_windows_never_overlap_when_step_covers_test_window(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        for earlier, later in zip(aggregate.folds, aggregate.folds[1:]):
            assert earlier.test_end <= later.test_start


class TestDeterministicReplay:
    """Category F: identical inputs -> identical outputs, every time."""

    def test_running_twice_with_identical_inputs_produces_identical_aggregate(self) -> None:
        repo = _small_repo()

        def run_once():
            return run_walk_forward_evaluation(
                repo, lambda: LongTermMomentumStrategy(list(_UNIVERSE), LongTermMomentumParameters(lookback_months=6, top_n=2, rebalance_months=3)),
                _UNIVERSE,
                overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
                train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
            )

        first = run_once()
        second = run_once()
        assert first.fold_count == second.fold_count
        assert first.median_net_cumulative_return == second.median_net_cumulative_return
        assert first.median_net_sharpe == second.median_net_sharpe
        assert first.regime_breakdown == second.regime_breakdown
        for f1, f2 in zip(first.folds, second.folds):
            assert f1.test_start == f2.test_start and f1.test_end == f2.test_end
            assert f1.result.net.performance.cumulative_return == f2.result.net.performance.cumulative_return
            assert f1.result.net.fills == f2.result.net.fills


class TestFutureLeakage:
    """Category C: a fold's own result must not change if the repository
    also holds bars dated AFTER that fold's test_end -- the same
    discipline `test_no_future_leakage.py` already proves at the single
    signal level, re-verified here at the walk-forward-fold level."""

    def test_first_fold_result_unchanged_by_bars_dated_after_its_test_window(self) -> None:
        overall_start, overall_end = date(2020, 1, 2), date(2021, 3, 1)
        repo_short = synthetic_multi_year_repository(overall_start, overall_end, symbols=_UNIVERSE)
        repo_long = synthetic_multi_year_repository(overall_start, date(2023, 1, 3), symbols=_UNIVERSE)

        kwargs = dict(
            overall_start=days_to_utc(overall_start), overall_end=days_to_utc(overall_end),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        agg_short = run_walk_forward_evaluation(repo_short, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE, **kwargs)
        agg_long = run_walk_forward_evaluation(repo_long, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE, **kwargs)

        assert agg_short.fold_count == agg_long.fold_count >= 1
        first_short, first_long = agg_short.folds[0], agg_long.folds[0]
        assert first_short.result.net.performance.cumulative_return == first_long.result.net.performance.cumulative_return
        assert first_short.result.net.fills == first_long.result.net.fills


class TestTransactionCostAndGrossNetConsistency:
    """Categories G (cost inclusion) and H (gross/net consistency)."""

    def test_net_leg_reflects_nonzero_transaction_cost_when_trades_occur(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        assert aggregate.fold_count >= 1
        for fold in aggregate.folds:
            if fold.result.net.fills:
                assert fold.result.net.performance.total_transaction_cost > 0.0
                assert fold.result.gross.performance.total_transaction_cost == 0.0

    def test_gross_and_net_trade_the_same_fills_but_net_return_is_not_better(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        for fold in aggregate.folds:
            if fold.result.gross.fills:
                gross_symbols = sorted(f.security_id for f in fold.result.gross.fills)
                net_symbols = sorted(f.security_id for f in fold.result.net.fills)
                assert gross_symbols == net_symbols
                assert fold.result.net.performance.cumulative_return <= fold.result.gross.performance.cumulative_return


class TestBenchmarkAlignment:
    """Category I: excess_return is populated when a benchmark_id is
    supplied and available, and stays honestly None when it is not."""

    def test_excess_return_is_none_without_a_benchmark(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
            benchmark_id=None,
        )
        for fold in aggregate.folds:
            assert fold.result.net.performance.excess_return is None

    def test_excess_return_is_populated_with_a_real_benchmark(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
            benchmark_id="SP500",
        )
        assert any(fold.result.net.performance.excess_return is not None for fold in aggregate.folds)


class TestAsOfTimeIntegrity:
    """Category J: regime classification must be evaluated as of each
    fold's own test_end -- never the overall run's end, never "now"."""

    def test_regime_lookup_uses_each_folds_own_test_end(self, monkeypatch) -> None:
        import strategy_research.walk_forward_evaluation as wf_mod

        seen_as_of_times: list[datetime] = []
        original = wf_mod.make_single_point_view

        def spy(repository, as_of_time):
            seen_as_of_times.append(as_of_time)
            return original(repository, as_of_time)

        monkeypatch.setattr(wf_mod, "make_single_point_view", spy)

        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
            regime_subject_id="TRENDUP",
        )
        assert len(seen_as_of_times) == aggregate.fold_count
        assert seen_as_of_times == [f.test_end for f in aggregate.folds]

    def test_regime_state_stays_unknown_when_no_subject_is_given(self) -> None:
        repo = _small_repo()
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
            regime_subject_id=None,
        )
        assert set(aggregate.regime_breakdown) <= {"UNKNOWN"}


class TestCorporateActionAvailability:
    """Category K: a fold whose TEST window contains a real corporate
    action (split/dividend) must still run to completion through the
    same unmodified `BacktestEngine`/point-in-time machinery -- proving
    `run_walk_forward_evaluation` adds no bypass around corporate-action
    handling."""

    def test_fold_spanning_a_split_runs_without_error_and_produces_a_result(self) -> None:
        days = trading_days(date(2020, 1, 2), date(2020, 9, 1))
        closes = [100.0 * (1.0006**i) for i in range(len(days))]
        bars = make_bars("SPLITCO", days, closes)
        split_day = days[len(days) // 2]
        actions = [make_split("SPLITCO", split_day, ratio="2:1"), make_dividend("SPLITCO", days[-5], amount=0.50)]
        repo = InMemoryDataRepository(
            bars=bars, securities=[make_security("SPLITCO", "SPLITCO", valid_from=days_to_utc(date(2020, 1, 2)))],
            corporate_actions=actions, calendars={"US_EQUITY": US_EQUITY},
        )

        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(["SPLITCO"]), ["SPLITCO"],
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2020, 9, 1)),
            train_window_months=3, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        assert aggregate.fold_count >= 1
        for fold in aggregate.folds:
            assert fold.result.net.performance is not None


class TestStrategyParameterImmutability:
    """Category M: a strategy's parameter dataclass must not be
    mutable, and one fold's run must not leak mutated state into the
    next -- `strategy_factory` must be called fresh each time
    (`run_gross_and_net`'s own documented contract), which
    `run_walk_forward_evaluation` respects by construction (it never
    caches or reuses a `Strategy` instance across folds)."""

    def test_parameters_dataclass_is_frozen(self) -> None:
        params = LongTermMomentumParameters()
        with pytest.raises(Exception):
            params.top_n = 999  # type: ignore[misc]

    def test_each_fold_gets_a_freshly_constructed_strategy_instance(self) -> None:
        repo = _small_repo()
        construction_count = 0

        def factory():
            nonlocal construction_count
            construction_count += 1
            return BuyAndHoldStrategy(list(_UNIVERSE))

        aggregate = run_walk_forward_evaluation(
            repo, factory, _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2022, 6, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        # Per fold, `run_gross_and_net` (Phase 23) calls `strategy_factory()`
        # 3 times: once for the gross BacktestEngine, once for the net
        # BacktestEngine, and once more to read `type(...).__name__` for
        # `GrossNetResult.strategy_name` -- plus 1 more call
        # `run_walk_forward_evaluation` itself makes upfront for the
        # aggregate's own `strategy_name`. (Not asserted via id()
        # uniqueness: CPython may legitimately reuse a garbage-collected
        # instance's memory address for the next one -- "fresh" here
        # means "a new constructor call," not "a never-before-seen
        # address.")
        assert construction_count == aggregate.fold_count * 3 + 1


class TestInsufficientHistory:
    def test_returns_zero_fold_aggregate_not_an_error_when_window_too_short(self) -> None:
        repo = _small_repo(date(2020, 1, 2), date(2020, 4, 1))
        aggregate = run_walk_forward_evaluation(
            repo, lambda: BuyAndHoldStrategy(list(_UNIVERSE)), _UNIVERSE,
            overall_start=days_to_utc(date(2020, 1, 2)), overall_end=days_to_utc(date(2020, 4, 1)),
            train_window_months=6, test_window_months=2, step_months=2, initial_capital=10_000.0,
        )
        assert aggregate.fold_count == 0
        assert aggregate.median_net_cumulative_return is None
        assert aggregate.folds == ()
