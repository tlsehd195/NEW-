"""Shared test helpers for the Phase 1 data infrastructure test suite."""

from __future__ import annotations

from datetime import datetime, timezone

from data_infra.models import Provenance


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_provenance(
    *,
    source: str = "test_source",
    source_dataset: str = "test_dataset",
    source_record_id: str = "rec-1",
    retrieved_at: datetime | None = None,
    data_version: str = "v1",
    schema_version: int = 1,
) -> Provenance:
    return Provenance(
        source=source,
        source_dataset=source_dataset,
        source_record_id=source_record_id,
        retrieved_at=retrieved_at or utc(2024, 1, 1),
        data_version=data_version,
        schema_version=schema_version,
    )
