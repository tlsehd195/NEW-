"""Category: Benchmark test.

See docs/specifications/PHASE-2-backtesting.md section 9. Confirms
BenchmarkEngine uses the same period/capital as requested and correctly
reports whichever BenchmarkReturnType the underlying data actually has —
it must never assume one (section 9.3, DECISION REQUIRED).
"""

from __future__ import annotations

from datetime import date

import pytest
from backtest_helpers import build_repository, checkpoint, make_benchmark, trading_days

from backtest.benchmark import BenchmarkEngine
from backtest.costs import TransactionCostModel
from data_infra.enums import BenchmarkReturnType


class TestBenchmarkEngine:
    def test_zero_cost_cumulative_return_matches_hand_computation(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 5))
        points = make_benchmark(days, [4000.0, 4040.0, 4000.0, 4200.0])  # +5% total
        repo = build_repository(benchmarks=points)
        engine = BenchmarkEngine(TransactionCostModel(fixed_per_trade=0.0, per_share=0.0, spread_bps=0.0))

        result = engine.compute(
            repo, "SP500", checkpoint(days[0], 0), checkpoint(days[-1]),
            as_of_time=checkpoint(days[-1]), initial_capital=10_000.0,
        )
        assert result is not None
        assert result.cumulative_return == pytest.approx(0.05)
        assert result.final_value == pytest.approx(10_500.0)

    def test_costs_reduce_final_value_relative_to_zero_cost(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 5))[:2]
        points = make_benchmark(days, [4000.0, 4200.0])
        repo = build_repository(benchmarks=points)

        zero_cost = BenchmarkEngine(TransactionCostModel(0.0, 0.0, 0.0)).compute(
            repo, "SP500", checkpoint(days[0], 0), checkpoint(days[1]),
            as_of_time=checkpoint(days[1]), initial_capital=10_000.0,
        )
        with_cost = BenchmarkEngine(TransactionCostModel(fixed_per_trade=5.0, per_share=0.0, spread_bps=10.0)).compute(
            repo, "SP500", checkpoint(days[0], 0), checkpoint(days[1]),
            as_of_time=checkpoint(days[1]), initial_capital=10_000.0,
        )
        assert with_cost.final_value < zero_cost.final_value

    def test_return_type_is_reported_not_assumed(self) -> None:
        from data_infra.models import BenchmarkPoint, Provenance

        days = trading_days(date(2024, 1, 2), date(2024, 1, 3))
        points = [
            BenchmarkPoint(
                benchmark_id="SP500TR", timestamp=checkpoint(d, 0), level=level,
                return_type=BenchmarkReturnType.TOTAL_RETURN, currency="USD",
                available_time=checkpoint(d), ingestion_time=checkpoint(d),
                provenance=Provenance(
                    source="test", source_dataset="test_ds", source_record_id=f"tr-{d.isoformat()}",
                    retrieved_at=checkpoint(d), data_version="v1",
                ),
            )
            for d, level in zip(days, [5000.0, 5050.0])
        ]
        repo = build_repository(benchmarks=points)
        engine = BenchmarkEngine(TransactionCostModel(0.0, 0.0, 0.0))
        result = engine.compute(
            repo, "SP500TR", checkpoint(days[0], 0), checkpoint(days[1]),
            as_of_time=checkpoint(days[1]), initial_capital=10_000.0,
        )
        assert result.return_type == BenchmarkReturnType.TOTAL_RETURN

    def test_fewer_than_two_points_returns_none(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 2))
        points = make_benchmark(days, [4000.0])
        repo = build_repository(benchmarks=points)
        engine = BenchmarkEngine(TransactionCostModel())
        result = engine.compute(
            repo, "SP500", checkpoint(days[0], 0), checkpoint(days[0], 0),
            as_of_time=checkpoint(days[0], 0), initial_capital=10_000.0,
        )
        assert result is None

    def test_uses_requested_initial_capital_not_a_hardcoded_value(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 3))
        points = make_benchmark(days, [4000.0, 4400.0])  # +10%
        repo = build_repository(benchmarks=points)
        engine = BenchmarkEngine(TransactionCostModel(0.0, 0.0, 0.0))

        small = engine.compute(
            repo, "SP500", checkpoint(days[0], 0), checkpoint(days[1]),
            as_of_time=checkpoint(days[1]), initial_capital=1_000.0,
        )
        large = engine.compute(
            repo, "SP500", checkpoint(days[0], 0), checkpoint(days[1]),
            as_of_time=checkpoint(days[1]), initial_capital=100_000.0,
        )
        assert small.cumulative_return == pytest.approx(large.cumulative_return)
        assert small.final_value == pytest.approx(1_100.0)
        assert large.final_value == pytest.approx(110_000.0)
