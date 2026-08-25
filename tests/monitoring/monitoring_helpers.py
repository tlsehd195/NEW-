"""Shared test helpers for the Phase 14 Monitoring test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ai_gateway.enums import RequestStatus
from ai_gateway.models import AIResponse

from broker.models import BrokerRequestRecord, BrokerResponseRecord

from data_infra.models import PriceBar, Provenance

from decision.models import DecisionOutput

from evolution.models import ModelLineageRecord, ModelStatusTransition

from learning.enums import CandidateModelStatus
from learning.models import CandidateModelArtifact, EvaluationMetrics, EvaluationResult, TrainingDataset

from monitoring.config import MonitoringConfig

from predict.enums import PredictionMethodType
from predict.models import PredictionOutput

from risk.enums import RiskCheckStatus
from risk.models import PositionSizingResult, RiskCheckedPosition

from trade_journal.enums import DecisionAction, TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_config(**overrides) -> MonitoringConfig:
    return MonitoringConfig(**overrides)


def make_provenance(record_id: str, retrieved_at: datetime, source: str = "test_source") -> Provenance:
    return Provenance(
        source=source, source_dataset="test_dataset", source_record_id=record_id,
        retrieved_at=retrieved_at, data_version="dv-test-1",
    )


def make_bar(
    *, security_id: str = "AAA", timestamp: datetime = utc(2024, 1, 2), close: float = 100.0,
    volume: float = 200_000.0, available_time: Optional[datetime] = None,
) -> PriceBar:
    available_time = available_time if available_time is not None else timestamp
    return PriceBar(
        security_id=security_id, timestamp=timestamp, open=close, high=close * 1.005, low=close * 0.995,
        close=close, volume=volume, available_time=available_time, ingestion_time=available_time,
        provenance=make_provenance(f"{security_id}-{timestamp.isoformat()}", available_time),
    )


def make_prediction(
    *, prediction_id: str = "PRED-000001", security_id: str = "AAA", as_of_time: datetime = utc(2024, 1, 2),
    expected_return: Optional[float] = 0.01, probability: Optional[float] = 0.55,
    expected_volatility: Optional[float] = 0.2, uncertainty: Optional[float] = 0.05,
    confidence: Optional[float] = 0.8,
) -> PredictionOutput:
    return PredictionOutput(
        prediction_id=prediction_id, security_id=security_id, as_of_time=as_of_time, horizon_days=5,
        expected_return=expected_return, probability=probability, expected_volatility=expected_volatility,
        uncertainty=uncertainty, confidence=confidence, method="random_walk_v1",
        method_type=PredictionMethodType.DETERMINISTIC_BASELINE, feature_version="feat-v1", data_version=("dv-1",),
        method_version="method-v1", configuration_version="cfg-v1",
    )


def make_decision(
    *, decision_id: str = "DEC-OUT-000001", security_id: str = "AAA", as_of_time: datetime = utc(2024, 1, 2),
    action: DecisionAction = DecisionAction.BUY, decision_reason: str = "test_rule",
) -> DecisionOutput:
    return DecisionOutput(
        decision_id=decision_id, security_id=security_id, as_of_time=as_of_time, action=action,
        decision_reason=decision_reason, confidence=0.7, time_horizon_days=5, target_weight_hint=0.1,
        regime=None, prediction_id="PRED-000001", prediction_version="method-v1", regime_version=None,
        feature_version="feat-v1", data_version=("dv-1",), model_version=None, decision_version="agent-v1",
    )


def make_sizing_result(
    *, sizing_id: str = "SIZE-000001", security_id: str = "AAA", as_of_time: datetime = utc(2024, 1, 2),
    status: RiskCheckStatus = RiskCheckStatus.PASS, reason: str = "normal_sizing",
) -> PositionSizingResult:
    return PositionSizingResult(
        sizing_id=sizing_id, security_id=security_id, as_of_time=as_of_time, status=status, reason=reason,
        decision_id="DEC-OUT-000001", decision_action=DecisionAction.BUY, proposed_target_weight=0.1,
        proposed_target_quantity=50.0, current_weight=0.0, current_quantity=0.0,
        sizing_version="sizer-v1", feature_version="feat-v1",
    )


def make_risk_result(
    *, risk_id: str = "RISK-000001", security_id: str = "AAA", as_of_time: datetime = utc(2024, 1, 2),
    status: RiskCheckStatus = RiskCheckStatus.PASS, reason: str = "normal_sizing",
) -> RiskCheckedPosition:
    return RiskCheckedPosition(
        risk_id=risk_id, security_id=security_id, as_of_time=as_of_time, status=status, reason=reason,
        breached_limits=(), final_target_weight=0.1, final_target_quantity=50.0,
        sizing_id="SIZE-000001", decision_id="DEC-OUT-000001", prediction_id="PRED-000001", risk_state=None,
        risk_version="risk-engine-v1", feature_version="feat-v1", provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def make_broker_request(
    *, request_id: str = "BROKREQ-000001", client_order_id: Optional[str] = "CID-000001",
    requested_at: datetime = utc(2024, 1, 2),
) -> BrokerRequestRecord:
    return BrokerRequestRecord(
        request_id=request_id, broker_id="toss", operation="submit", execution_mode="PAPER",
        client_order_id=client_order_id, decision_id="DEC-OUT-000001", sizing_id="SIZE-000001",
        risk_assessment_id="RISK-000001", configuration_version="cfg-v1", requested_at=requested_at,
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def make_broker_response(
    *, response_id: str = "BROKRESLOG-000001", request_id: str = "BROKREQ-000001", status: str = "PENDING",
    error_code: Optional[str] = None, responded_at: datetime = utc(2024, 1, 2), attempt_count: int = 1,
) -> BrokerResponseRecord:
    return BrokerResponseRecord(
        response_id=response_id, request_id=request_id, broker_id="toss", operation="submit", status=status,
        broker_order_id=None, error_code=error_code, attempt_count=attempt_count, latency_ms=50.0,
        responded_at=responded_at, provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def make_ai_response(
    *, response_id: str = "AIRESP-000001", request_id: str = "AIREQ-000001",
    status: RequestStatus = RequestStatus.SUCCESS, responded_at: datetime = utc(2024, 1, 2),
    attempt_count: int = 1,
) -> AIResponse:
    return AIResponse(
        response_id=response_id, request_id=request_id, status=status, provider_id="test_provider",
        model="test-model", model_version="v1", prompt_template_version="tmpl-v1",
        configuration_version="cfg-v1", content="ok" if status == RequestStatus.SUCCESS else None,
        parsed=None, usage=None, latency_ms=100.0,
        error_reason=None if status == RequestStatus.SUCCESS else status.value,
        attempt_count=attempt_count, responded_at=responded_at, provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def make_training_dataset(
    *, dataset_id: str = "TDS-000001", created_at: datetime = utc(2024, 1, 2), sample_count: int = 100,
) -> TrainingDataset:
    return TrainingDataset(
        dataset_id=dataset_id, dataset_version="dsv-1", created_at=created_at, source_experience_ids=("EXP-1",),
        provenance=TradeProvenance.HISTORICAL_SIMULATION, feature_version="feat-v1", label_version="label-v1",
        data_version=("dv-1",), cleaning_config_version="clean-v1", label_config_version="labelcfg-v1",
        split_config_version="split-v1", sampling_config_version="sample-v1", configuration_version="cfg-v1",
        sample_count=sample_count, excluded_count=0, quality_status="OK",
    )


def make_candidate(
    *, candidate_id: str = "CAND-000001", dataset_id: str = "TDS-000001", trained_at: datetime = utc(2024, 1, 2),
) -> CandidateModelArtifact:
    return CandidateModelArtifact(
        candidate_id=candidate_id, status=CandidateModelStatus.CANDIDATE, trainer_version="trainer-v1",
        dataset_id=dataset_id, dataset_version="dsv-1", feature_version="feat-v1", label_version="label-v1",
        parameters={"predicted_value": 0.0}, seed=None, trained_at=trained_at,
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def make_evaluation(
    *, evaluation_id: str = "EVAL-000001", candidate_id: str = "CAND-000001", dataset_id: str = "TDS-000001",
    evaluated_at: datetime = utc(2024, 1, 2), test_mae: Optional[float] = 0.05,
) -> EvaluationResult:
    metrics = EvaluationMetrics(sample_count=20, mean_absolute_error=test_mae, mean_squared_error=0.01, mean_label=0.0)
    return EvaluationResult(
        evaluation_id=evaluation_id, candidate_id=candidate_id, dataset_id=dataset_id, dataset_version="dsv-1",
        train_metrics=metrics, validation_metrics=metrics, test_metrics=metrics, baseline_metrics=metrics,
        evaluator_version="evaluator-v1", evaluated_at=evaluated_at, provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


def make_transition(
    *, transition_id: str = "TRANS-000001", candidate_id: str = "CAND-000001",
    to_status: CandidateModelStatus = CandidateModelStatus.BACKTESTED, passed: bool = True,
    evaluated_at: datetime = utc(2024, 1, 2),
) -> ModelStatusTransition:
    return ModelStatusTransition(
        transition_id=transition_id, candidate_id=candidate_id, dataset_id="TDS-000001", dataset_version="dsv-1",
        evaluation_id="EVAL-000001", from_status=CandidateModelStatus.CANDIDATE, to_status=to_status,
        passed=passed, criteria_version="criteria-v1", criteria={"min_sample_count": True}, reason="all_criteria_met",
        provenance=TradeProvenance.HISTORICAL_SIMULATION, evaluated_at=evaluated_at,
    )


def make_lineage(
    *, candidate_id: str = "CAND-000001", parent_candidate_id: Optional[str] = None, generation: int = 0,
    recorded_at: Optional[datetime] = None,
) -> ModelLineageRecord:
    return ModelLineageRecord(
        candidate_id=candidate_id, parent_candidate_id=parent_candidate_id, generation=generation,
        lineage_basis="initial", dataset_id="TDS-000001", dataset_version="dsv-1",
        provenance=TradeProvenance.HISTORICAL_SIMULATION, recorded_at=recorded_at,
    )


__all__ = [
    "utc", "make_config", "make_provenance", "make_bar", "make_prediction", "make_decision",
    "make_sizing_result", "make_risk_result", "make_broker_request", "make_broker_response",
    "make_ai_response", "make_training_dataset", "make_candidate", "make_evaluation", "make_transition",
    "make_lineage",
]
