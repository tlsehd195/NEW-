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
from data_infra.fundamentals_models import FundamentalRecord
from data_infra.insider_models import InsiderTransaction
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
    AttributionResult,
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

from decision.models import DecisionOutput

from risk.enums import RiskCheckStatus
from risk.models import PortfolioRiskState, PositionSizingResult, RiskCheckedPosition

from learning.enums import CandidateModelStatus, SplitName
from learning.models import CandidateModelArtifact, EvaluationMetrics, EvaluationResult, LearningExperimentRecord, TrainingDataset

from evolution.models import ModelLineageRecord, ModelStatusTransition

from ai_gateway.enums import BillingStatus, ProviderHealthStatus, RequestStatus, TaskTier
from ai_gateway.models import AIRequest, AIResponse, ProviderQuotaState, UsageInfo

from broker.enums import BrokerOrderStatus
from broker.models import BrokerRequestRecord, BrokerResponseRecord, OrderStatusObservation

from monitoring.enums import AlertSeverity, ComponentHealthStatus, DriftStatus, MonitoringComponent
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent

from broker.models import ValidatedOrder
from broker.paper.models import PaperFillRecord, PaperOrderRecord

from broker.live.enums import ReconciliationStatus
from broker.live.kill_switch import KillSwitchEvent
from broker.live.reconciliation import ReconciliationResult
from broker.paper.performance import BenchmarkComparison, PaperPerformanceReport


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


def fundamental_record_to_row(record: FundamentalRecord) -> dict:
    row = {
        "security_id": record.security_id,
        "concept": record.concept,
        "period_start": to_utc_naive(record.period_start),
        "period_end": to_utc_naive(record.period_end),
        "fiscal_year": record.fiscal_year,
        "fiscal_period": record.fiscal_period,
        "form_type": record.form_type,
        "value": record.value,
        "unit": record.unit,
        "available_time": to_utc_naive(record.available_time),
        "ingestion_time": to_utc_naive(record.ingestion_time),
    }
    row.update(provenance_to_row(record.provenance))
    return row


def row_to_fundamental_record(row: dict) -> FundamentalRecord:
    return FundamentalRecord(
        security_id=row["security_id"],
        concept=row["concept"],
        period_start=from_utc_naive(row.get("period_start")),
        period_end=from_utc_naive(row["period_end"]),
        fiscal_year=int(row["fiscal_year"]),
        fiscal_period=row["fiscal_period"],
        form_type=row["form_type"],
        value=row["value"],
        unit=row["unit"],
        available_time=from_utc_naive(row["available_time"]),
        ingestion_time=from_utc_naive(row["ingestion_time"]),
        provenance=row_to_provenance(row),
    )


def insider_transaction_to_row(record: InsiderTransaction) -> dict:
    row = {
        "security_id": record.security_id,
        "reporting_owner_cik": record.reporting_owner_cik,
        "reporting_owner_name": record.reporting_owner_name,
        "is_officer": record.is_officer,
        "is_director": record.is_director,
        "is_ten_percent_owner": record.is_ten_percent_owner,
        "officer_title": record.officer_title,
        "transaction_date": to_utc_naive(record.transaction_date),
        "transaction_code": record.transaction_code,
        "acquired_disposed_code": record.acquired_disposed_code,
        "shares": record.shares,
        "price_per_share": record.price_per_share,
        "is_10b5_1_plan": record.is_10b5_1_plan,
        "accession_number": record.accession_number,
        "available_time": to_utc_naive(record.available_time),
        "ingestion_time": to_utc_naive(record.ingestion_time),
    }
    row.update(provenance_to_row(record.provenance))
    return row


def row_to_insider_transaction(row: dict) -> InsiderTransaction:
    return InsiderTransaction(
        security_id=row["security_id"],
        reporting_owner_cik=row["reporting_owner_cik"],
        reporting_owner_name=row["reporting_owner_name"],
        is_officer=bool(row["is_officer"]),
        is_director=bool(row["is_director"]),
        is_ten_percent_owner=bool(row["is_ten_percent_owner"]),
        officer_title=row.get("officer_title"),
        transaction_date=from_utc_naive(row["transaction_date"]),
        transaction_code=row["transaction_code"],
        acquired_disposed_code=row["acquired_disposed_code"],
        shares=row["shares"],
        price_per_share=row.get("price_per_share"),
        is_10b5_1_plan=bool(row["is_10b5_1_plan"]),
        accession_number=row["accession_number"],
        available_time=from_utc_naive(row["available_time"]),
        ingestion_time=from_utc_naive(row["ingestion_time"]),
        provenance=row_to_provenance(row),
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
        "features": order.features,
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
        features=data.get("features"),
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
        "max_drawdown_duration_days": report.max_drawdown_duration_days,
        "max_drawdown_recovery_days": report.max_drawdown_recovery_days,
        "max_drawdown_still_underwater": report.max_drawdown_still_underwater,
        "ulcer_index": report.ulcer_index,
        "value_at_risk_95": report.value_at_risk_95,
        "conditional_value_at_risk_95": report.conditional_value_at_risk_95,
        "max_consecutive_wins": report.max_consecutive_wins,
        "max_consecutive_losses": report.max_consecutive_losses,
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
        "exit_reason": trade.exit_reason,
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
        exit_reason=data.get("exit_reason"),
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


# --------------------------------------------------------------------
# decision.models
# --------------------------------------------------------------------


def decision_output_to_payload(decision: DecisionOutput) -> dict:
    return {
        "decision_id": decision.decision_id,
        "security_id": decision.security_id,
        "as_of_time": _dt_iso(decision.as_of_time),
        "action": decision.action.value,
        "decision_reason": decision.decision_reason,
        "confidence": decision.confidence,
        "time_horizon_days": decision.time_horizon_days,
        "target_weight_hint": decision.target_weight_hint,
        "regime": decision.regime,
        "prediction_id": decision.prediction_id,
        "prediction_version": decision.prediction_version,
        "regime_version": decision.regime_version,
        "feature_version": decision.feature_version,
        "data_version": list(decision.data_version),
        "model_version": decision.model_version,
        "decision_version": decision.decision_version,
        "strategy_version": decision.strategy_version,
        "risk_version": decision.risk_version,
        "provenance": decision.provenance.value,
        "experiment_id": decision.experiment_id,
        "recorded_at": _dt_iso(decision.recorded_at),
    }


def payload_to_decision_output(data: dict) -> DecisionOutput:
    return DecisionOutput(
        decision_id=data["decision_id"],
        security_id=data["security_id"],
        as_of_time=_dt_from_iso(data["as_of_time"]),
        action=DecisionAction(data["action"]),
        decision_reason=data["decision_reason"],
        confidence=data.get("confidence"),
        time_horizon_days=data.get("time_horizon_days"),
        target_weight_hint=data.get("target_weight_hint"),
        regime=data.get("regime"),
        prediction_id=data.get("prediction_id"),
        prediction_version=data.get("prediction_version"),
        regime_version=data.get("regime_version"),
        feature_version=data.get("feature_version"),
        data_version=tuple(data.get("data_version") or ()),
        model_version=data.get("model_version"),
        decision_version=data["decision_version"],
        strategy_version=data.get("strategy_version"),
        risk_version=data.get("risk_version"),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


# --------------------------------------------------------------------
# risk.models
# --------------------------------------------------------------------


def _risk_state_to_dict(state: Optional[PortfolioRiskState]) -> Optional[dict]:
    if state is None:
        return None
    return {
        "as_of_time": _dt_iso(state.as_of_time),
        "portfolio_value": state.portfolio_value,
        "cash": state.cash,
        "gross_exposure": state.gross_exposure,
        "net_exposure": state.net_exposure,
        "position_weights": dict(state.position_weights),
        "sector_exposure": state.sector_exposure,
        "drawdown": state.drawdown,
        "max_drawdown": state.max_drawdown,
        "portfolio_volatility": state.portfolio_volatility,
        "turnover": state.turnover,
        "concentration": state.concentration,
        "risk_budget_usage": state.risk_budget_usage,
        "risk_state_version": state.risk_state_version,
    }


def _dict_to_risk_state(data: Optional[dict]) -> Optional[PortfolioRiskState]:
    if data is None:
        return None
    return PortfolioRiskState(
        as_of_time=_dt_from_iso(data["as_of_time"]),
        portfolio_value=data["portfolio_value"],
        cash=data["cash"],
        gross_exposure=data.get("gross_exposure"),
        net_exposure=data.get("net_exposure"),
        position_weights=dict(data.get("position_weights") or {}),
        sector_exposure=data.get("sector_exposure"),
        drawdown=data.get("drawdown"),
        max_drawdown=data.get("max_drawdown"),
        portfolio_volatility=data.get("portfolio_volatility"),
        turnover=data.get("turnover"),
        concentration=data.get("concentration"),
        risk_budget_usage=data.get("risk_budget_usage"),
        risk_state_version=data.get("risk_state_version", "portfolio_risk_state_v1"),
    )


def position_sizing_result_to_payload(result: PositionSizingResult) -> dict:
    return {
        "sizing_id": result.sizing_id,
        "security_id": result.security_id,
        "as_of_time": _dt_iso(result.as_of_time),
        "status": result.status.value,
        "reason": result.reason,
        "decision_id": result.decision_id,
        "decision_action": result.decision_action.value if result.decision_action is not None else None,
        "proposed_target_weight": result.proposed_target_weight,
        "proposed_target_quantity": result.proposed_target_quantity,
        "current_weight": result.current_weight,
        "current_quantity": result.current_quantity,
        "sizing_version": result.sizing_version,
        "feature_version": result.feature_version,
        "prediction_id": result.prediction_id,
        "decision_version": result.decision_version,
        "prediction_version": result.prediction_version,
        "regime_version": result.regime_version,
        "data_version": list(result.data_version),
        "provenance": result.provenance.value,
        "experiment_id": result.experiment_id,
        "recorded_at": _dt_iso(result.recorded_at),
    }


def payload_to_position_sizing_result(data: dict) -> PositionSizingResult:
    return PositionSizingResult(
        sizing_id=data["sizing_id"],
        security_id=data["security_id"],
        as_of_time=_dt_from_iso(data["as_of_time"]),
        status=RiskCheckStatus(data["status"]),
        reason=data["reason"],
        decision_id=data.get("decision_id"),
        decision_action=DecisionAction(data["decision_action"]) if data.get("decision_action") else None,
        proposed_target_weight=data.get("proposed_target_weight"),
        proposed_target_quantity=data.get("proposed_target_quantity"),
        current_weight=data.get("current_weight"),
        current_quantity=data["current_quantity"],
        sizing_version=data["sizing_version"],
        feature_version=data.get("feature_version"),
        prediction_id=data.get("prediction_id"),
        decision_version=data.get("decision_version"),
        prediction_version=data.get("prediction_version"),
        regime_version=data.get("regime_version"),
        data_version=tuple(data.get("data_version") or ()),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def risk_checked_position_to_payload(checked: RiskCheckedPosition) -> dict:
    return {
        "risk_id": checked.risk_id,
        "security_id": checked.security_id,
        "as_of_time": _dt_iso(checked.as_of_time),
        "status": checked.status.value,
        "reason": checked.reason,
        "breached_limits": list(checked.breached_limits),
        "final_target_weight": checked.final_target_weight,
        "final_target_quantity": checked.final_target_quantity,
        "sizing_id": checked.sizing_id,
        "decision_id": checked.decision_id,
        "prediction_id": checked.prediction_id,
        "risk_state": _risk_state_to_dict(checked.risk_state),
        "risk_version": checked.risk_version,
        "feature_version": checked.feature_version,
        "sizing_version": checked.sizing_version,
        "decision_version": checked.decision_version,
        "prediction_version": checked.prediction_version,
        "regime_version": checked.regime_version,
        "data_version": list(checked.data_version),
        "strategy_version": checked.strategy_version,
        "provenance": checked.provenance.value,
        "experiment_id": checked.experiment_id,
        "recorded_at": _dt_iso(checked.recorded_at),
    }


def payload_to_risk_checked_position(data: dict) -> RiskCheckedPosition:
    return RiskCheckedPosition(
        risk_id=data["risk_id"],
        security_id=data["security_id"],
        as_of_time=_dt_from_iso(data["as_of_time"]),
        status=RiskCheckStatus(data["status"]),
        reason=data["reason"],
        breached_limits=tuple(data.get("breached_limits") or ()),
        final_target_weight=data.get("final_target_weight"),
        final_target_quantity=data.get("final_target_quantity"),
        sizing_id=data.get("sizing_id"),
        decision_id=data.get("decision_id"),
        prediction_id=data.get("prediction_id"),
        risk_state=_dict_to_risk_state(data.get("risk_state")),
        risk_version=data["risk_version"],
        feature_version=data.get("feature_version"),
        sizing_version=data.get("sizing_version"),
        decision_version=data.get("decision_version"),
        prediction_version=data.get("prediction_version"),
        regime_version=data.get("regime_version"),
        data_version=tuple(data.get("data_version") or ()),
        strategy_version=data.get("strategy_version"),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


# --------------------------------------------------------------------
# learning.models
# --------------------------------------------------------------------


def _evaluation_metrics_to_dict(m: EvaluationMetrics) -> dict:
    return {
        "sample_count": m.sample_count,
        "mean_absolute_error": m.mean_absolute_error,
        "mean_squared_error": m.mean_squared_error,
        "mean_label": m.mean_label,
    }


def _dict_to_evaluation_metrics(data: dict) -> EvaluationMetrics:
    return EvaluationMetrics(
        sample_count=data["sample_count"],
        mean_absolute_error=data.get("mean_absolute_error"),
        mean_squared_error=data.get("mean_squared_error"),
        mean_label=data.get("mean_label"),
    )


def training_dataset_to_payload(dataset: TrainingDataset) -> dict:
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.dataset_version,
        "created_at": _dt_iso(dataset.created_at),
        "source_experience_ids": list(dataset.source_experience_ids),
        "provenance": dataset.provenance.value,
        "feature_version": dataset.feature_version,
        "label_version": dataset.label_version,
        "data_version": list(dataset.data_version),
        "cleaning_config_version": dataset.cleaning_config_version,
        "label_config_version": dataset.label_config_version,
        "split_config_version": dataset.split_config_version,
        "sampling_config_version": dataset.sampling_config_version,
        "configuration_version": dataset.configuration_version,
        "sample_count": dataset.sample_count,
        "excluded_count": dataset.excluded_count,
        "quality_status": dataset.quality_status,
        "splits": {split.value: list(ids) for split, ids in dataset.splits.items()},
        "as_of_cutoff": _dt_iso(dataset.as_of_cutoff) if dataset.as_of_cutoff is not None else None,
    }


def payload_to_training_dataset(data: dict) -> TrainingDataset:
    return TrainingDataset(
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        created_at=_dt_from_iso(data["created_at"]),
        source_experience_ids=tuple(data.get("source_experience_ids") or ()),
        provenance=TradeProvenance(data["provenance"]),
        feature_version=data.get("feature_version"),
        label_version=data["label_version"],
        data_version=tuple(data.get("data_version") or ()),
        cleaning_config_version=data["cleaning_config_version"],
        label_config_version=data["label_config_version"],
        split_config_version=data["split_config_version"],
        sampling_config_version=data["sampling_config_version"],
        configuration_version=data["configuration_version"],
        sample_count=data["sample_count"],
        excluded_count=data["excluded_count"],
        quality_status=data["quality_status"],
        splits={SplitName(k): tuple(v) for k, v in (data.get("splits") or {}).items()},
        as_of_cutoff=_dt_from_iso(data.get("as_of_cutoff")),
    )


def candidate_model_to_payload(candidate: CandidateModelArtifact) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "status": candidate.status.value,
        "trainer_version": candidate.trainer_version,
        "dataset_id": candidate.dataset_id,
        "dataset_version": candidate.dataset_version,
        "feature_version": candidate.feature_version,
        "label_version": candidate.label_version,
        "parameters": candidate.parameters,
        "seed": candidate.seed,
        "trained_at": _dt_iso(candidate.trained_at),
        "provenance": candidate.provenance.value,
        "experiment_id": candidate.experiment_id,
    }


def payload_to_candidate_model(data: dict) -> CandidateModelArtifact:
    return CandidateModelArtifact(
        candidate_id=data["candidate_id"],
        status=CandidateModelStatus(data["status"]),
        trainer_version=data["trainer_version"],
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        feature_version=data.get("feature_version"),
        label_version=data["label_version"],
        parameters=data.get("parameters") or {},
        seed=data.get("seed"),
        trained_at=_dt_from_iso(data["trained_at"]),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
    )


def evaluation_result_to_payload(evaluation: EvaluationResult) -> dict:
    return {
        "evaluation_id": evaluation.evaluation_id,
        "candidate_id": evaluation.candidate_id,
        "dataset_id": evaluation.dataset_id,
        "dataset_version": evaluation.dataset_version,
        "train_metrics": _evaluation_metrics_to_dict(evaluation.train_metrics),
        "validation_metrics": _evaluation_metrics_to_dict(evaluation.validation_metrics),
        "test_metrics": _evaluation_metrics_to_dict(evaluation.test_metrics),
        "baseline_metrics": _evaluation_metrics_to_dict(evaluation.baseline_metrics),
        "evaluator_version": evaluation.evaluator_version,
        "evaluated_at": _dt_iso(evaluation.evaluated_at),
        "provenance": evaluation.provenance.value,
    }


def payload_to_evaluation_result(data: dict) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=data["evaluation_id"],
        candidate_id=data["candidate_id"],
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        train_metrics=_dict_to_evaluation_metrics(data["train_metrics"]),
        validation_metrics=_dict_to_evaluation_metrics(data["validation_metrics"]),
        test_metrics=_dict_to_evaluation_metrics(data["test_metrics"]),
        baseline_metrics=_dict_to_evaluation_metrics(data["baseline_metrics"]),
        evaluator_version=data["evaluator_version"],
        evaluated_at=_dt_from_iso(data["evaluated_at"]),
        provenance=TradeProvenance(data["provenance"]),
    )


def learning_experiment_to_payload(experiment: LearningExperimentRecord) -> dict:
    return {
        "experiment_id": experiment.experiment_id,
        "dataset_id": experiment.dataset_id,
        "dataset_version": experiment.dataset_version,
        "trainer_version": experiment.trainer_version,
        "evaluator_version": experiment.evaluator_version,
        "candidate_id": experiment.candidate_id,
        "evaluation_id": experiment.evaluation_id,
        "configuration_version": experiment.configuration_version,
        "seed": experiment.seed,
        "provenance": experiment.provenance.value,
        "status": experiment.status,
        "created_at": _dt_iso(experiment.created_at),
    }


def payload_to_learning_experiment(data: dict) -> LearningExperimentRecord:
    return LearningExperimentRecord(
        experiment_id=data["experiment_id"],
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        trainer_version=data["trainer_version"],
        evaluator_version=data["evaluator_version"],
        candidate_id=data["candidate_id"],
        evaluation_id=data["evaluation_id"],
        configuration_version=data["configuration_version"],
        seed=data.get("seed"),
        provenance=TradeProvenance(data["provenance"]),
        status=data["status"],
        created_at=_dt_from_iso(data["created_at"]),
    )


# -- Phase 10: Performance Attribution --------------------------------


def attribution_result_to_payload(result: AttributionResult) -> dict:
    return {
        "experiment_id": result.experiment_id,
        "market": result.market,
        "sector": result.sector,
        "factor": result.factor,
        "selection": result.selection,
        "timing": result.timing,
        "execution": result.execution,
        "computed_at": _dt_iso(result.computed_at),
    }


def payload_to_attribution_result(data: dict) -> AttributionResult:
    return AttributionResult(
        experiment_id=data["experiment_id"],
        market=data.get("market"),
        sector=data.get("sector"),
        factor=data.get("factor"),
        selection=data.get("selection"),
        timing=data.get("timing"),
        execution=data.get("execution"),
        computed_at=_dt_from_iso(data.get("computed_at")),
    )


# -- Phase 11: Model Evolution -----------------------------------------


def model_status_transition_to_payload(transition: ModelStatusTransition) -> dict:
    return {
        "transition_id": transition.transition_id,
        "candidate_id": transition.candidate_id,
        "dataset_id": transition.dataset_id,
        "dataset_version": transition.dataset_version,
        "evaluation_id": transition.evaluation_id,
        "from_status": transition.from_status.value,
        "to_status": transition.to_status.value,
        "passed": transition.passed,
        "criteria_version": transition.criteria_version,
        "criteria": transition.criteria,
        "reason": transition.reason,
        "provenance": transition.provenance.value,
        "evaluated_at": _dt_iso(transition.evaluated_at),
        "recorded_at": _dt_iso(transition.recorded_at),
    }


def payload_to_model_status_transition(data: dict) -> ModelStatusTransition:
    return ModelStatusTransition(
        transition_id=data["transition_id"],
        candidate_id=data["candidate_id"],
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        evaluation_id=data.get("evaluation_id"),
        from_status=CandidateModelStatus(data["from_status"]),
        to_status=CandidateModelStatus(data["to_status"]),
        passed=data["passed"],
        criteria_version=data["criteria_version"],
        criteria=data.get("criteria") or {},
        reason=data["reason"],
        provenance=TradeProvenance(data["provenance"]),
        evaluated_at=_dt_from_iso(data["evaluated_at"]),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def model_lineage_to_payload(lineage: ModelLineageRecord) -> dict:
    return {
        "candidate_id": lineage.candidate_id,
        "parent_candidate_id": lineage.parent_candidate_id,
        "generation": lineage.generation,
        "lineage_basis": lineage.lineage_basis,
        "dataset_id": lineage.dataset_id,
        "dataset_version": lineage.dataset_version,
        "provenance": lineage.provenance.value,
        "recorded_at": _dt_iso(lineage.recorded_at),
    }


def payload_to_model_lineage(data: dict) -> ModelLineageRecord:
    return ModelLineageRecord(
        candidate_id=data["candidate_id"],
        parent_candidate_id=data.get("parent_candidate_id"),
        generation=data["generation"],
        lineage_basis=data["lineage_basis"],
        dataset_id=data["dataset_id"],
        dataset_version=data["dataset_version"],
        provenance=TradeProvenance(data["provenance"]),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


# -- Phase 12: AI Gateway -----------------------------------------------


def ai_request_to_payload(request: AIRequest) -> dict:
    return {
        "request_id": request.request_id,
        "task_tier": request.task_tier.value,
        "prompt_template_id": request.prompt_template_id,
        "prompt_template_version": request.prompt_template_version,
        "payload": request.payload,
        "max_tokens": request.max_tokens,
        "requested_at": _dt_iso(request.requested_at),
        "provenance": request.provenance.value,
        "experiment_id": request.experiment_id,
        "response_schema": list(request.response_schema) if request.response_schema is not None else None,
    }


def payload_to_ai_request(data: dict) -> AIRequest:
    schema = data.get("response_schema")
    return AIRequest(
        request_id=data["request_id"],
        task_tier=TaskTier(data["task_tier"]),
        prompt_template_id=data["prompt_template_id"],
        prompt_template_version=data["prompt_template_version"],
        payload=data["payload"],
        max_tokens=data.get("max_tokens"),
        requested_at=_dt_from_iso(data["requested_at"]),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
        response_schema=tuple(schema) if schema else None,
    )


def _usage_info_to_dict(usage: Optional[UsageInfo]) -> Optional[dict]:
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _dict_to_usage_info(data: Optional[dict]) -> Optional[UsageInfo]:
    if data is None:
        return None
    return UsageInfo(
        prompt_tokens=data.get("prompt_tokens"), completion_tokens=data.get("completion_tokens"),
        total_tokens=data.get("total_tokens"),
    )


def ai_response_to_payload(response: AIResponse) -> dict:
    return {
        "response_id": response.response_id,
        "request_id": response.request_id,
        "status": response.status.value,
        "provider_id": response.provider_id,
        "model": response.model,
        "model_version": response.model_version,
        "prompt_template_version": response.prompt_template_version,
        "configuration_version": response.configuration_version,
        "content": response.content,
        "parsed": response.parsed,
        "usage": _usage_info_to_dict(response.usage),
        "latency_ms": response.latency_ms,
        "error_reason": response.error_reason,
        "attempt_count": response.attempt_count,
        "responded_at": _dt_iso(response.responded_at),
        "provenance": response.provenance.value,
        "experiment_id": response.experiment_id,
    }


def payload_to_ai_response(data: dict) -> AIResponse:
    return AIResponse(
        response_id=data["response_id"],
        request_id=data["request_id"],
        status=RequestStatus(data["status"]),
        provider_id=data.get("provider_id"),
        model=data.get("model"),
        model_version=data.get("model_version"),
        prompt_template_version=data["prompt_template_version"],
        configuration_version=data["configuration_version"],
        content=data.get("content"),
        parsed=data.get("parsed"),
        usage=_dict_to_usage_info(data.get("usage")),
        latency_ms=data.get("latency_ms"),
        error_reason=data.get("error_reason"),
        attempt_count=data["attempt_count"],
        responded_at=_dt_from_iso(data["responded_at"]),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
    )


def provider_quota_state_to_payload(state: ProviderQuotaState) -> dict:
    return {
        "state_id": state.state_id,
        "provider_id": state.provider_id,
        "observed_at": _dt_iso(state.observed_at),
        "remaining_requests": state.remaining_requests,
        "remaining_tokens": state.remaining_tokens,
        "reset_time": _dt_iso(state.reset_time),
        "health_status": state.health_status.value,
        "billing_status": state.billing_status.value,
        "enabled": state.enabled,
        "error_count": state.error_count,
        "last_success_at": _dt_iso(state.last_success_at),
        "last_error_at": _dt_iso(state.last_error_at),
        "last_error_reason": state.last_error_reason,
        "reason": state.reason,
    }


def payload_to_provider_quota_state(data: dict) -> ProviderQuotaState:
    return ProviderQuotaState(
        state_id=data["state_id"],
        provider_id=data["provider_id"],
        observed_at=_dt_from_iso(data["observed_at"]),
        remaining_requests=data.get("remaining_requests"),
        remaining_tokens=data.get("remaining_tokens"),
        reset_time=_dt_from_iso(data.get("reset_time")),
        health_status=ProviderHealthStatus(data["health_status"]),
        billing_status=BillingStatus(data["billing_status"]),
        enabled=data["enabled"],
        error_count=data["error_count"],
        last_success_at=_dt_from_iso(data.get("last_success_at")),
        last_error_at=_dt_from_iso(data.get("last_error_at")),
        last_error_reason=data.get("last_error_reason"),
        reason=data["reason"],
    )


# -- Phase 13: Toss Securities Adapter (Broker) --------------------------


def broker_request_to_payload(request: BrokerRequestRecord) -> dict:
    return {
        "request_id": request.request_id,
        "broker_id": request.broker_id,
        "operation": request.operation,
        "execution_mode": request.execution_mode,
        "client_order_id": request.client_order_id,
        "decision_id": request.decision_id,
        "sizing_id": request.sizing_id,
        "risk_assessment_id": request.risk_assessment_id,
        "configuration_version": request.configuration_version,
        "requested_at": _dt_iso(request.requested_at),
        "provenance": request.provenance.value,
        "payload": request.payload,
        "experiment_id": request.experiment_id,
    }


def payload_to_broker_request(data: dict) -> BrokerRequestRecord:
    return BrokerRequestRecord(
        request_id=data["request_id"],
        broker_id=data["broker_id"],
        operation=data["operation"],
        execution_mode=data["execution_mode"],
        client_order_id=data.get("client_order_id"),
        decision_id=data.get("decision_id"),
        sizing_id=data.get("sizing_id"),
        risk_assessment_id=data.get("risk_assessment_id"),
        configuration_version=data["configuration_version"],
        requested_at=_dt_from_iso(data["requested_at"]),
        provenance=TradeProvenance(data["provenance"]),
        payload=data.get("payload") or {},
        experiment_id=data.get("experiment_id"),
    )


def broker_response_to_payload(response: BrokerResponseRecord) -> dict:
    return {
        "response_id": response.response_id,
        "request_id": response.request_id,
        "broker_id": response.broker_id,
        "operation": response.operation,
        "status": response.status,
        "broker_order_id": response.broker_order_id,
        "error_code": response.error_code,
        "attempt_count": response.attempt_count,
        "latency_ms": response.latency_ms,
        "responded_at": _dt_iso(response.responded_at),
        "provenance": response.provenance.value,
        "metadata": response.metadata,
        "experiment_id": response.experiment_id,
    }


def payload_to_broker_response(data: dict) -> BrokerResponseRecord:
    return BrokerResponseRecord(
        response_id=data["response_id"],
        request_id=data["request_id"],
        broker_id=data["broker_id"],
        operation=data["operation"],
        status=data["status"],
        broker_order_id=data.get("broker_order_id"),
        error_code=data.get("error_code"),
        attempt_count=data["attempt_count"],
        latency_ms=data.get("latency_ms"),
        responded_at=_dt_from_iso(data["responded_at"]),
        provenance=TradeProvenance(data["provenance"]),
        metadata=data.get("metadata") or {},
        experiment_id=data.get("experiment_id"),
    )


def order_status_observation_to_payload(observation: OrderStatusObservation) -> dict:
    return {
        "observation_id": observation.observation_id,
        "client_order_id": observation.client_order_id,
        "broker_id": observation.broker_id,
        "broker_order_id": observation.broker_order_id,
        "status": observation.status.value,
        "filled_quantity": observation.filled_quantity,
        "avg_fill_price": observation.avg_fill_price,
        "observed_at": _dt_iso(observation.observed_at),
        "raw_status_code": observation.raw_status_code,
    }


def payload_to_order_status_observation(data: dict) -> OrderStatusObservation:
    return OrderStatusObservation(
        observation_id=data["observation_id"],
        client_order_id=data["client_order_id"],
        broker_id=data["broker_id"],
        broker_order_id=data.get("broker_order_id"),
        status=BrokerOrderStatus(data["status"]),
        filled_quantity=data.get("filled_quantity"),
        avg_fill_price=data.get("avg_fill_price"),
        observed_at=_dt_from_iso(data["observed_at"]),
        raw_status_code=data.get("raw_status_code"),
    )


# -- Phase 14: Monitoring ------------------------------------------------

# `MonitoringEvent.metrics` is a generic `dict` -- every value in it is
# already a JSON-native primitive (float/int/str/None/list) *except*
# `compute_data_quality_metrics`'s own `latest_available_time`, which is
# a real `datetime` (needed for `collectors.py`'s staleness arithmetic).
# `json_dumps`'s own `_default` hook already turns any `datetime` value
# into an ISO string on encode; these two helpers make that reversible
# on decode for the one key known to hold a timestamp, so a round-tripped
# `MonitoringEvent.metrics` is identical to the one that was persisted.
_METRICS_DATETIME_KEYS = frozenset({"latest_available_time"})


def _deserialize_metrics(metrics: Optional[dict]) -> dict:
    if not metrics:
        return {}
    result = dict(metrics)
    for key in _METRICS_DATETIME_KEYS:
        if key in result and isinstance(result[key], str):
            # `json_dumps`'s own `_default` hook encodes a `datetime` via
            # `to_utc_naive(...).isoformat()` -- a naive UTC string, not
            # `_dt_iso`'s offset-preserving form -- so this must reverse
            # with `from_utc_naive`, not `_dt_from_iso`.
            result[key] = from_utc_naive(datetime.fromisoformat(result[key]))
    return result


def monitoring_event_to_payload(event: MonitoringEvent) -> dict:
    return {
        "event_id": event.event_id,
        "component": event.component.value,
        "event_type": event.event_type,
        "severity": event.severity.value,
        "observed_at": _dt_iso(event.observed_at),
        "as_of_time": _dt_iso(event.as_of_time),
        "metrics": event.metrics,
        "threshold_version": event.threshold_version,
        "component_version": event.component_version,
        "data_version": list(event.data_version),
        "message": event.message,
        "provenance": event.provenance.value,
        "correlation_id": event.correlation_id,
        "source_record_ids": list(event.source_record_ids),
        "configuration_version": event.configuration_version,
        "experiment_id": event.experiment_id,
    }


def payload_to_monitoring_event(data: dict) -> MonitoringEvent:
    return MonitoringEvent(
        event_id=data["event_id"],
        component=MonitoringComponent(data["component"]),
        event_type=data["event_type"],
        severity=AlertSeverity(data["severity"]),
        observed_at=_dt_from_iso(data["observed_at"]),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        metrics=_deserialize_metrics(data.get("metrics")),
        threshold_version=data.get("threshold_version", "unknown"),
        component_version=data.get("component_version"),
        data_version=tuple(data.get("data_version") or ()),
        message=data.get("message", ""),
        provenance=TradeProvenance(data["provenance"]),
        correlation_id=data.get("correlation_id"),
        source_record_ids=tuple(data.get("source_record_ids") or ()),
        configuration_version=data.get("configuration_version", "unknown"),
        experiment_id=data.get("experiment_id"),
    )


def component_health_to_payload(health: ComponentHealth) -> dict:
    return {
        "health_id": health.health_id,
        "component": health.component.value,
        "status": health.status.value,
        "as_of_time": _dt_iso(health.as_of_time),
        "reason": health.reason,
        "checks": health.checks,
        "configuration_version": health.configuration_version,
        "event_id": health.event_id,
        "recorded_at": _dt_iso(health.recorded_at),
    }


def payload_to_component_health(data: dict) -> ComponentHealth:
    return ComponentHealth(
        health_id=data["health_id"],
        component=MonitoringComponent(data["component"]),
        status=ComponentHealthStatus(data["status"]),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        reason=data["reason"],
        checks=data.get("checks") or {},
        configuration_version=data.get("configuration_version", "unknown"),
        event_id=data.get("event_id"),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def drift_result_to_payload(drift: DriftResult) -> dict:
    return {
        "drift_id": drift.drift_id,
        "component": drift.component.value,
        "metric_name": drift.metric_name,
        "status": drift.status.value,
        "statistic": drift.statistic,
        "threshold": drift.threshold,
        "as_of_time": _dt_iso(drift.as_of_time),
        "baseline_summary": drift.baseline_summary,
        "current_summary": drift.current_summary,
        "sample_count_baseline": drift.sample_count_baseline,
        "sample_count_current": drift.sample_count_current,
        "configuration_version": drift.configuration_version,
        "reason": drift.reason,
        "recorded_at": _dt_iso(drift.recorded_at),
    }


def payload_to_drift_result(data: dict) -> DriftResult:
    return DriftResult(
        drift_id=data["drift_id"],
        component=MonitoringComponent(data["component"]),
        metric_name=data["metric_name"],
        status=DriftStatus(data["status"]),
        statistic=data.get("statistic"),
        threshold=data.get("threshold"),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        baseline_summary=data.get("baseline_summary") or {},
        current_summary=data.get("current_summary") or {},
        sample_count_baseline=data.get("sample_count_baseline"),
        sample_count_current=data.get("sample_count_current"),
        configuration_version=data.get("configuration_version", "unknown"),
        reason=data.get("reason", ""),
        recorded_at=_dt_from_iso(data.get("recorded_at")),
    )


def alert_to_payload(alert: Alert) -> dict:
    return {
        "alert_id": alert.alert_id,
        "severity": alert.severity.value,
        "component": alert.component.value,
        "message": alert.message,
        "raised_at": _dt_iso(alert.raised_at),
        "event_id": alert.event_id,
        "provenance": alert.provenance.value,
        "experiment_id": alert.experiment_id,
    }


def payload_to_alert(data: dict) -> Alert:
    return Alert(
        alert_id=data["alert_id"],
        severity=AlertSeverity(data["severity"]),
        component=MonitoringComponent(data["component"]),
        message=data["message"],
        raised_at=_dt_from_iso(data["raised_at"]),
        event_id=data.get("event_id"),
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
    )


# -- Phase 15: Paper Trading ----------------------------------------------


def validated_order_to_payload(order: ValidatedOrder) -> dict:
    return {
        "client_order_id": order.client_order_id,
        "security_id": order.security_id,
        "side": order.side.value,
        "quantity": order.quantity,
        "order_type": order.order_type.value,
        "as_of_time": _dt_iso(order.as_of_time),
        "decision_id": order.decision_id,
        "sizing_id": order.sizing_id,
        "risk_assessment_id": order.risk_assessment_id,
        "configuration_version": order.configuration_version,
        "provenance": order.provenance.value,
        "experiment_id": order.experiment_id,
    }


def payload_to_validated_order(data: dict) -> ValidatedOrder:
    return ValidatedOrder(
        client_order_id=data["client_order_id"],
        security_id=data["security_id"],
        side=OrderSide(data["side"]),
        quantity=data["quantity"],
        order_type=OrderType(data["order_type"]),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        decision_id=data["decision_id"],
        sizing_id=data["sizing_id"],
        risk_assessment_id=data["risk_assessment_id"],
        configuration_version=data["configuration_version"],
        provenance=TradeProvenance(data["provenance"]),
        experiment_id=data.get("experiment_id"),
    )


def fill_to_payload(fill: Fill) -> dict:
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
        "decision_time": _dt_iso(fill.decision_time),
        "execution_time": _dt_iso(fill.execution_time),
        "data_version": fill.data_version,
    }


def payload_to_fill(data: dict) -> Fill:
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
        decision_time=_dt_from_iso(data["decision_time"]),
        execution_time=_dt_from_iso(data["execution_time"]),
        data_version=data["data_version"],
    )


def paper_order_record_to_payload(record: PaperOrderRecord) -> dict:
    return {
        "validated_order": validated_order_to_payload(record.validated_order),
        "requested_at": _dt_iso(record.requested_at),
        "initial_status": record.initial_status.value,
        "rejection_reason": record.rejection_reason,
        "configuration_version": record.configuration_version,
    }


def payload_to_paper_order_record(data: dict) -> PaperOrderRecord:
    return PaperOrderRecord(
        validated_order=payload_to_validated_order(data["validated_order"]),
        requested_at=_dt_from_iso(data["requested_at"]),
        initial_status=BrokerOrderStatus(data["initial_status"]),
        rejection_reason=data.get("rejection_reason"),
        configuration_version=data["configuration_version"],
    )


def paper_fill_record_to_payload(record: PaperFillRecord) -> dict:
    return {
        "fill_id": record.fill_id,
        "client_order_id": record.client_order_id,
        "fill": fill_to_payload(record.fill),
        "configuration_version": record.configuration_version,
        "recorded_at": _dt_iso(record.recorded_at),
    }


def payload_to_paper_fill_record(data: dict) -> PaperFillRecord:
    return PaperFillRecord(
        fill_id=data["fill_id"],
        client_order_id=data["client_order_id"],
        fill=payload_to_fill(data["fill"]),
        configuration_version=data["configuration_version"],
        recorded_at=_dt_from_iso(data["recorded_at"]),
    )


# -- Phase 16: Live Trading ------------------------------------------------


def kill_switch_event_to_payload(event: KillSwitchEvent) -> dict:
    return {
        "event_id": event.event_id,
        "engaged": event.engaged,
        "reason": event.reason,
        "triggered_by": event.triggered_by,
        "occurred_at": _dt_iso(event.occurred_at),
        "configuration_version": event.configuration_version,
    }


def payload_to_kill_switch_event(data: dict) -> KillSwitchEvent:
    return KillSwitchEvent(
        event_id=data["event_id"],
        engaged=data["engaged"],
        reason=data["reason"],
        triggered_by=data["triggered_by"],
        occurred_at=_dt_from_iso(data["occurred_at"]),
        configuration_version=data["configuration_version"],
    )


def reconciliation_result_to_payload(result: ReconciliationResult) -> dict:
    return {
        "reconciliation_id": result.reconciliation_id,
        "target": result.target,
        "subject_id": result.subject_id,
        "status": result.status.value,
        "as_of_time": _dt_iso(result.as_of_time),
        "details": result.details,
        "configuration_version": result.configuration_version,
    }


def payload_to_reconciliation_result(data: dict) -> ReconciliationResult:
    return ReconciliationResult(
        reconciliation_id=data["reconciliation_id"],
        target=data["target"],
        subject_id=data["subject_id"],
        status=ReconciliationStatus(data["status"]),
        as_of_time=_dt_from_iso(data["as_of_time"]),
        details=data.get("details") or {},
        configuration_version=data.get("configuration_version", "unknown"),
    )


# --------------------------------------------------------------------
# broker.paper.performance (Phase 18)
# --------------------------------------------------------------------


def _benchmark_comparison_to_payload(comparison: BenchmarkComparison) -> dict:
    return {
        "status": comparison.status,
        "benchmark_id": comparison.benchmark_id,
        "benchmark_return_type": comparison.benchmark_return_type,
        "benchmark_cumulative_return": comparison.benchmark_cumulative_return,
        "benchmark_cagr": comparison.benchmark_cagr,
        "benchmark_max_drawdown": comparison.benchmark_max_drawdown,
        "excess_return": comparison.excess_return,
        "annualized_excess_return": comparison.annualized_excess_return,
    }


def _payload_to_benchmark_comparison(data: dict) -> BenchmarkComparison:
    return BenchmarkComparison(
        status=data["status"],
        benchmark_id=data.get("benchmark_id"),
        benchmark_return_type=data.get("benchmark_return_type"),
        benchmark_cumulative_return=data.get("benchmark_cumulative_return"),
        benchmark_cagr=data.get("benchmark_cagr"),
        benchmark_max_drawdown=data.get("benchmark_max_drawdown"),
        excess_return=data.get("excess_return"),
        annualized_excess_return=data.get("annualized_excess_return"),
    )


def paper_performance_report_to_payload(report: PaperPerformanceReport) -> dict:
    return {
        "report_id": report.report_id,
        "paper_session_id": report.paper_session_id,
        "evaluated_at": _dt_iso(report.evaluated_at),
        "period_start": _dt_iso(report.period_start),
        "period_end": _dt_iso(report.period_end),
        "total_return": report.total_return,
        "cagr": report.cagr,
        "volatility": report.volatility,
        "sharpe_ratio": report.sharpe_ratio,
        "sortino_ratio": report.sortino_ratio,
        "calmar_ratio": report.calmar_ratio,
        "max_drawdown": report.max_drawdown,
        "turnover": report.turnover,
        "total_transaction_cost": report.total_transaction_cost,
        "total_slippage": report.total_slippage,
        "num_trades": report.num_trades,
        "win_rate": report.win_rate,
        "avg_trade_return": report.avg_trade_return,
        "realized_pnl": report.realized_pnl,
        "benchmark": _benchmark_comparison_to_payload(report.benchmark),
        "configuration_version": report.configuration_version,
        "provenance": report.provenance.value,
        "strategy_version": report.strategy_version,
        "model_version": report.model_version,
        "experiment_id": report.experiment_id,
        "reasons": report.reasons,
    }


def payload_to_paper_performance_report(data: dict) -> PaperPerformanceReport:
    return PaperPerformanceReport(
        report_id=data["report_id"],
        paper_session_id=data["paper_session_id"],
        evaluated_at=_dt_from_iso(data["evaluated_at"]),
        period_start=_dt_from_iso(data.get("period_start")),
        period_end=_dt_from_iso(data.get("period_end")),
        total_return=data.get("total_return"),
        cagr=data.get("cagr"),
        volatility=data.get("volatility"),
        sharpe_ratio=data.get("sharpe_ratio"),
        sortino_ratio=data.get("sortino_ratio"),
        calmar_ratio=data.get("calmar_ratio"),
        max_drawdown=data.get("max_drawdown"),
        turnover=data.get("turnover"),
        total_transaction_cost=data.get("total_transaction_cost"),
        total_slippage=data.get("total_slippage"),
        num_trades=data["num_trades"],
        win_rate=data.get("win_rate"),
        avg_trade_return=data.get("avg_trade_return"),
        realized_pnl=data.get("realized_pnl"),
        benchmark=_payload_to_benchmark_comparison(data["benchmark"]),
        configuration_version=data.get("configuration_version", "unknown"),
        provenance=TradeProvenance(data.get("provenance", TradeProvenance.PAPER_TRADING.value)),
        strategy_version=data.get("strategy_version", "unknown"),
        model_version=data.get("model_version"),
        experiment_id=data.get("experiment_id"),
        reasons=data.get("reasons") or {},
    )
