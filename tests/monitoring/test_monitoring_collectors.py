"""Category: Unit Test (Collectors) -- each `collectors.py` function
filters to `as_of_time`, computes metrics, evaluates health, and
assembles a `MonitoringEvent` whose `severity` matches the resulting
`ComponentHealth.status`."""

from __future__ import annotations

from monitoring_helpers import (
    make_ai_response, make_bar, make_broker_response, make_config, make_decision, make_lineage,
    make_prediction, make_risk_result, make_sizing_result, make_training_dataset, make_transition, utc,
)

from monitoring.collectors import (
    collect_ai_gateway,
    collect_broker,
    collect_data_quality,
    collect_decision,
    collect_learning,
    collect_model_evolution,
    collect_prediction,
    collect_risk,
    collect_sizing,
)
from monitoring.enums import AlertSeverity, ComponentHealthStatus, MonitoringComponent


class TestSeverityMatchesHealth:
    def test_data_quality_healthy_maps_to_info(self) -> None:
        config = make_config(min_sample_count=1)
        bars = [make_bar(available_time=utc(2024, 1, 1))]
        event, health = collect_data_quality(
            bars, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY
        assert event.severity == AlertSeverity.INFO

    def test_broker_unavailable_maps_to_critical(self) -> None:
        config = make_config(min_sample_count=1, unavailable_failure_rate_threshold=0.5)
        responses = [make_broker_response(response_id=f"B{i}", status="ERROR") for i in range(5)]
        event, health = collect_broker(
            responses, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE
        assert event.severity == AlertSeverity.CRITICAL

    def test_prediction_unavailable_when_no_predictions(self) -> None:
        config = make_config()
        event, health = collect_prediction(
            [], as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE
        assert event.component == MonitoringComponent.PREDICTION


class TestCollectDecisionExistenceHealth:
    def test_hold_only_decisions_are_still_healthy(self) -> None:
        from trade_journal.enums import DecisionAction

        config = make_config(degraded_min_expected_count=1)
        decisions = [make_decision(decision_id="D1", action=DecisionAction.HOLD)]
        event, health = collect_decision(
            decisions, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY
        assert event.metrics["hold_rate"] == 1.0


class TestCollectSizingFailureRate:
    def test_reject_and_unknown_combine_into_failure_rate(self) -> None:
        from risk.enums import RiskCheckStatus

        config = make_config(min_sample_count=1, degraded_failure_rate_threshold=0.1)
        results = [
            make_sizing_result(sizing_id="S1", status=RiskCheckStatus.PASS),
            make_sizing_result(sizing_id="S2", status=RiskCheckStatus.REJECT),
        ]
        event, health = collect_sizing(
            results, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert event.metrics["failure_rate"] == 0.5
        assert health.status != ComponentHealthStatus.HEALTHY


class TestCollectRisk:
    def test_all_pass_is_healthy(self) -> None:
        config = make_config(min_sample_count=1)
        results = [make_risk_result(risk_id="R1")]
        event, health = collect_risk(
            results, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY


class TestCollectAIGateway:
    def test_success_only_is_healthy(self) -> None:
        config = make_config(min_sample_count=1)
        responses = [make_ai_response(response_id="A1")]
        event, health = collect_ai_gateway(
            responses, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config, event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY
        assert event.metrics["success_rate"] == 1.0


class TestCollectLearningAndModelEvolution:
    def test_learning_healthy_when_dataset_produced(self) -> None:
        config = make_config(degraded_min_expected_count=1)
        datasets = [make_training_dataset(dataset_id="TDS-1")]
        event, health = collect_learning(
            datasets, [], [], as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config,
            event_id="E1", health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

    def test_model_evolution_lineage_with_none_recorded_at_is_kept(self) -> None:
        config = make_config(degraded_min_expected_count=1)
        transitions = [make_transition(transition_id="T1")]
        lineages = [make_lineage(candidate_id="C1", recorded_at=None)]
        event, health = collect_model_evolution(
            transitions, lineages, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config,
            event_id="E1", health_id="H1",
        )
        assert event.metrics["lineage_count"] == 1.0

    def test_model_evolution_lineage_with_future_recorded_at_is_excluded(self) -> None:
        config = make_config(degraded_min_expected_count=1)
        transitions = [make_transition(transition_id="T1")]
        lineages = [make_lineage(candidate_id="C1", recorded_at=utc(2024, 1, 10))]
        event, health = collect_model_evolution(
            transitions, lineages, as_of_time=utc(2024, 1, 2), observed_at=utc(2024, 1, 2), config=config,
            event_id="E1", health_id="H1",
        )
        assert event.metrics["lineage_count"] == 0.0
