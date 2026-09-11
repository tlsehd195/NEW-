"""Category: Track A (Phase 32) result decomposition
(strategy_research.result_analysis) -- pure functions over an already-
produced report JSON, no repository/network access. SYNTHETIC fixtures
only, shaped exactly like a real run_long_horizon_validation.py
output's schema -- proves the decomposition math is correct, not a
claim about any real strategy result."""

from __future__ import annotations

import pytest

from strategy_research.result_analysis import (
    analyze_report,
    analyze_strategy,
    benchmark_comparison_summary,
    cost_drag_summary,
    fold_distribution_summary,
    regime_conditional_summary,
)


def _fold(net_return: float, regime: str, sharpe: float = 0.5, gross_return=None) -> dict:
    gross_return = net_return + 0.01 if gross_return is None else gross_return
    return {
        "regime_trend_state": regime,
        "gross": {"cumulative_return": gross_return, "turnover": 1.0},
        "net": {
            "cumulative_return": net_return, "sharpe_ratio": sharpe,
            "turnover": 1.0, "total_transaction_cost": 5.0,
        },
    }


class TestFoldDistributionSummary:
    def test_win_rate_and_distribution_stats(self) -> None:
        folds = [_fold(0.05, "BULL"), _fold(-0.02, "BEAR"), _fold(0.03, "BULL")]
        summary = fold_distribution_summary(folds)
        assert summary.fold_count == 3
        assert summary.win_rate == 2 / 3
        assert summary.worst_return == -0.02
        assert summary.best_return == 0.05
        assert summary.mean_return == (0.05 - 0.02 + 0.03) / 3

    def test_empty_folds_produces_all_none_not_fabricated_zero(self) -> None:
        summary = fold_distribution_summary([])
        assert summary.fold_count == 0
        assert summary.win_rate is None
        assert summary.mean_return is None
        assert summary.stdev_return is None

    def test_median_on_an_even_fold_count_averages_the_two_middle_values(self) -> None:
        # ADR-0117: `sorted(returns)[len(returns) // 2]` picks the
        # UPPER of the two middle values on an even-length list instead
        # of averaging them -- e.g. for [0.01, 0.02, 0.03, 0.04] it
        # returned 0.03 (index 2) instead of the true median 0.025,
        # a systematic upward bias whenever fold_count is even (a
        # common, not edge, case for a real walk-forward run).
        folds = [_fold(0.04, "BULL"), _fold(0.01, "BEAR"), _fold(0.03, "BULL"), _fold(0.02, "BULL")]
        summary = fold_distribution_summary(folds)
        assert summary.median_return == pytest.approx(0.025)

    def test_median_on_an_odd_fold_count_is_the_middle_value(self) -> None:
        folds = [_fold(0.05, "BULL"), _fold(-0.02, "BEAR"), _fold(0.03, "BULL")]
        summary = fold_distribution_summary(folds)
        assert summary.median_return == pytest.approx(0.03)


class TestRegimeConditionalSummary:
    def test_buckets_by_regime_and_computes_per_bucket_win_rate(self) -> None:
        folds = [
            _fold(0.05, "BULL"), _fold(0.03, "BULL"), _fold(-0.01, "BULL"),
            _fold(-0.04, "BEAR"), _fold(-0.02, "BEAR"),
        ]
        buckets = {b.regime: b for b in regime_conditional_summary(folds)}
        assert buckets["BULL"].fold_count == 3
        assert buckets["BULL"].win_rate == 2 / 3
        assert buckets["BEAR"].fold_count == 2
        assert buckets["BEAR"].win_rate == 0.0

    def test_no_folds_produces_no_buckets(self) -> None:
        assert regime_conditional_summary([]) == ()


class TestCostDragSummary:
    def test_drag_is_gross_minus_net(self) -> None:
        perf = {"gross": {"cumulative_return": 0.30}, "net": {"cumulative_return": 0.22, "turnover": 9.4, "total_transaction_cost": 300.0}}
        summary = cost_drag_summary(perf)
        assert summary.cost_drag == pytest.approx(0.08)
        assert summary.turnover == 9.4
        assert summary.total_transaction_cost == 300.0


class TestBenchmarkComparisonSummary:
    def test_extracts_excess_return_fields_unchanged(self) -> None:
        net_perf = {
            "cumulative_return": 0.04, "cagr": 0.012, "max_drawdown": -0.39,
            "benchmark_cumulative_return": 0.93, "benchmark_cagr": 0.218,
            "excess_return": -0.89, "annualized_excess_return": -0.207,
            "benchmark_max_drawdown": -0.19,
        }
        summary = benchmark_comparison_summary(net_perf)
        assert summary.strategy_net_cumulative_return == 0.04
        assert summary.benchmark_cumulative_return == 0.93
        assert summary.excess_return == -0.89

    def test_missing_benchmark_fields_stay_none_not_fabricated(self) -> None:
        # BENCHMARK_UNAVAILABLE case -- the original run's own convention.
        net_perf = {"cumulative_return": 0.04, "cagr": 0.012, "max_drawdown": -0.39}
        summary = benchmark_comparison_summary(net_perf)
        assert summary.benchmark_cumulative_return is None
        assert summary.excess_return is None


class TestAnalyzeStrategy:
    def _report_result(self, *, with_drawdown_field: bool, with_concentration: bool) -> dict:
        held_out_net = {
            "cumulative_return": 0.04, "cagr": 0.012, "max_drawdown": -0.39,
            "turnover": 7.5, "total_transaction_cost": 97.6,
            "benchmark_cumulative_return": 0.93, "benchmark_cagr": 0.218,
            "excess_return": -0.89, "annualized_excess_return": -0.207,
            "benchmark_max_drawdown": -0.19,
        }
        if with_drawdown_field:
            held_out_net["max_drawdown_duration_days"] = 412
        held_out = {"gross": {"cumulative_return": 0.05, "turnover": 7.5}, "net": held_out_net, "num_trades_net": 51}
        if with_concentration:
            held_out["concentration"] = {"herfindahl_index": 0.3}
        return {
            "walk_forward": {"folds": [_fold(0.02, "BULL"), _fold(-0.01, "BEAR")]},
            "held_out_test": held_out,
            "evidence_assessment": {
                "level": "ROBUSTNESS_PENDING", "reason": "test reason",
                "pbo_probability": 0.0, "deflated_sharpe_ratio": 0.988, "positive_fold_ratio": 0.55,
            },
        }

    def test_drawdown_field_absent_is_distinguished_from_zero_drawdown(self) -> None:
        result = self._report_result(with_drawdown_field=False, with_concentration=False)
        analysis = analyze_strategy("risk_controlled_momentum", result)
        assert analysis.held_out_drawdown_field_present is False
        assert analysis.held_out_drawdown_duration_days is None

    def test_drawdown_field_present_is_extracted(self) -> None:
        result = self._report_result(with_drawdown_field=True, with_concentration=False)
        analysis = analyze_strategy("risk_controlled_momentum", result)
        assert analysis.held_out_drawdown_field_present is True
        assert analysis.held_out_drawdown_duration_days == 412

    def test_concentration_presence_is_flagged(self) -> None:
        no_conc = analyze_strategy("x", self._report_result(with_drawdown_field=False, with_concentration=False))
        with_conc = analyze_strategy("x", self._report_result(with_drawdown_field=False, with_concentration=True))
        assert no_conc.held_out_concentration_present is False
        assert with_conc.held_out_concentration_present is True

    def test_evidence_fields_are_passed_through(self) -> None:
        result = self._report_result(with_drawdown_field=False, with_concentration=False)
        analysis = analyze_strategy("x", result)
        assert analysis.evidence_level == "ROBUSTNESS_PENDING"
        assert analysis.pbo_probability == 0.0
        assert analysis.deflated_sharpe_ratio == 0.988

    def test_no_held_out_test_produces_none_comparisons_not_crash(self) -> None:
        result = {"walk_forward": {"folds": [_fold(0.02, "BULL")]}, "evidence_assessment": {}}
        analysis = analyze_strategy("x", result)
        assert analysis.held_out_cost_drag is None
        assert analysis.held_out_benchmark_comparison is None
        assert analysis.held_out_concentration_present is False


class TestAnalyzeReport:
    def test_analyzes_every_strategy_in_sorted_order(self) -> None:
        report = {
            "results": {
                "trend_volatility": {"walk_forward": {"folds": [_fold(0.01, "BULL")]}, "evidence_assessment": {}},
                "buy_and_hold": {"walk_forward": {"folds": [_fold(0.02, "BULL")]}, "evidence_assessment": {}},
            }
        }
        analyses = analyze_report(report)
        assert [a.strategy_name for a in analyses] == ["buy_and_hold", "trend_volatility"]
