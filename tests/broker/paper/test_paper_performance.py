"""Category: Paper Performance Test (Phase 18). Every insufficient-data/
undefined-ratio branch is exercised explicitly -- a fabricated `0.0`
anywhere here would be a regression against the module's own stated
contract (never guess a missing number)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from backtest.benchmark import BenchmarkResult
from backtest.enums import OrderSide
from backtest.fills import Fill
from broker.paper.performance import (
    BenchmarkComparison,
    PaperPerformanceConfig,
    compute_paper_performance_report,
)
from data_infra.enums import BenchmarkReturnType
from trade_journal.enums import TradeProvenance
from trade_journal.models import TradeRecord


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _fill(*, side=OrderSide.BUY, quantity=10.0, price=100.0, execution_time=utc(2024, 1, 2), slippage_cost=0.5, commission=1.0, spread_cost=0.2) -> Fill:
    return Fill(
        order_id="CID-1", security_id="AAA", side=side, quantity=quantity, reference_price=price - slippage_cost,
        price=price, commission=commission, spread_cost=spread_cost, slippage_cost=slippage_cost,
        decision_time=execution_time, execution_time=execution_time, data_version="dv-1",
    )


def _trade(
    *, trade_id="TRD-1", side=OrderSide.BUY, quantity=10.0, price=100.0, execution_time=utc(2024, 1, 2),
    realized_pnl=None, realized_return=None, slippage=0.5, transaction_cost=1.2,
) -> TradeRecord:
    fill = _fill(side=side, quantity=quantity, price=price, execution_time=execution_time, slippage_cost=slippage)
    return TradeRecord(
        trade_id=trade_id, decision_id="DEC-1", order_id="CID-1", security_id="AAA", timestamp=execution_time,
        side=side, quantity=quantity, execution_price=price, reference_price=price - slippage, slippage=slippage,
        transaction_cost=transaction_cost, position_after=quantity, fill=fill, realized_pnl=realized_pnl,
        realized_return=realized_return, provenance=TradeProvenance.PAPER_TRADING,
    )


def _rising_equity(n=10, start=1_000_000.0, daily_return=0.001):
    history = []
    value = start
    for i in range(n):
        history.append((utc(2024, 1, 1 + i), value))
        value *= (1 + daily_return)
    return history


class TestInsufficientData:
    def test_empty_equity_history_marks_everything_insufficient(self) -> None:
        report = compute_paper_performance_report(
            report_id="R1", paper_session_id="S1", equity_history=[], trades=[], evaluated_at=utc(2024, 1, 2),
        )
        assert report.total_return is None
        assert report.reasons["total_return"] == "insufficient_data"
        assert report.reasons["sharpe_ratio"] == "insufficient_data"
        assert report.num_trades == 0

    def test_single_equity_point_is_insufficient(self) -> None:
        report = compute_paper_performance_report(
            report_id="R2", paper_session_id="S1", equity_history=[(utc(2024, 1, 2), 1_000_000.0)],
            trades=[], evaluated_at=utc(2024, 1, 2),
        )
        assert report.total_return is None
        assert report.reasons["total_return"] == "insufficient_data"

    def test_zero_trades_leaves_win_rate_and_avg_trade_return_none(self) -> None:
        report = compute_paper_performance_report(
            report_id="R3", paper_session_id="S1", equity_history=_rising_equity(), trades=[],
            evaluated_at=utc(2024, 1, 20),
        )
        assert report.win_rate is None
        assert report.avg_trade_return is None
        assert report.realized_pnl is None
        assert report.reasons["win_rate"] == "insufficient_data"

    def test_fewer_periods_than_min_periods_for_ratios_leaves_ratios_none(self) -> None:
        report = compute_paper_performance_report(
            report_id="R4", paper_session_id="S1",
            equity_history=[(utc(2024, 1, 1), 1_000_000.0), (utc(2024, 1, 2), 1_010_000.0)],
            trades=[], evaluated_at=utc(2024, 1, 2), config=PaperPerformanceConfig(min_periods_for_ratios=5),
        )
        assert report.volatility is None
        assert report.sharpe_ratio is None
        assert report.reasons["volatility"] == "insufficient_data"
        assert report.total_return is not None  # total_return only needs 2 points, unlike the ratios


class TestZeroDenominatorCases:
    def test_zero_volatility_constant_returns_leaves_sharpe_none(self) -> None:
        flat = [(utc(2024, 1, 1 + i), 1_000_000.0) for i in range(10)]  # never moves -- zero variance
        report = compute_paper_performance_report(
            report_id="R5", paper_session_id="S1", equity_history=flat, trades=[], evaluated_at=utc(2024, 1, 10),
        )
        assert report.volatility == 0.0  # a real, computed zero -- not missing data
        assert report.sharpe_ratio is None
        assert report.reasons["sharpe_ratio"] == "zero_volatility"

    def test_never_negative_returns_leaves_sortino_none_zero_downside(self) -> None:
        rising = _rising_equity(n=10, daily_return=0.002)  # monotonically up -- no downside periods at all
        report = compute_paper_performance_report(
            report_id="R6", paper_session_id="S1", equity_history=rising, trades=[], evaluated_at=utc(2024, 1, 10),
        )
        assert report.sortino_ratio is None
        assert report.reasons["sortino_ratio"] == "zero_downside_deviation"

    def test_zero_max_drawdown_leaves_calmar_none(self) -> None:
        rising = _rising_equity(n=10, daily_return=0.001)
        report = compute_paper_performance_report(
            report_id="R7", paper_session_id="S1", equity_history=rising, trades=[], evaluated_at=utc(2024, 1, 10),
        )
        assert report.max_drawdown == 0.0
        assert report.calmar_ratio is None
        assert report.reasons["calmar_ratio"] == "zero_drawdown"


class TestRealizedTradeEconomics:
    def test_win_rate_and_avg_trade_return_and_realized_pnl(self) -> None:
        trades = [
            _trade(trade_id="T1", side=OrderSide.SELL, realized_pnl=100.0, realized_return=0.05),
            _trade(trade_id="T2", side=OrderSide.SELL, realized_pnl=-40.0, realized_return=-0.02),
        ]
        report = compute_paper_performance_report(
            report_id="R8", paper_session_id="S1", equity_history=_rising_equity(), trades=trades,
            evaluated_at=utc(2024, 1, 20),
        )
        assert report.num_trades == 2
        assert report.win_rate == 0.5
        assert report.realized_pnl == 60.0
        assert report.avg_trade_return == (0.05 + -0.02) / 2

    def test_transaction_cost_and_slippage_are_summed_from_trade_journal_not_fabricated(self) -> None:
        trades = [
            _trade(trade_id="T1", transaction_cost=1.2, slippage=0.5),
            _trade(trade_id="T2", transaction_cost=1.4, slippage=0.6),
        ]
        report = compute_paper_performance_report(
            report_id="R9", paper_session_id="S1", equity_history=_rising_equity(), trades=trades,
            evaluated_at=utc(2024, 1, 20),
        )
        assert report.total_transaction_cost == 1.2 + 1.4
        assert report.total_slippage == 0.5 + 0.6

    def test_open_position_with_no_realized_pnl_is_excluded_from_win_rate_but_present_in_costs(self) -> None:
        opening_trade = _trade(trade_id="T1", side=OrderSide.BUY, realized_pnl=None, realized_return=None)
        report = compute_paper_performance_report(
            report_id="R10", paper_session_id="S1", equity_history=_rising_equity(), trades=[opening_trade],
            evaluated_at=utc(2024, 1, 20),
        )
        assert report.num_trades == 1
        assert report.win_rate is None  # no closed trade to compute a rate over
        assert report.total_transaction_cost is not None  # cost is known even for an open position


class TestTurnoverIsPassthroughNeverRecomputed:
    def test_turnover_none_when_not_supplied(self) -> None:
        report = compute_paper_performance_report(
            report_id="R11", paper_session_id="S1", equity_history=_rising_equity(), trades=[],
            evaluated_at=utc(2024, 1, 20),
        )
        assert report.turnover is None
        assert report.reasons["turnover"] == "not_supplied"

    def test_turnover_zero_is_a_real_value_not_a_missing_one(self) -> None:
        report = compute_paper_performance_report(
            report_id="R12", paper_session_id="S1", equity_history=_rising_equity(), trades=[],
            evaluated_at=utc(2024, 1, 20), turnover=0.0,
        )
        assert report.turnover == 0.0
        assert "turnover" not in report.reasons


class TestBenchmark:
    def test_no_benchmark_is_explicitly_unavailable(self) -> None:
        report = compute_paper_performance_report(
            report_id="R13", paper_session_id="S1", equity_history=_rising_equity(), trades=[],
            evaluated_at=utc(2024, 1, 20),
        )
        assert report.benchmark.status == "BENCHMARK_UNAVAILABLE"
        assert report.benchmark.benchmark_cumulative_return is None

    def test_benchmark_available_computes_excess_return(self) -> None:
        benchmark = BenchmarkResult(
            benchmark_id="SPX", return_type=BenchmarkReturnType.PRICE_RETURN, start=utc(2024, 1, 1),
            end=utc(2024, 1, 10), initial_capital=1_000_000.0, final_value=1_020_000.0,
            cumulative_return=0.02, cagr=0.9, max_drawdown=-0.01, value_series=(),
        )
        equity = _rising_equity(n=10, daily_return=0.001)
        report = compute_paper_performance_report(
            report_id="R14", paper_session_id="S1", equity_history=equity, trades=[],
            evaluated_at=utc(2024, 1, 10), benchmark=benchmark,
        )
        assert report.benchmark.status == "AVAILABLE"
        assert report.benchmark.excess_return == report.total_return - 0.02

    def test_benchmark_comparison_rejects_unavailable_with_a_value(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            BenchmarkComparison(status="BENCHMARK_UNAVAILABLE", benchmark_cumulative_return=0.1)


class TestDeterminism:
    def test_same_inputs_produce_equal_reports(self) -> None:
        equity = _rising_equity()
        trades = [_trade(trade_id="T1", side=OrderSide.SELL, realized_pnl=10.0, realized_return=0.01)]
        kwargs = dict(
            report_id="R15", paper_session_id="S1", equity_history=copy.deepcopy(equity),
            trades=list(trades), evaluated_at=utc(2024, 1, 20),
        )
        r1 = compute_paper_performance_report(**kwargs)
        r2 = compute_paper_performance_report(**kwargs)
        assert r1 == r2

    def test_reordered_equity_history_input_produces_identical_result(self) -> None:
        equity = _rising_equity()
        shuffled = list(reversed(equity))
        r1 = compute_paper_performance_report(
            report_id="R16", paper_session_id="S1", equity_history=equity, trades=[], evaluated_at=utc(2024, 1, 20),
        )
        r2 = compute_paper_performance_report(
            report_id="R16", paper_session_id="S1", equity_history=shuffled, trades=[], evaluated_at=utc(2024, 1, 20),
        )
        assert r1.total_return == r2.total_return
        assert r1.sharpe_ratio == r2.sharpe_ratio


class TestNoRandomnessUsed:
    def test_module_does_not_import_random(self) -> None:
        import ast
        import broker.paper.performance as perf_module
        from pathlib import Path

        tree = ast.parse(Path(perf_module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module]
                assert "random" not in names


class TestValidation:
    def test_naive_evaluated_at_is_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            compute_paper_performance_report(
                report_id="R17", paper_session_id="S1", equity_history=[], trades=[],
                evaluated_at=datetime(2024, 1, 2),
            )

    def test_empty_report_id_is_rejected(self) -> None:
        import pytest
        from broker.paper.performance import PaperPerformanceReport

        with pytest.raises(ValueError):
            PaperPerformanceReport(
                report_id="", paper_session_id="S1", evaluated_at=utc(2024, 1, 2), period_start=None,
                period_end=None, total_return=None, cagr=None, volatility=None, sharpe_ratio=None,
                sortino_ratio=None, calmar_ratio=None, max_drawdown=None, turnover=None,
                total_transaction_cost=None, total_slippage=None, num_trades=0, win_rate=None,
                avg_trade_return=None, realized_pnl=None,
                benchmark=BenchmarkComparison(status="BENCHMARK_UNAVAILABLE"), configuration_version="cfg-1",
            )
