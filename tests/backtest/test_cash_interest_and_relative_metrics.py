"""ADR-0229: cash earns the 3-month T-bill yield when the engine is given
one, and the performance report carries beta, tracking error,
information ratio and Jensen's alpha against the benchmark."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.metrics import benchmark_relative_metrics
from backtest.risk_free import RiskFreeRates
from backtest.strategy import BuyAndHoldStrategy


class _Idle:
    def generate_orders(self, as_of_time, data, portfolio):
        return []


def _daily_rates(start: date, end: date, percent: float) -> RiskFreeRates:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return RiskFreeRates([(d, percent) for d in days], source="test")


def _run(strategy, days, *, cash_interest=None, benchmark=False, closes=None):
    closes = closes or [100.0] * len(days)
    repo = build_repository(
        bars=make_bars("AAA", days, closes), securities=[make_security("AAA", "AAA")],
        benchmarks=make_benchmark(days, closes) if benchmark else (),
    )
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=10_000.0,
        security_ids=("AAA",), benchmark_id="SP500" if benchmark else None, cash_interest=cash_interest,
    )
    return BacktestEngine(repo, config, strategy).run()


class TestCashInterest:
    def test_idle_cash_compounds_daily_on_actual_365(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 3, 29))
        result = _run(_Idle(), days, cash_interest=_daily_rates(date(2023, 12, 1), date(2024, 4, 30), 3.65))
        elapsed = (days[-1] - days[0]).days
        assert result.performance.cumulative_return == pytest.approx((1 + 0.0365 / 365) ** elapsed - 1)
        assert result.is_valid_performance

    def test_without_a_rate_source_cash_earns_nothing(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        assert _run(_Idle(), days).performance.cumulative_return == 0.0

    def test_a_gap_longer_than_the_staleness_cap_earns_nothing_and_warns(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        result = _run(_Idle(), days, cash_interest=_daily_rates(date(2023, 6, 1), date(2023, 6, 30), 5.0))
        assert result.performance.cumulative_return == 0.0
        assert any(i.check == "cash_interest_rate_missing" for i in result.integrity.issues)

    def test_the_rate_source_changes_the_configuration_hash(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        rates = _daily_rates(date(2023, 12, 1), date(2024, 2, 29), 5.0)
        plain = _run(_Idle(), days).experiment.configuration_version
        assert _run(_Idle(), days, cash_interest=rates).experiment.configuration_version != plain


class TestLatestAnnualRateBefore:
    def test_uses_the_day_before_not_the_day_itself(self) -> None:
        rates = RiskFreeRates([(date(2024, 1, 2), 5.0), (date(2024, 1, 3), 4.0)], source="t")
        assert rates.latest_annual_rate_before(date(2024, 1, 3)) == pytest.approx(0.05)

    def test_carries_over_short_gaps_only(self) -> None:
        rates = RiskFreeRates([(date(2024, 1, 2), 5.0)], source="t")
        assert rates.latest_annual_rate_before(date(2024, 1, 12)) == pytest.approx(0.05)
        assert rates.latest_annual_rate_before(date(2024, 1, 13)) is None
        assert rates.latest_annual_rate_before(date(2024, 1, 2)) is None


def _series(values, start=datetime(2024, 1, 2, tzinfo=timezone.utc)):
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


class TestBenchmarkRelativeMetrics:
    def test_a_twice_levered_copy_has_beta_two(self) -> None:
        bench_returns = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02]
        bench, port = [100.0], [100.0]
        for r in bench_returns:
            bench.append(bench[-1] * (1 + r))
            port.append(port[-1] * (1 + 2 * r))
        m = benchmark_relative_metrics(_series(port), _series(bench))
        assert m.beta == pytest.approx(2.0)
        assert m.jensen_alpha == pytest.approx(0.0, abs=1e-12)
        assert m.tracking_error > 0

    def test_the_benchmark_itself_has_no_active_risk(self) -> None:
        bench = _series([100.0, 101.0, 99.0, 102.0])
        m = benchmark_relative_metrics(bench, bench)
        assert m.beta == pytest.approx(1.0)
        assert m.tracking_error == pytest.approx(0.0)
        assert m.information_ratio is None

    def test_dates_are_matched_ignoring_time_of_day(self) -> None:
        port = [(t.replace(hour=20), v) for t, v in _series([100.0, 102.0, 101.0])]
        bench = [(t.replace(hour=1), v) for t, v in _series([100.0, 101.0, 100.5])]
        assert benchmark_relative_metrics(port, bench).beta is not None

    def test_too_few_common_days_returns_none(self) -> None:
        m = benchmark_relative_metrics(_series([100.0, 101.0]), _series([100.0, 101.0]))
        assert m.beta is None and m.tracking_error is None

    def test_engine_report_carries_the_metrics(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 2, 29))
        closes = [100.0 + (i % 5) - 2 + i * 0.1 for i in range(len(days))]
        result = _run(BuyAndHoldStrategy(["AAA"]), days, benchmark=True, closes=closes)
        assert result.performance.beta is not None
        assert result.performance.beta == pytest.approx(1.0, abs=0.1)

    def test_no_benchmark_leaves_them_none(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        assert _run(_Idle(), days).performance.beta is None
