"""Category: Monitoring Account Test (Phase 17 -- Production Safety
Review). Closes the Phase 15/ADR-0021 known limitation that
`paper_account_equity`/`paper_pnl`/`paper_drawdown` were computable but
never wired into a `MonitoringEvent`. Additive to Phase 14 -- follows
the exact same collector/metrics/health three-layer pattern every
other component in this package already uses."""

from __future__ import annotations

from monitoring_helpers import make_config, utc

from monitoring.collectors import collect_account
from monitoring.enums import ComponentHealthStatus, MonitoringComponent
from monitoring.health import evaluate_account_health
from monitoring.metrics import compute_account_metrics


class TestComputeAccountMetrics:
    def test_empty_history_is_honestly_none_not_zero(self) -> None:
        metrics = compute_account_metrics([], initial_cash=1_000_000.0)
        assert metrics["count"] == 0.0
        assert metrics["latest_equity"] is None
        assert metrics["drawdown"] is None
        assert metrics["pnl"] is None

    def test_latest_equity_and_pnl(self) -> None:
        history = [(utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 3), 1_050_000.0)]
        metrics = compute_account_metrics(history, initial_cash=1_000_000.0)
        assert metrics["latest_equity"] == 1_050_000.0
        assert metrics["pnl"] == 50_000.0

    def test_pnl_is_none_without_initial_cash(self) -> None:
        history = [(utc(2024, 1, 2), 1_000_000.0)]
        metrics = compute_account_metrics(history)
        assert metrics["pnl"] is None

    def test_drawdown_from_peak(self) -> None:
        history = [(utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 3), 1_200_000.0), (utc(2024, 1, 4), 900_000.0)]
        metrics = compute_account_metrics(history, initial_cash=1_000_000.0)
        assert metrics["peak_equity"] == 1_200_000.0
        assert metrics["drawdown"] == 0.25

    def test_out_of_order_input_is_sorted_before_computing(self) -> None:
        history = [(utc(2024, 1, 4), 900_000.0), (utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 3), 1_200_000.0)]
        metrics = compute_account_metrics(history, initial_cash=1_000_000.0)
        assert metrics["latest_equity"] == 900_000.0  # the chronologically-last point, not the last list entry


class TestEvaluateAccountHealth:
    def test_insufficient_sample_count_is_unknown(self) -> None:
        health = evaluate_account_health(
            sample_count=1, equity=1_000_000.0, drawdown=0.01, max_drawdown=None,
            config=make_config(min_sample_count=5), as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN

    def test_missing_equity_is_unknown(self) -> None:
        health = evaluate_account_health(
            sample_count=10, equity=None, drawdown=None, max_drawdown=None,
            config=make_config(), as_of_time=utc(2024, 1, 2), health_id="H2",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN

    def test_max_drawdown_not_configured_is_healthy_regardless_of_actual_drawdown(self) -> None:
        """`None` means "not enforced" -- the same convention every
        other Optional threshold in this codebase uses. This function
        never invents a default drawdown limit of its own."""
        health = evaluate_account_health(
            sample_count=10, equity=500_000.0, drawdown=0.60, max_drawdown=None,
            config=make_config(), as_of_time=utc(2024, 1, 2), health_id="H3",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

    def test_drawdown_within_configured_max_is_healthy(self) -> None:
        health = evaluate_account_health(
            sample_count=10, equity=900_000.0, drawdown=0.10, max_drawdown=0.20,
            config=make_config(), as_of_time=utc(2024, 1, 2), health_id="H4",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

    def test_drawdown_at_or_beyond_configured_max_is_unavailable(self) -> None:
        health = evaluate_account_health(
            sample_count=10, equity=800_000.0, drawdown=0.20, max_drawdown=0.20,
            config=make_config(), as_of_time=utc(2024, 1, 2), health_id="H5",
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE


class TestCollectAccount:
    def test_event_and_health_component_is_account(self) -> None:
        history = [(utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 3), 1_100_000.0)]
        event, health = collect_account(
            history, initial_cash=1_000_000.0, as_of_time=utc(2024, 1, 3), observed_at=utc(2024, 1, 3),
            config=make_config(min_sample_count=1), event_id="ACCEVT-1", health_id="ACCHEALTH-1",
        )
        assert event.component == MonitoringComponent.ACCOUNT
        assert health.component == MonitoringComponent.ACCOUNT
        assert event.metrics["latest_equity"] == 1_100_000.0
        assert event.metrics["pnl"] == 100_000.0

    def test_future_equity_points_are_never_visible(self) -> None:
        """Point-in-time discipline (instruction section 13) -- an
        equity snapshot dated after as_of_time must not influence the
        health verdict, mirroring every other collector in this file."""
        history = [(utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 10), 50_000.0)]  # a "future" crash
        event, _ = collect_account(
            history, initial_cash=1_000_000.0, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2),
            config=make_config(min_sample_count=1), event_id="ACCEVT-2", health_id="ACCHEALTH-2",
        )
        assert event.metrics["latest_equity"] == 1_000_000.0

    def test_max_drawdown_breach_produces_unavailable_health(self) -> None:
        history = [(utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 3), 700_000.0)]
        _, health = collect_account(
            history, initial_cash=1_000_000.0, as_of_time=utc(2024, 1, 3), observed_at=utc(2024, 1, 3),
            config=make_config(min_sample_count=1), event_id="ACCEVT-3", health_id="ACCHEALTH-3", max_drawdown=0.20,
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE
