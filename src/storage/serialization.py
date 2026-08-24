"""Explicit (non-generic) serialize/deserialize helpers for domain objects
that need to cross the DuckDB/Parquet boundary.

Design note: a generic recursive dataclass<->dict mapper would be shorter,
but would silently produce wrong results for Enum members and datetimes
(round-tripping through JSON loses their type) unless it re-derives the
target type at read time anyway. Writing one explicit pair of functions
per type is more code but keeps every conversion auditable and keeps
failures loud (a missing field raises a KeyError immediately) rather than
silently defaulting — consistent with this project's fail-closed
philosophy (PROJECT_MASTER_PLAN.md section 1.4) applied to storage
round-tripping, not just trading state.

Every timestamp is normalized to UTC and stored as a naive
(tzinfo-stripped) value; every read path re-attaches ``timezone.utc``.
This sidesteps DuckDB/PyArrow/Parquet timezone-metadata round-trip
ambiguity entirely rather than depending on it being handled correctly by
the storage engine (this project treats "the library probably handles
it" as an unverified assumption, not a guarantee).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from data_infra.enums import (
    BenchmarkReturnType,
    CorporateActionType,
    InstrumentType,
    SecurityStatus,
)
from data_infra.models import (
    BenchmarkPoint,
    CorporateAction,
    PriceBar,
    Provenance,
    SecurityMaster,
    UniverseMembership,
)

from backtest.enums import ExperimentResult, OrderSide, OrderStatus, OrderType
from backtest.experiment import ExperimentRecord
from backtest.fills import Fill
from backtest.metrics import PerformanceReport
from backtest.orders import Order
from backtest.portfolio import PortfolioView, PositionView

from trade_journal.enums import CorrectionTargetType, DecisionAction, TradeProvenance
from trade_journal.models import (
    AlternativeOutcome,
    CorrectionRecord,
    CounterfactualRecord,
    DecisionSnapshot,
    ExperienceRecord,
    PostTradeAnalysis,
    TradeRecord,
)

from regime.enums import RegimeAxis, SubjectKind
from regime.models import CompositeRegimeObservation, RegimeObservation

from predict.enums import PredictionMethodType
from predict.models import PredictionOutput


def to_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(f"expected a timezone-aware datetime, got naive: {value!r}")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def from_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        # Already aware (e.g. a driver that preserves tz) -- normalize.
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def json_dumps(payload: Any) -> str:
    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return to_utc_naive(obj).isoformat() if obj.tzinfo else obj.isoformat()
        if isinstance(obj, timedelta):
            return obj.total_seconds()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(payload, default=_default, sort_keys=True)


def json_loads(raw: Optional[str]) -> Any:
    if raw is None:
        return None
    return json.loads(raw)


# --------------------------------------------------------------------
# data_infra.models
# --------------------------------------------------------------------


def provenance_to_row(p: Provenance) -> dict:
    return {
        "provenance_source": p.source,
        "provenance_source_dataset": p.source_dataset,
        "provenance_source_record_id": p.source_record_id,
        "provenance_retrieved_at": to_utc_naive(p.retrieved_at),
        "provenance_data_version": p.data_version,
        "provenance_schema_version": p.schema_version,
    }


def row_to_provenance(row: dict) -> Provenance:
    return Provenance(
        source=row["provenance_source"],
        source_dataset=row["provenance_source_dataset"],
        source_record_id=row["provenance_source_record_id"],
        retrieved_at=from_utc_naive(row["provenance_retrieved_at"]),
        data_version=row["provenance_data_version"],
        schema_version=int(row["provenance_schema_version"]),
    )


def price_bar_to_row(bar: PriceBar) -> dict:
    row = {
        "security_id": bar.security_id,
        "timestamp": to_utc_naive(bar.timestamp),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "available_time": to_utc_naive(bar.available_time),
        "ingestion_time": to_utc_naive(bar.ingestion_time),
        "adjusted_close": bar.adjusted_close,
        "vwap": bar.vwap,
        "trade_count": bar.trade_count,
        "currency": bar.currency,
        "exchange": bar.exchange,
        "event_time": to_utc_naive(bar.event_time),
        "publication_time": to_utc_naive(bar.publication_time),
    }
    row.update(provenance_to_row(bar.provenance))
    return row


def row_to_price_bar(row: dict) -> PriceBar:
    return PriceBar(
        security_id=row["security_id"],
        timestamp=from_utc_naive(row["timestamp"]),
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        available_time=from_utc_naive(row["available_time"]),
        ingestion_time=from_utc_naive(row["ingestion_time"]),
        provenance=row_to_provenance(row),
        adjusted_close=row.get("adjusted_close"),
        vwap=row.get("vwap"),
        trade_count=(int(row["trade_count"]) if row.get("trade_count") is not None else None),
        currency=row.get("currency"),
        exchange=row.get("exchange"),
        event_time=from_utc_naive(row.get("event_time")),
        publication_time=from_utc_naive(row.get("publication_time")),
    )


PRICE_BAR_COLUMNS = (
    "security_id", "timestamp", "open", "high", "low", "close", "volume",
    "available_time", "ingestion_time", "adjusted_close", "vwap", "trade_count",
    "currency", "exchange", "event_time", "publication_time",
    "provenance_source", "provenance_source_dataset", "provenance_source_record_id",
    "provenance_retrieved_at", "provenance_data_version", "provenance_schema_version",
)


def security_master_to_row(sec: SecurityMaster) -> dict:
    return {
        "security_id": sec.security_id,
        "ticker": sec.ticker,
        "exchange": sec.exchange,
        "currency": sec.currency,
        "company_id": sec.company_id,
        "instrument_type": sec.instrument_type.value,
        "valid_from": to_utc_naive(sec.valid_from),
        "valid_to": to_utc_naive(sec.valid_to),
        "status": sec.status.value,
    }


def row_to_security_master(row: dict) -> SecurityMaster:
    return SecurityMaster(
        security_id=row["security_id"],
        ticker=row["ticker"],
        exchange=row["exchange"],
        currency=row["currency"],
        company_id=row["company_id"],
        instrument_type=InstrumentType(row["instrument_type"]),
        valid_from=from_utc_naive(row["valid_from"]),
        valid_to=from_utc_naive(row.get("valid_to")),
        status=SecurityStatus(row["status"]),
    )


def corporate_action_to_row(action: CorporateAction) -> dict:
    row = {
        "security_id": action.security_id,
        "action_type": action.action_type.value,
        "event_time": to_utc_naive(action.event_time),
        "announcement_time": to_utc_naive(action.announcement_time),
        "effective_time": to_utc_naive(action.effective_time),
        "available_time": to_utc_naive(action.available_time),
        "ingestion_time": to_utc_naive(action.ingestion_time),
        "details_json": json_dumps(action.details),
    }
    row.update(provenance_to_row(action.provenance))
    return row


def row_to_corporate_action(row: dict) -> CorporateAction:
    return CorporateAction(
        security_id=row["security_id"],
        action_type=CorporateActionType(row["action_type"]),
        available_time=from_utc_naive(row["available_time"]),
        ingestion_time=from_utc_naive(row["ingestion_time"]),
        provenance=row_to_provenance(row),
        event_time=from_utc_naive(row.get("event_time")),
        announcement_time=from_utc_naive(row.get("announcement_time")),
        effective_time=from_utc_naive(row.get("effective_time")),
        details=json_loads(row.get("details_json")) or {},
    )


def benchmark_point_to_row(point: BenchmarkPoint) -> dict:
    row = {
        "benchmark_id": point.benchmark_id,
        "timestamp": to_utc_naive(point.timestamp),
        "level": point.level,
        "return_type": point.return_type.value,
        "currency": point.currency,
        "available_time": to_utc_naive(point.available_time),
        "ingestion_time": to_utc_naive(point.ingestion_time),
    }
    row.update(provenance_to_row(point.provenance))
    return row


def row_to_benchmark_point(row: dict) -> BenchmarkPoint:
    return BenchmarkPoint(
        benchmark_id=row["benchmark_id"],
        timestamp=from_utc_naive(row["timestamp"]),
        level=row["level"],
        return_type=BenchmarkReturnType(row["return_type"]),
        currency=row["currency"],
        available_time=from_utc_naive(row["available_time"]),
        ingestion_time=from_utc_naive(row["ingestion_time"]),
        provenance=row_to_provenance(row),
    )


def universe_membership_to_row(m: UniverseMembership) -> dict:
    return {
        "security_id": m.security_id,
        "universe": m.universe,
        "valid_from": to_utc_naive(m.valid_from),
        "valid_to": to_utc_naive(m.valid_to),
    }


def row_to_universe_membership(row: dict) -> UniverseMembership:
    return UniverseMembership(
        security_id=row["security_id"],
        universe=row["universe"],
        valid_from=from_utc_naive(row["valid_from"]),
        valid_to=from_utc_naive(row.get("valid_to")),
    )


# --------------------------------------------------------------------
# backtest.{orders,fills,portfolio,experiment,metrics}
# --------------------------------------------------------------------


def order_to_dict(order: Optional[Order]) -> Optional[dict]:
    if order is None:
        return None
    return {
        "order_id": order.order_id,
        "security_id": order.security_id,
        "side": order.side.value,
        "quantity": order.quantity,
        "order_type": order.order_type.value,
        "decision_time": order.decision_time.isoformat(),
        "status": order.status.value,
        "rejection_reason": order.rejection_reason,
    }


def dict_to_order(data: Optional[dict]) -> Optional[Order]:
    if data is None:
        return None
    return Order(
        order_id=data["order_id"],
        security_id=data["security_id"],
        side=OrderSide(data["side"]),
        quantity=data["quantity"],
        order_type=OrderType(data["order_type"]),
        decision_time=datetime.fromisoformat(data["decision_time"]),
        status=OrderStatus(data["status"]),
        rejection_reason=data.get("rejection_reason"),
    )


def fill_to_dict(fill: Fill) -> dict:
    return {
        "order_id": fill.order_id,
        "security_id": fill.security_id,
        "side": fill.side.value,
        "quantity": fill.quantity,
        "reference_price": fill.reference_price,
        "price": fill.price,
        "commission": fill.commission,
        "spread_cost": fill.spread_cost,
        "slippage_cost": fill.slippage_cost,
        "decision_time": fill.decision_time.isoformat(),
        "execution_time": fill.execution_time.isoformat(),
        "data_version": fill.data_version,
    }


def dict_to_fill(data: dict) -> Fill:
    return Fill(
        order_id=data["order_id"],
        security_id=data["security_id"],
        side=OrderSide(data["side"]),
        quantity=data["quantity"],
        reference_price=data["reference_price"],
        price=data["price"],
        commission=data["commission"],
        spread_cost=data["spread_cost"],
        slippage_cost=data["slippage_cost"],
        decision_time=datetime.fromisoformat(data["decision_time"]),
        execution_time=datetime.fromisoformat(data["execution_time"]),
        data_version=data["data_version"],
    )


def portfolio_view_to_dict(view: Optional[PortfolioView]) -> Optional[dict]:
    if view is None:
        return None
    return {
        "as_of_time": view.as_of_time.isoformat(),
        "cash": view.cash,
        "positions": {
            sid: {"security_id": p.security_id, "quantity": p.quantity, "average_cost": p.average_cost}
            for sid, p in view.positions.items()
        },
        "portfolio_value": view.portfolio_value,
    }


def dict_to_portfolio_view(data: Optional[dict]) -> Optional[PortfolioView]:
    if data is None:
        return None
    return PortfolioView(
        as_of_time=datetime.fromisoformat(data["as_of_time"]),
        cash=data["cash"],
        positions={
            sid: PositionView(security_id=p["security_id"], quantity=p["quantity"], average_cost=p["average_cost"])
            for sid, p in data["positions"].items()
        },
        portfolio_value=data["portfolio_value"],
    )


def performance_report_to_dict(report: PerformanceReport) -> dict:
    return {
        "cumulative_return": report.cumulative_return,
        "cagr": report.cagr,
        "annualized_volatility": report.annualized_volatility,
        "sharpe_ratio": report.sharpe_ratio,
        "sortino_ratio": report.sortino_ratio,
        "max_drawdown": report.max_drawdown,
        "calmar_ratio": report.calmar_ratio,
        "turnover": report.turnover,
        "total_transaction_cost": report.total_transaction_cost,
        "win_rate": report.win_rate,
        "avg_trade_return": report.avg_trade_return,
        "benchmark_cumulative_return": report.benchmark_cumulative_return,
        "benchmark_cagr": report.benchmark_cagr,
        "benchmark_max_drawdown": report.benchmark_max_drawdown,
        "excess_return": report.excess_return,
        "annualized_excess_return": report.annualized_excess_return,
    }


def dict_to_performance_report(data: dict) -> PerformanceReport:
    return PerformanceReport(**data)


def experiment_record_to_dict(record: ExperimentRecord) -> dict:
    return {
        "experiment_id": record.experiment_id,
        "strategy_version": record.strategy_version,
        "data_version": list(record.data_version),
        "feature_version": record.feature_version,
        "configuration_version": record.configuration_version,
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat(),
        "initial_capital": record.initial_capital,
        "transaction_cost_config": record.transaction_cost_config,
        "slippage_config": record.slippage_config,
        "benchmark": record.benchmark,
        "metrics": performance_report_to_dict(record.metrics),
        "code_version": record.code_version,
        "seed": record.seed,
        "result": record.result.value,
        "timestamp": record.timestamp.isoformat(),
    }


def dict_to_experiment_record(data: dict) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=data["experiment_id"],
        strategy_version=data["strategy_version"],
        data_version=tuple(data["data_version"]),
        feature_version=data.get("feature_version"),
        configuration_version=data["configuration_version"],
        start_date=datetime.fromisoformat(data["start_date"]),
        end_date=datetime.fromisoformat(data["end_date"]),
        initial_capital=data["initial_capital"],
        transaction_cost_config=data["transaction_cost_config"],
        slippage_config=data["slippage_config"],
        benchmark=data["benchmark"],
        metrics=dict_to_performance_report(data["metrics"]),
        code_version=data["code_version"],
        seed=data.get("seed"),
        result=ExperimentResult(data["result"]),
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )


# --------------------------------------------------------------------
# trade_journal.models
# --------------------------------------------------------------------


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _dt_from_iso(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value is not None else None


def _timedelta_seconds(value: Optional[timedelta]) -> Optional[float]:
    return value.total_seconds() if value is not None else None


def _timedelta_from_seconds(value: Optional[float]) -> Optional[timedelta]:
    return timedelta(seconds=value) if value is not None else None


def decision_snapshot_to_payload(snapshot: DecisionSnapshot) -> dict:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "decision_time": _dt_iso(snapshot.decision_time),
        "security_id": snapshot.security_id,
        "decision": snapshot.decision.value,
        "order": order_to_dict(snapshot.order),
        "portfolio_state": portfolio_view_to_dict(snapshot.portfolio_state),
        "market_state": snapshot.market_state,
        "features": snapshot.features,
        "prediction": snapshot.prediction,
        "confidence": snapshot.confidence,
        "decision_reason": snapshot.decision_reason,
        "expected_return": snapshot.expected_return,
        "expected_risk": snapshot.expected_risk,
        "risk_state": snapshot.risk_state,
        "target_weight": snapshot.target_weight,
        "model_version": snapshot.model_version,
        "strategy_version": snapshot.strategy_version,
        "feature_version": snapshot.feature_version,
        "data_version": list(snapshot.data_version) if snapshot.data_version is not None else None,
        "risk_version": snapshot.risk_version,
        "execution_version": snapshot.execution_version,
        "provenance": snapshot.provenance.value,
        "experiment_id": snapshot.experiment_id,
        "recorded_at": _dt_iso(snapshot.recorded_at),
    }


def payload_to_decision_snapshot(data: dict) -> DecisionSnapshot:
    return DecisionSnapshot(
        snapshot_id=data["snapshot_id"],
        decision_time=_dt_from_iso(data["decision_time"]),
        security_id=data["security_id"],
        decision=DecisionAction(data["decision"]),
        order=dict_to_order(data.get("order")),
        portfolio_state=dict_to_portfolio_view(data.get("portfolio_state")),
        market_state=data.get("market_state") or {},
        features=data.get("features"),
        prediction=data.get("prediction"),
        confidence=data.get("confidence"),
        decision_reason=data.get("decision_reason"),
        expected_return=data.get("expected_return"),
        expected_risk=data.get("expected_risk"),
        risk_state=data.get("risk_state"),
        target_weight=data.get("target_weight"),
        model_version=data.get("model_version"),
        strategy_version=data.get("strategy_version", "unknown"),
        feature_version=data.get("feature_version"),
        data_version=(tuple(data["data_version"]) if data.get("data_version") is not None else None),
        risk_version=data.get("risk_version"),
        execution_version=data.get("execution_version", "unknown"),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def trade_record_to_payload(trade: TradeRecord) -> dict:
    return {
        "trade_id": trade.trade_id,
        "decision_id": trade.decision_id,
        "order_id": trade.order_id,
        "security_id": trade.security_id,
        "timestamp": _dt_iso(trade.timestamp),
        "side": trade.side.value,
        "quantity": trade.quantity,
        "execution_price": trade.execution_price,
        "reference_price": trade.reference_price,
        "slippage": trade.slippage,
        "transaction_cost": trade.transaction_cost,
        "position_after": trade.position_after,
        "fill": fill_to_dict(trade.fill),
        "realized_pnl": trade.realized_pnl,
        "realized_return": trade.realized_return,
        "holding_period_seconds": _timedelta_seconds(trade.holding_period),
        "provenance": trade.provenance.value,
        "experiment_id": trade.experiment_id,
        "recorded_at": _dt_iso(trade.recorded_at),
    }


def payload_to_trade_record(data: dict) -> TradeRecord:
    return TradeRecord(
        trade_id=data["trade_id"],
        decision_id=data["decision_id"],
        order_id=data["order_id"],
        security_id=data["security_id"],
        timestamp=_dt_from_iso(data["timestamp"]),
        side=OrderSide(data["side"]),
        quantity=data["quantity"],
        execution_price=data["execution_price"],
        reference_price=data["reference_price"],
        slippage=data["slippage"],
        transaction_cost=data["transaction_cost"],
        position_after=data["position_after"],
        fill=dict_to_fill(data["fill"]),
        realized_pnl=data.get("realized_pnl"),
        realized_return=data.get("realized_return"),
        holding_period=_timedelta_from_seconds(data.get("holding_period_seconds")),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def post_trade_analysis_to_payload(analysis: PostTradeAnalysis) -> dict:
    return {
        "trade_id": analysis.trade_id,
        "prediction_error": analysis.prediction_error,
        "timing_error": analysis.timing_error,
        "risk_estimation_error": analysis.risk_estimation_error,
        "execution_error": analysis.execution_error,
        "regime_error": analysis.regime_error,
        "signal_error": analysis.signal_error,
        "notes": analysis.notes,
        "computed_at": _dt_iso(analysis.computed_at),
    }


def payload_to_post_trade_analysis(data: dict) -> PostTradeAnalysis:
    return PostTradeAnalysis(
        trade_id=data["trade_id"],
        prediction_error=data.get("prediction_error"),
        timing_error=data.get("timing_error"),
        risk_estimation_error=data.get("risk_estimation_error"),
        execution_error=data.get("execution_error"),
        regime_error=data.get("regime_error"),
        signal_error=data.get("signal_error"),
        notes=data.get("notes"),
        computed_at=_dt_from_iso(data.get("computed_at")),
    )


def alternative_outcome_to_dict(outcome: AlternativeOutcome) -> dict:
    return {
        "action": outcome.action,
        "hypothetical_return": outcome.hypothetical_return,
        "basis": outcome.basis,
        "horizon_seconds": _timedelta_seconds(outcome.horizon),
    }


def dict_to_alternative_outcome(data: dict) -> AlternativeOutcome:
    return AlternativeOutcome(
        action=data["action"],
        hypothetical_return=data.get("hypothetical_return"),
        basis=data.get("basis"),
        horizon=_timedelta_from_seconds(data.get("horizon_seconds")),
    )


def counterfactual_to_payload(record: CounterfactualRecord) -> dict:
    return {
        "trade_id": record.trade_id,
        "selected_action": record.selected_action.value,
        "alternatives": [alternative_outcome_to_dict(a) for a in record.alternatives],
        "computed_at": _dt_iso(record.computed_at),
    }


def payload_to_counterfactual(data: dict) -> CounterfactualRecord:
    return CounterfactualRecord(
        trade_id=data["trade_id"],
        selected_action=DecisionAction(data["selected_action"]),
        alternatives=tuple(dict_to_alternative_outcome(a) for a in data.get("alternatives", [])),
        computed_at=_dt_from_iso(data.get("computed_at")),
    )


def correction_to_row(correction: CorrectionRecord) -> dict:
    return {
        "correction_id": correction.correction_id,
        "target_type": correction.target_type.value,
        "target_id": correction.target_id,
        "reason": correction.reason,
        "corrected_fields_json": json_dumps(correction.corrected_fields),
        "created_at": to_utc_naive(correction.created_at),
        "created_by": correction.created_by,
    }


def row_to_correction(row: dict) -> CorrectionRecord:
    return CorrectionRecord(
        correction_id=row["correction_id"],
        target_type=CorrectionTargetType(row["target_type"]),
        target_id=row["target_id"],
        reason=row["reason"],
        corrected_fields=json_loads(row["corrected_fields_json"]) or {},
        created_at=from_utc_naive(row["created_at"]),
        created_by=row["created_by"],
    )


def _state_to_json(state: dict) -> dict:
    """ExperienceRecord.state carries a raw (non-frozen-dataclass-free)
    ``portfolio_state`` value under trade_journal.experience's convention
    (see build_experience_records) -- convert it explicitly rather than
    assuming every value in the dict is already JSON-serializable."""
    converted = dict(state)
    if "portfolio_state" in converted:
        converted["portfolio_state"] = portfolio_view_to_dict(converted["portfolio_state"])
    return converted


def _state_from_json(data: dict) -> dict:
    converted = dict(data)
    if "portfolio_state" in converted:
        converted["portfolio_state"] = dict_to_portfolio_view(converted["portfolio_state"])
    return converted


def experience_record_to_payload(record: ExperienceRecord) -> dict:
    return {
        "experience_id": record.experience_id,
        "trade_id": record.trade_id,
        "decision_id": record.decision_id,
        "state": _state_to_json(record.state),
        "action": record.action.value,
        "actual_outcome": record.actual_outcome,
        "expected_outcome": record.expected_outcome,
        "reward": record.reward,
        "market_regime": record.market_regime,
        "risk_state": record.risk_state,
        "prediction_error": record.prediction_error,
        "counterfactual_results": (
            [alternative_outcome_to_dict(a) for a in record.counterfactual_results]
            if record.counterfactual_results is not None
            else None
        ),
        "provenance": record.provenance.value,
        "data_version": list(record.data_version) if record.data_version is not None else None,
        "strategy_version": record.strategy_version,
        "model_version": record.model_version,
        "created_at": _dt_iso(record.created_at),
    }


def _actual_outcome_from_json(data: dict) -> dict:
    """Mirrors trade_journal.backtest_adapter's actual_outcome shape
    (realized_pnl, realized_return, holding_period) -- holding_period was
    written as seconds by json_dumps's timedelta handling, so it is
    converted back to a timedelta here rather than left as a bare float."""
    converted = dict(data)
    if "holding_period" in converted and converted["holding_period"] is not None:
        converted["holding_period"] = _timedelta_from_seconds(converted["holding_period"])
    return converted


def payload_to_experience_record(data: dict) -> ExperienceRecord:
    counterfactual_results = data.get("counterfactual_results")
    return ExperienceRecord(
        experience_id=data["experience_id"],
        trade_id=data["trade_id"],
        decision_id=data["decision_id"],
        state=_state_from_json(data.get("state") or {}),
        action=DecisionAction(data["action"]),
        actual_outcome=_actual_outcome_from_json(data.get("actual_outcome") or {}),
        expected_outcome=data.get("expected_outcome"),
        reward=data.get("reward"),
        market_regime=data.get("market_regime"),
        risk_state=data.get("risk_state"),
        prediction_error=data.get("prediction_error"),
        counterfactual_results=(
            tuple(dict_to_alternative_outcome(a) for a in counterfactual_results)
            if counterfactual_results is not None
            else None
        ),
        provenance=TradeProvenance(data["provenance"]),
        data_version=(tuple(data["data_version"]) if data.get("data_version") is not None else None),
        strategy_version=data.get("strategy_version", "unknown"),
        model_version=data.get("model_version"),
        created_at=_dt_from_iso(data.get("created_at")),
    )


# --------------------------------------------------------------------
# regime.models
# --------------------------------------------------------------------


def regime_observation_to_payload(observation: RegimeObservation) -> dict:
    return {
        "regime_id": observation.regime_id,
        "axis": observation.axis.value,
        "subject_id": observation.subject_id,
        "subject_kind": observation.subject_kind.value,
        "timestamp": _dt_iso(observation.timestamp),
        "as_of_time": _dt_iso(observation.as_of_time),
        "state": observation.state,
        "value": observation.value,
        "definition": observation.definition,
        "reliability": observation.reliability,
        "lookback_days": observation.lookback_days,
        "feature_version": observation.feature_version,
        "data_version": list(observation.data_version),
        "method_version": observation.method_version,
        "configuration_version": observation.configuration_version,
        "provenance": observation.provenance.value,
        "experiment_id": observation.experiment_id,
        "recorded_at": _dt_iso(observation.recorded_at),
    }


def payload_to_regime_observation(data: dict) -> RegimeObservation:
    return RegimeObservation(
        regime_id=data["regime_id"],
        axis=RegimeAxis(data["axis"]),
        subject_id=data["subject_id"],
        subject_kind=SubjectKind(data["subject_kind"]),
        timestamp=_dt_from_iso(data["timestamp"]),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        state=data["state"],
        value=data.get("value"),
        definition=data["definition"],
        reliability=data["reliability"],
        lookback_days=data["lookback_days"],
        feature_version=data["feature_version"],
        data_version=tuple(data.get("data_version") or ()),
        method_version=data["method_version"],
        configuration_version=data["configuration_version"],
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def composite_regime_to_payload(composite: CompositeRegimeObservation) -> dict:
    return {
        "composite_id": composite.composite_id,
        "subject_id": composite.subject_id,
        "subject_kind": composite.subject_kind.value,
        "as_of_time": _dt_iso(composite.as_of_time),
        "axes": {axis.value: regime_observation_to_payload(obs) for axis, obs in composite.axes.items()},
        "composite_label": composite.composite_label,
        "provenance": composite.provenance.value,
        "experiment_id": composite.experiment_id,
        "recorded_at": _dt_iso(composite.recorded_at),
    }


def payload_to_composite_regime(data: dict) -> CompositeRegimeObservation:
    axes = {
        RegimeAxis(axis_value): payload_to_regime_observation(obs_data)
        for axis_value, obs_data in (data.get("axes") or {}).items()
    }
    return CompositeRegimeObservation(
        composite_id=data["composite_id"],
        subject_id=data["subject_id"],
        subject_kind=SubjectKind(data["subject_kind"]),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        axes=axes,
        composite_label=data.get("composite_label"),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


# --------------------------------------------------------------------
# predict.models
# --------------------------------------------------------------------


def prediction_output_to_payload(prediction: PredictionOutput) -> dict:
    return {
        "prediction_id": prediction.prediction_id,
        "security_id": prediction.security_id,
        "as_of_time": _dt_iso(prediction.as_of_time),
        "horizon_days": prediction.horizon_days,
        "expected_return": prediction.expected_return,
        "probability": prediction.probability,
        "expected_volatility": prediction.expected_volatility,
        "uncertainty": prediction.uncertainty,
        "confidence": prediction.confidence,
        "method": prediction.method,
        "method_type": prediction.method_type.value,
        "feature_version": prediction.feature_version,
        "data_version": list(prediction.data_version),
        "method_version": prediction.method_version,
        "configuration_version": prediction.configuration_version,
        "model_version": prediction.model_version,
        "regime_context": prediction.regime_context,
        "provenance": prediction.provenance.value,
        "experiment_id": prediction.experiment_id,
        "recorded_at": _dt_iso(prediction.recorded_at),
    }


def payload_to_prediction_output(data: dict) -> PredictionOutput:
    return PredictionOutput(
        prediction_id=data["prediction_id"],
        security_id=data["security_id"],
        as_of_time=_dt_from_iso(data["as_of_time"]),
        horizon_days=data["horizon_days"],
        expected_return=data.get("expected_return"),
        probability=data.get("probability"),
        expected_volatility=data.get("expected_volatility"),
        uncertainty=data.get("uncertainty"),
        confidence=data.get("confidence"),
        method=data["method"],
        method_type=PredictionMethodType(data["method_type"]),
        feature_version=data["feature_version"],
        data_version=tuple(data.get("data_version") or ()),
        method_version=data["method_version"],
        configuration_version=data["configuration_version"],
        model_version=data.get("model_version"),
        regime_context=data.get("regime_context"),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )
