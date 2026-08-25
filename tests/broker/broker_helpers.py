"""Shared test helpers for the Phase 13 Broker Adapter test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from broker.config import BrokerConfig

from risk.enums import RiskCheckStatus
from risk.models import RiskCheckedPosition

from trade_journal.enums import TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_risk_checked_position(
    *,
    risk_id: str = "RISK-000001",
    security_id: str = "AAA",
    as_of_time: datetime = utc(2024, 1, 2),
    status: RiskCheckStatus = RiskCheckStatus.PASS,
    reason: str = "normal_sizing",
    final_target_weight: Optional[float] = 0.10,
    final_target_quantity: Optional[float] = 50.0,
    sizing_id: Optional[str] = "SIZE-000001",
    decision_id: Optional[str] = "DEC-OUT-000001",
    prediction_id: Optional[str] = "PRED-000001",
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
    experiment_id: Optional[str] = None,
) -> RiskCheckedPosition:
    return RiskCheckedPosition(
        risk_id=risk_id, security_id=security_id, as_of_time=as_of_time, status=status, reason=reason,
        breached_limits=(), final_target_weight=final_target_weight, final_target_quantity=final_target_quantity,
        sizing_id=sizing_id, decision_id=decision_id, prediction_id=prediction_id, risk_state=None,
        risk_version="test_risk_engine_v1", feature_version="test_feature_v1",
        provenance=provenance, experiment_id=experiment_id,
    )


def make_broker_config(**overrides) -> BrokerConfig:
    return BrokerConfig(**overrides)


__all__ = ["utc", "make_risk_checked_position", "make_broker_config"]
