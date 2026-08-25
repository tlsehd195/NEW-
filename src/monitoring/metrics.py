"""Deterministic metric computation over already-materialized Phase
1-13 records. Every function here is a pure function of its input
sequence -- no data access, no randomness, no wall-clock call. A metric
that cannot be honestly computed (empty input, too few finite values)
is `None`, never a fabricated `0.0` (instruction section 12).

See docs/specifications/PHASE-14-monitoring.md section 5.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional, Sequence

from ai_gateway.enums import RequestStatus
from ai_gateway.models import AIResponse

from broker.models import BrokerCapabilities, BrokerRequestRecord, BrokerResponseRecord
from data_infra.models import PriceBar

from decision.models import DecisionOutput

from evolution.models import ModelLineageRecord, ModelStatusTransition

from learning.enums import CandidateModelStatus
from learning.models import CandidateModelArtifact, EvaluationResult, TrainingDataset

from predict.models import PredictionOutput

from risk.enums import RiskCheckStatus
from risk.models import PositionSizingResult, RiskCheckedPosition

from trade_journal.enums import DecisionAction


def _finite(value: Optional[float]) -> bool:
    if value is None:
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def _mean(values: Sequence[float]) -> Optional[float]:
    finite = [v for v in values if _finite(v)]
    if not finite:
        return None
    return sum(finite) / len(finite)


def _stdev(values: Sequence[float]) -> Optional[float]:
    finite = [v for v in values if _finite(v)]
    if len(finite) < 2:
        return None
    mean = sum(finite) / len(finite)
    variance = sum((v - mean) ** 2 for v in finite) / (len(finite) - 1)
    return variance**0.5


def compute_data_quality_metrics(bars: Sequence[PriceBar]) -> dict:
    n = len(bars)
    if n == 0:
        return {
            "observation_count": 0.0, "invalid_rate": None, "duplicate_rate": None,
            "timestamp_violation_rate": None, "latest_available_time": None,
        }

    invalid = sum(
        1 for b in bars
        if not all(_finite(v) for v in (b.open, b.high, b.low, b.close, b.volume))
    )
    keys = [(b.security_id, b.timestamp) for b in bars]
    duplicate_count = len(keys) - len(set(keys))

    violations = 0
    last_seen: dict[str, object] = {}
    for bar in bars:
        prior = last_seen.get(bar.security_id)
        if prior is not None and bar.timestamp < prior:
            violations += 1
        last_seen[bar.security_id] = bar.timestamp

    latest_available_time = max(b.available_time for b in bars)

    return {
        "observation_count": float(n),
        "invalid_rate": invalid / n,
        "duplicate_rate": duplicate_count / n,
        "timestamp_violation_rate": violations / n,
        "latest_available_time": latest_available_time,
    }


def compute_prediction_metrics(predictions: Sequence[PredictionOutput]) -> dict:
    n = len(predictions)
    if n == 0:
        return {
            "count": 0.0, "missing_rate": None, "confidence_mean": None, "confidence_stdev": None,
            "uncertainty_mean": None, "expected_volatility_mean": None,
        }
    missing = sum(1 for p in predictions if p.expected_return is None)
    confidences = [p.confidence for p in predictions if p.confidence is not None]
    uncertainties = [p.uncertainty for p in predictions if p.uncertainty is not None]
    vols = [p.expected_volatility for p in predictions if p.expected_volatility is not None]
    return {
        "count": float(n),
        "missing_rate": missing / n,
        "confidence_mean": _mean(confidences),
        "confidence_stdev": _stdev(confidences),
        "uncertainty_mean": _mean(uncertainties),
        "expected_volatility_mean": _mean(vols),
    }


def compute_decision_metrics(decisions: Sequence[DecisionOutput]) -> dict:
    n = len(decisions)
    if n == 0:
        return {
            "count": 0.0, "buy_rate": None, "sell_rate": None, "hold_rate": None,
            "exit_rate": None, "no_trade_rate": None,
        }
    counts = Counter(d.action for d in decisions)
    return {
        "count": float(n),
        "buy_rate": counts.get(DecisionAction.BUY, 0) / n,
        "sell_rate": counts.get(DecisionAction.SELL, 0) / n,
        "hold_rate": counts.get(DecisionAction.HOLD, 0) / n,
        "exit_rate": counts.get(DecisionAction.EXIT, 0) / n,
        "no_trade_rate": counts.get(DecisionAction.NO_TRADE, 0) / n,
    }


def compute_sizing_metrics(sizing_results: Sequence[PositionSizingResult]) -> dict:
    n = len(sizing_results)
    if n == 0:
        return {"count": 0.0, "pass_rate": None, "reduce_rate": None, "reject_rate": None, "unknown_rate": None}
    counts = Counter(r.status for r in sizing_results)
    return {
        "count": float(n),
        "pass_rate": counts.get(RiskCheckStatus.PASS, 0) / n,
        "reduce_rate": counts.get(RiskCheckStatus.REDUCE, 0) / n,
        "reject_rate": counts.get(RiskCheckStatus.REJECT, 0) / n,
        "unknown_rate": counts.get(RiskCheckStatus.UNKNOWN, 0) / n,
    }


def compute_risk_metrics(risk_results: Sequence[RiskCheckedPosition]) -> dict:
    n = len(risk_results)
    if n == 0:
        return {
            "count": 0.0, "pass_rate": None, "reduce_rate": None, "reject_rate": None,
            "unknown_rate": None, "failure_rate": None,
        }
    counts = Counter(r.status for r in risk_results)
    reject = counts.get(RiskCheckStatus.REJECT, 0)
    unknown = counts.get(RiskCheckStatus.UNKNOWN, 0)
    return {
        "count": float(n),
        "pass_rate": counts.get(RiskCheckStatus.PASS, 0) / n,
        "reduce_rate": counts.get(RiskCheckStatus.REDUCE, 0) / n,
        "reject_rate": reject / n,
        "unknown_rate": unknown / n,
        "failure_rate": (reject + unknown) / n,
    }


_BROKER_FAILURE_STATUSES = frozenset({"ERROR", "UNKNOWN", "REJECTED"})
_BROKER_TIMEOUT_CODES = frozenset({"BrokerTimeoutError"})
_BROKER_AUTH_CODES = frozenset({"BrokerAuthError", "expired-token"})
_BROKER_RATE_LIMIT_CODES = frozenset({"BrokerRateLimitError", "rate-limited"})


def compute_broker_metrics(
    responses: Sequence[BrokerResponseRecord], requests: Sequence[BrokerRequestRecord] = ()
) -> dict:
    n = len(responses)
    if n == 0:
        return {
            "count": 0.0, "success_rate": None, "failure_rate": None, "timeout_rate": None,
            "auth_failure_rate": None, "rate_limit_rate": None, "malformed_response_rate": None,
            "unknown_status_rate": None, "duplicate_client_order_id_count": None,
        }
    status_counts = Counter(r.status for r in responses)
    error_code_counts = Counter(r.error_code for r in responses if r.error_code)
    failures = sum(c for s, c in status_counts.items() if s in _BROKER_FAILURE_STATUSES)
    timeout = sum(error_code_counts.get(c, 0) for c in _BROKER_TIMEOUT_CODES)
    auth = sum(error_code_counts.get(c, 0) for c in _BROKER_AUTH_CODES)
    rate_limit = sum(error_code_counts.get(c, 0) for c in _BROKER_RATE_LIMIT_CODES)
    malformed = error_code_counts.get("malformed_response", 0)
    unknown_status = status_counts.get("UNKNOWN", 0)

    duplicate_count: Optional[float] = None
    if requests:
        client_order_id_counts = Counter(r.client_order_id for r in requests if r.client_order_id)
        duplicate_count = float(sum(c - 1 for c in client_order_id_counts.values() if c > 1))

    return {
        "count": float(n),
        "success_rate": (n - failures) / n,
        "failure_rate": failures / n,
        "timeout_rate": timeout / n,
        "auth_failure_rate": auth / n,
        "rate_limit_rate": rate_limit / n,
        "malformed_response_rate": malformed / n,
        "unknown_status_rate": unknown_status / n,
        "duplicate_client_order_id_count": duplicate_count,
    }


def compute_capability_unknown_count(capabilities: BrokerCapabilities) -> int:
    from broker.enums import CapabilityStatus

    return sum(1 for status in capabilities.capabilities.values() if status == CapabilityStatus.UNKNOWN)


def compute_ai_gateway_metrics(responses: Sequence[AIResponse]) -> dict:
    n = len(responses)
    if n == 0:
        return {
            "count": 0.0, "success_rate": None, "failure_rate": None, "timeout_rate": None,
            "auth_failure_rate": None, "rate_limited_rate": None, "invalid_response_rate": None,
            "provider_error_rate": None, "unavailable_rate": None, "missing_configuration_rate": None,
            "mean_attempt_count": None,
        }
    status_counts = Counter(r.status for r in responses)
    success = status_counts.get(RequestStatus.SUCCESS, 0)
    return {
        "count": float(n),
        "success_rate": success / n,
        "failure_rate": (n - success) / n,
        "timeout_rate": status_counts.get(RequestStatus.TIMEOUT, 0) / n,
        "auth_failure_rate": status_counts.get(RequestStatus.AUTH_FAILED, 0) / n,
        "rate_limited_rate": status_counts.get(RequestStatus.RATE_LIMITED, 0) / n,
        "invalid_response_rate": status_counts.get(RequestStatus.INVALID_RESPONSE, 0) / n,
        "provider_error_rate": status_counts.get(RequestStatus.PROVIDER_ERROR, 0) / n,
        "unavailable_rate": status_counts.get(RequestStatus.NO_PROVIDER_AVAILABLE, 0) / n,
        "missing_configuration_rate": status_counts.get(RequestStatus.MISSING_CONFIGURATION, 0) / n,
        "mean_attempt_count": _mean([r.attempt_count for r in responses]),
    }


def compute_learning_metrics(
    datasets: Sequence[TrainingDataset], candidates: Sequence[CandidateModelArtifact],
    evaluations: Sequence[EvaluationResult],
) -> dict:
    test_maes = [
        e.test_metrics.mean_absolute_error for e in evaluations if e.test_metrics.mean_absolute_error is not None
    ]
    return {
        "dataset_count": float(len(datasets)),
        "mean_dataset_sample_count": _mean([float(d.sample_count) for d in datasets]),
        "candidate_count": float(len(candidates)),
        "evaluation_count": float(len(evaluations)),
        "mean_test_mae": _mean(test_maes),
    }


def compute_model_evolution_metrics(
    transitions: Sequence[ModelStatusTransition], lineages: Sequence[ModelLineageRecord]
) -> dict:
    n = len(transitions)
    passed_to_status = Counter(t.to_status for t in transitions if t.passed)
    return {
        "transition_count": float(n),
        "pass_rate": (sum(1 for t in transitions if t.passed) / n) if n else None,
        "backtested_count": float(passed_to_status.get(CandidateModelStatus.BACKTESTED, 0)),
        "validated_count": float(passed_to_status.get(CandidateModelStatus.VALIDATED, 0)),
        "oos_tested_count": float(passed_to_status.get(CandidateModelStatus.OOS_TESTED, 0)),
        "lineage_count": float(len(lineages)),
        "lineage_with_parent_count": float(sum(1 for lin in lineages if lin.parent_candidate_id is not None)),
    }
