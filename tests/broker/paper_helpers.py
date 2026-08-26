"""Shared test helpers for the Phase 15 Paper Trading test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from broker.models import ValidatedOrder
from broker.paper.config import PaperTradingConfig

from backtest.enums import OrderSide, OrderType

from data_infra.models import PriceBar, Provenance

from trade_journal.enums import TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_paper_config(**overrides) -> PaperTradingConfig:
    return PaperTradingConfig(**overrides)


def make_provenance(record_id: str, retrieved_at: datetime, source: str = "test_source") -> Provenance:
    return Provenance(
        source=source, source_dataset="test_dataset", source_record_id=record_id,
        retrieved_at=retrieved_at, data_version="dv-test-1",
    )


def make_bar(
    *, security_id: str = "AAA", timestamp: datetime = utc(2024, 1, 2), close: float = 100.0,
    volume: float = 1_000.0, available_time: Optional[datetime] = None,
) -> PriceBar:
    available_time = available_time if available_time is not None else timestamp
    return PriceBar(
        security_id=security_id, timestamp=timestamp, open=close, high=close * 1.005, low=close * 0.995,
        close=close, volume=volume, available_time=available_time, ingestion_time=available_time,
        provenance=make_provenance(f"{security_id}-{timestamp.isoformat()}", available_time),
    )


def make_validated_order(
    *, client_order_id: str = "CID-000001", security_id: str = "AAA", side: OrderSide = OrderSide.BUY,
    quantity: float = 10.0, as_of_time: datetime = utc(2024, 1, 2), decision_id: str = "DEC-000001",
    sizing_id: str = "SIZE-000001", risk_assessment_id: str = "RISK-000001",
    provenance: TradeProvenance = TradeProvenance.PAPER_TRADING,
) -> ValidatedOrder:
    return ValidatedOrder(
        client_order_id=client_order_id, security_id=security_id, side=side, quantity=quantity,
        order_type=OrderType.MARKET, as_of_time=as_of_time, decision_id=decision_id, sizing_id=sizing_id,
        risk_assessment_id=risk_assessment_id, configuration_version="cfg-v1", provenance=provenance,
    )


__all__ = ["utc", "make_paper_config", "make_provenance", "make_bar", "make_validated_order"]
