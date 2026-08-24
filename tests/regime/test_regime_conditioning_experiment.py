"""Category: Regime as a conditioning variable (Phase 5 spec section 9).

This is an illustrative experiment, not a validation of Regime's
usefulness. `PROJECT_MASTER_PLAN.md` section 1.1 explicitly forbids
adopting anything on backtest performance alone, and this phase's own
instruction repeats the same constraint specifically for Regime: "이것을
근거로 Regime이 alpha를 만든다고 주장하지 않는다." Every test in this
file reports the conditioned-vs-unconditioned comparison; **none** of
them assert the conditioned version has higher return, Sharpe, or any
other performance figure -- only that the mechanism runs, produces two
comparable `PerformanceReport`s, and that suppressing BUY orders during a
BEAR trend actually changes turnover/trade count in the expected
*mechanical* direction (fewer trades), which is a statement about what
the wrapper does, not about whether doing it is profitable.
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.experiment import ExperimentTracker
from backtest.strategy import SimpleMomentumStrategy

from regime.enums import SubjectKind
from regime.strategy import RegimeConditionedStrategy

from baseline.report import build_comparison_report, compare_reports


def _scenario():
    import random

    days = trading_days(date(2024, 1, 2), date(2024, 12, 30))
    rng = random.Random(99)
    aaa, bbb = [100.0], [80.0]
    for _ in range(1, len(days)):
        aaa.append(aaa[-1] * (1 + rng.gauss(0.0002, 0.02)))
        bbb.append(bbb[-1] * (1 + rng.gauss(0.0000, 0.018)))
    bars = make_bars("AAA", days, aaa) + make_bars("BBB", days, bbb)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    bench = make_benchmark(days, [4000.0 + i * 0.3 for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA", "BBB"), benchmark_id="SP500", code_version="regime-conditioning-experiment",
    )
    return repo, config


class TestRegimeConditioningExperiment:
    def test_conditioned_and_unconditioned_runs_are_both_valid_and_comparable(self) -> None:
        repo, config = _scenario()
        tracker = ExperimentTracker()

        unconditioned = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        result_unconditioned = BacktestEngine(repo, config, unconditioned, experiment_tracker=tracker).run()

        base = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        conditioned = RegimeConditionedStrategy(base, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result_conditioned = BacktestEngine(repo, config, conditioned, experiment_tracker=tracker).run()

        assert result_unconditioned.is_valid_performance
        assert result_conditioned.is_valid_performance
        assert result_unconditioned.experiment.experiment_id != result_conditioned.experiment.experiment_id

        # Report both side by side -- this is the entire deliverable of
        # the experiment. No assertion here claims one report is
        # "better" than the other.
        table = compare_reports([
            build_comparison_report(_FakeBaselineRun("unconditioned", result_unconditioned)),
            build_comparison_report(_FakeBaselineRun("regime_conditioned", result_conditioned)),
        ])
        assert "unconditioned" in table and "regime_conditioned" in table

    def test_suppressing_buy_orders_never_increases_trade_count(self) -> None:
        """A purely mechanical consequence of the wrapper (it can only
        remove BUY intents, never add or alter them) -- not a claim about
        whether fewer trades is good or bad."""
        repo, config = _scenario()
        tracker = ExperimentTracker()

        unconditioned = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        result_unconditioned = BacktestEngine(repo, config, unconditioned, experiment_tracker=tracker).run()

        base = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        conditioned = RegimeConditionedStrategy(base, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result_conditioned = BacktestEngine(repo, config, conditioned, experiment_tracker=tracker).run()

        assert len(result_conditioned.fills) <= len(result_unconditioned.fills)


class _FakeBaselineRun:
    """Adapts a raw BacktestResult to the shape baseline.report expects,
    without going through baseline.runner (this experiment does not
    persist anything -- it is a one-off illustrative comparison)."""

    def __init__(self, label: str, backtest_result) -> None:
        self.label = label
        self.backtest_result = backtest_result
