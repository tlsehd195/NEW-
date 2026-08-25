"""Category: Unit Test (Metrics) -- every `metrics.py` function is a
pure function of its input sequence: empty input never fabricates a
`0.0`, and a metric with no finite observations is `None`."""

from __future__ import annotations

from monitoring_helpers import (
    make_ai_response, make_bar, make_broker_request, make_broker_response, make_candidate, make_decision,
    make_evaluation, make_lineage, make_prediction, make_risk_result, make_sizing_result, make_training_dataset,
    make_transition, utc,
)

from ai_gateway.enums import RequestStatus

from monitoring.metrics import (
    compute_ai_gateway_metrics,
    compute_broker_metrics,
    compute_data_quality_metrics,
    compute_decision_metrics,
    compute_learning_metrics,
    compute_model_evolution_metrics,
    compute_prediction_metrics,
    compute_risk_metrics,
    compute_sizing_metrics,
)

from risk.enums import RiskCheckStatus

from trade_journal.enums import DecisionAction


class TestEmptyInputNeverFabricatesAValue:
    def test_data_quality_empty(self) -> None:
        m = compute_data_quality_metrics([])
        assert m["observation_count"] == 0.0
        assert m["invalid_rate"] is None
        assert m["latest_available_time"] is None

    def test_prediction_empty(self) -> None:
        m = compute_prediction_metrics([])
        assert m["count"] == 0.0
        assert m["confidence_mean"] is None

    def test_decision_empty(self) -> None:
        m = compute_decision_metrics([])
        assert m["count"] == 0.0
        assert m["buy_rate"] is None

    def test_sizing_empty(self) -> None:
        m = compute_sizing_metrics([])
        assert m["count"] == 0.0
        assert m["pass_rate"] is None

    def test_risk_empty(self) -> None:
        m = compute_risk_metrics([])
        assert m["count"] == 0.0
        assert m["failure_rate"] is None

    def test_broker_empty(self) -> None:
        m = compute_broker_metrics([])
        assert m["count"] == 0.0
        assert m["failure_rate"] is None
        assert m["duplicate_client_order_id_count"] is None

    def test_ai_gateway_empty(self) -> None:
        m = compute_ai_gateway_metrics([])
        assert m["count"] == 0.0
        assert m["success_rate"] is None

    def test_learning_empty(self) -> None:
        m = compute_learning_metrics([], [], [])
        assert m["dataset_count"] == 0.0
        assert m["mean_dataset_sample_count"] is None

    def test_model_evolution_empty(self) -> None:
        m = compute_model_evolution_metrics([], [])
        assert m["transition_count"] == 0.0
        assert m["pass_rate"] is None


class TestDataQualityMetrics:
    def test_invalid_rate_counts_non_finite_ohlcv(self) -> None:
        good = make_bar(security_id="AAA", timestamp=utc(2024, 1, 2))
        import dataclasses

        bad = dataclasses.replace(make_bar(security_id="BBB", timestamp=utc(2024, 1, 2)), close=float("nan"))
        m = compute_data_quality_metrics([good, bad])
        assert m["observation_count"] == 2.0
        assert m["invalid_rate"] == 0.5

    def test_duplicate_rate(self) -> None:
        b1 = make_bar(security_id="AAA", timestamp=utc(2024, 1, 2))
        b2 = make_bar(security_id="AAA", timestamp=utc(2024, 1, 2))
        m = compute_data_quality_metrics([b1, b2])
        assert m["duplicate_rate"] == 0.5

    def test_timestamp_violation_rate(self) -> None:
        b1 = make_bar(security_id="AAA", timestamp=utc(2024, 1, 3))
        b2 = make_bar(security_id="AAA", timestamp=utc(2024, 1, 2))  # out of order after b1
        m = compute_data_quality_metrics([b1, b2])
        assert m["timestamp_violation_rate"] == 0.5

    def test_latest_available_time_is_the_max(self) -> None:
        b1 = make_bar(available_time=utc(2024, 1, 2))
        b2 = make_bar(available_time=utc(2024, 1, 3))
        m = compute_data_quality_metrics([b1, b2])
        assert m["latest_available_time"] == utc(2024, 1, 3)


class TestPredictionMetrics:
    def test_missing_rate_counts_none_expected_return(self) -> None:
        p1 = make_prediction(prediction_id="P1", expected_return=0.01)
        p2 = make_prediction(prediction_id="P2", expected_return=None)
        m = compute_prediction_metrics([p1, p2])
        assert m["missing_rate"] == 0.5

    def test_confidence_mean(self) -> None:
        p1 = make_prediction(prediction_id="P1", confidence=0.5)
        p2 = make_prediction(prediction_id="P2", confidence=0.9)
        m = compute_prediction_metrics([p1, p2])
        assert m["confidence_mean"] == 0.7


class TestDecisionMetrics:
    def test_action_distribution(self) -> None:
        decisions = [
            make_decision(decision_id="D1", action=DecisionAction.BUY),
            make_decision(decision_id="D2", action=DecisionAction.BUY),
            make_decision(decision_id="D3", action=DecisionAction.HOLD),
            make_decision(decision_id="D4", action=DecisionAction.NO_TRADE),
        ]
        m = compute_decision_metrics(decisions)
        assert m["count"] == 4.0
        assert m["buy_rate"] == 0.5
        assert m["hold_rate"] == 0.25
        assert m["no_trade_rate"] == 0.25
        assert m["sell_rate"] == 0.0


class TestSizingAndRiskMetrics:
    def test_sizing_status_distribution(self) -> None:
        results = [
            make_sizing_result(sizing_id="S1", status=RiskCheckStatus.PASS),
            make_sizing_result(sizing_id="S2", status=RiskCheckStatus.REJECT),
        ]
        m = compute_sizing_metrics(results)
        assert m["pass_rate"] == 0.5
        assert m["reject_rate"] == 0.5

    def test_risk_failure_rate_combines_reject_and_unknown(self) -> None:
        results = [
            make_risk_result(risk_id="R1", status=RiskCheckStatus.PASS),
            make_risk_result(risk_id="R2", status=RiskCheckStatus.REJECT),
            make_risk_result(risk_id="R3", status=RiskCheckStatus.UNKNOWN),
        ]
        m = compute_risk_metrics(results)
        assert abs(m["failure_rate"] - (2 / 3)) < 1e-9


class TestBrokerMetrics:
    def test_failure_and_timeout_and_auth_and_rate_limit_rates(self) -> None:
        responses = [
            make_broker_response(response_id="B1", status="PENDING"),
            make_broker_response(response_id="B2", status="ERROR", error_code="BrokerTimeoutError"),
            make_broker_response(response_id="B3", status="ERROR", error_code="expired-token"),
            make_broker_response(response_id="B4", status="ERROR", error_code="rate-limited"),
        ]
        m = compute_broker_metrics(responses)
        assert m["count"] == 4.0
        assert m["failure_rate"] == 0.75
        assert m["timeout_rate"] == 0.25
        assert m["auth_failure_rate"] == 0.25
        assert m["rate_limit_rate"] == 0.25

    def test_duplicate_client_order_id_count_only_from_requests(self) -> None:
        responses = [make_broker_response()]
        requests = [
            make_broker_request(request_id="REQ1", client_order_id="CID-A"),
            make_broker_request(request_id="REQ2", client_order_id="CID-A"),
            make_broker_request(request_id="REQ3", client_order_id="CID-B"),
        ]
        m = compute_broker_metrics(responses, requests)
        assert m["duplicate_client_order_id_count"] == 1.0

    def test_no_requests_leaves_duplicate_count_none(self) -> None:
        m = compute_broker_metrics([make_broker_response()])
        assert m["duplicate_client_order_id_count"] is None


class TestAIGatewayMetrics:
    def test_status_distribution(self) -> None:
        responses = [
            make_ai_response(response_id="A1", status=RequestStatus.SUCCESS),
            make_ai_response(response_id="A2", status=RequestStatus.TIMEOUT, attempt_count=0),
            make_ai_response(response_id="A3", status=RequestStatus.RATE_LIMITED, attempt_count=0),
        ]
        m = compute_ai_gateway_metrics(responses)
        assert abs(m["success_rate"] - (1 / 3)) < 1e-9
        assert abs(m["timeout_rate"] - (1 / 3)) < 1e-9
        assert abs(m["rate_limited_rate"] - (1 / 3)) < 1e-9


class TestLearningAndModelEvolutionMetrics:
    def test_learning_counts_and_mean_mae(self) -> None:
        datasets = [make_training_dataset(dataset_id="TDS-1", sample_count=100)]
        candidates = [make_candidate(candidate_id="C1")]
        evaluations = [make_evaluation(evaluation_id="E1", test_mae=0.05), make_evaluation(evaluation_id="E2", test_mae=0.15)]
        m = compute_learning_metrics(datasets, candidates, evaluations)
        assert m["dataset_count"] == 1.0
        assert m["mean_dataset_sample_count"] == 100.0
        assert m["mean_test_mae"] == 0.1

    def test_model_evolution_pass_rate_and_lineage_counts(self) -> None:
        from learning.enums import CandidateModelStatus

        transitions = [
            make_transition(transition_id="T1", to_status=CandidateModelStatus.BACKTESTED, passed=True),
            make_transition(transition_id="T2", to_status=CandidateModelStatus.VALIDATED, passed=False),
        ]
        lineages = [make_lineage(candidate_id="C1"), make_lineage(candidate_id="C2", parent_candidate_id="C1", generation=1)]
        m = compute_model_evolution_metrics(transitions, lineages)
        assert m["transition_count"] == 2.0
        assert m["pass_rate"] == 0.5
        assert m["backtested_count"] == 1.0
        assert m["validated_count"] == 0.0
        assert m["lineage_count"] == 2.0
        assert m["lineage_with_parent_count"] == 1.0
