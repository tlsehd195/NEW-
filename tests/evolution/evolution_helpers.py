"""Shared test helpers for the Phase 11 Model Evolution test suite."""

from __future__ import annotations

from datetime import datetime

from learning_helpers import build_journal_with_closed_trades, utc

from learning.config import TrainingDatasetConfig
from learning.dataset import DatasetBuildResult, build_training_dataset

from trade_journal.enums import TradeProvenance


def build_dataset(
    count: int = 12,
    *,
    start: datetime = utc(2024, 1, 2),
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
    config: TrainingDatasetConfig = TrainingDatasetConfig(),
) -> DatasetBuildResult:
    journal, records = build_journal_with_closed_trades(count, start=start, provenance=provenance)
    return build_training_dataset(
        journal, records, provenance=provenance, config=config, created_at=start,
    )


__all__ = ["utc", "build_dataset", "build_journal_with_closed_trades"]
