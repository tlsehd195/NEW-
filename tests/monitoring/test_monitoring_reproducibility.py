"""Category: Reproducibility Test -- identical inputs produce identical
outputs everywhere in `monitoring.*`, and no module uses `random`."""

from __future__ import annotations

import ast
from pathlib import Path

import monitoring

from monitoring_helpers import make_bar, make_config, make_risk_result, utc

from monitoring.collectors import collect_data_quality, collect_risk
from monitoring.drift import detect_mean_shift
from monitoring.enums import MonitoringComponent
from monitoring.health import evaluate_health_from_failure_rate


def _package_files():
    return list(Path(monitoring.__file__).parent.rglob("*.py"))


class TestNoRandomImport:
    def test_no_random_import_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "random", f"{py_file.name} imports random"
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    raise AssertionError(f"{py_file.name} imports from random")


class TestDeterministicHealth:
    def test_same_inputs_produce_identical_health(self) -> None:
        config = make_config()
        h1 = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.2, sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        h2 = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.2, sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert h1 == h2


class TestDeterministicDrift:
    def test_same_inputs_produce_identical_drift_result(self) -> None:
        config = make_config(min_drift_sample_count=5)
        baseline, current = [1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 3.0, 4.0, 5.0, 6.0]
        r1 = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        r2 = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert r1 == r2


class TestDeterministicCollectors:
    def test_collect_data_quality_is_deterministic(self) -> None:
        config = make_config()
        bars = [make_bar(security_id="AAA", timestamp=utc(2024, 1, 1), available_time=utc(2024, 1, 1))]
        as_of = utc(2024, 1, 2)

        e1, h1 = collect_data_quality(bars, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")
        e2, h2 = collect_data_quality(bars, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")
        assert e1 == e2
        assert h1 == h2

    def test_collect_risk_is_deterministic(self) -> None:
        config = make_config()
        results = [make_risk_result(risk_id="R1", as_of_time=utc(2024, 1, 1))]
        as_of = utc(2024, 1, 2)

        e1, h1 = collect_risk(results, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")
        e2, h2 = collect_risk(results, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")
        assert e1 == e2
        assert h1 == h2
