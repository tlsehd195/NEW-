"""Category: Leakage Test -- instruction section 13: adding a future
observation never changes a past monitoring result; every collector
requires an explicit `as_of_time`; nothing in `monitoring.*` calls
`datetime.now()`/`datetime.utcnow()` or accesses future data implicitly."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import monitoring

from monitoring_helpers import make_bar, make_config, make_decision, make_prediction, utc

from monitoring.collectors import collect_data_quality, collect_decision, collect_prediction


def _package_files():
    return list(Path(monitoring.__file__).parent.rglob("*.py"))


class TestNoWallClockCall:
    def test_no_now_or_utcnow_call_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow"):
                    raise AssertionError(f"{py_file.name} calls datetime.{node.attr}()")


class TestEveryCollectorRequiresExplicitAsOfTime:
    def test_collect_data_quality_as_of_time_has_no_default(self) -> None:
        params = inspect.signature(collect_data_quality).parameters
        assert "as_of_time" in params
        assert params["as_of_time"].default is inspect.Parameter.empty

    def test_collect_prediction_as_of_time_has_no_default(self) -> None:
        params = inspect.signature(collect_prediction).parameters
        assert "as_of_time" in params
        assert params["as_of_time"].default is inspect.Parameter.empty

    def test_collect_decision_as_of_time_has_no_default(self) -> None:
        params = inspect.signature(collect_decision).parameters
        assert "as_of_time" in params
        assert params["as_of_time"].default is inspect.Parameter.empty


class TestFutureObservationDoesNotChangePastResult:
    def test_data_quality_unaffected_by_future_bar(self) -> None:
        config = make_config()
        as_of = utc(2024, 1, 2)
        past_bars = [make_bar(security_id="AAA", timestamp=utc(2024, 1, 1), available_time=utc(2024, 1, 1))]

        event_before, health_before = collect_data_quality(
            past_bars, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )

        future_bar = make_bar(security_id="AAA", timestamp=utc(2024, 1, 5), available_time=utc(2024, 1, 5))
        event_after, health_after = collect_data_quality(
            past_bars + [future_bar], as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )

        assert event_before.metrics == event_after.metrics
        assert health_before.status == health_after.status

    def test_prediction_unaffected_by_future_prediction(self) -> None:
        config = make_config(degraded_min_expected_count=1)
        as_of = utc(2024, 1, 2)
        past = [make_prediction(prediction_id="P1", as_of_time=utc(2024, 1, 1))]

        event_before, _ = collect_prediction(
            past, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )
        future = make_prediction(prediction_id="P2", as_of_time=utc(2024, 1, 10))
        event_after, _ = collect_prediction(
            past + [future], as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )

        assert event_before.metrics == event_after.metrics

    def test_decision_unaffected_by_future_decision(self) -> None:
        config = make_config(degraded_min_expected_count=1)
        as_of = utc(2024, 1, 2)
        past = [make_decision(decision_id="D1", as_of_time=utc(2024, 1, 1))]

        event_before, _ = collect_decision(
            past, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )
        future = make_decision(decision_id="D2", as_of_time=utc(2024, 1, 10))
        event_after, _ = collect_decision(
            past + [future], as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )

        assert event_before.metrics == event_after.metrics

    def test_future_bar_is_actually_excluded_from_source_record_ids(self) -> None:
        config = make_config()
        as_of = utc(2024, 1, 2)
        past_bar = make_bar(security_id="AAA", timestamp=utc(2024, 1, 1), available_time=utc(2024, 1, 1))
        future_bar = make_bar(security_id="BBB", timestamp=utc(2024, 1, 5), available_time=utc(2024, 1, 5))

        event, _ = collect_data_quality(
            [past_bar, future_bar], as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1",
        )
        assert not any("BBB" in rid for rid in event.source_record_ids)
        assert event.metrics["observation_count"] == 1.0
