"""Category: point-in-time guard for macro observations (ADR-0217) --
`available_time` comes from the ALFRED vintage date, never the
observation date."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from data_infra.macro_models import MACRO_SERIES_CATALOG, vintage_available_time
from data_infra.providers.fred import FredVintageObservation, vintage_to_macro_record


def test_vintage_available_time_is_next_day_0600_utc() -> None:
    assert vintage_available_time(date(2024, 2, 13)) == datetime(2024, 2, 14, 6, tzinfo=timezone.utc)


def test_record_available_time_uses_realtime_start_not_observation_date() -> None:
    obs = FredVintageObservation(
        series_id="CPIAUCSL", observation_date=date(2024, 1, 1), value=309.7,
        realtime_start=date(2024, 2, 13), realtime_end=None, retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )
    record = vintage_to_macro_record(obs, ingestion_time=datetime(2026, 9, 26, tzinfo=timezone.utc))
    assert record.observation_date == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert record.available_time == datetime(2024, 2, 14, 6, tzinfo=timezone.utc)
    assert record.provenance.source_record_id == "fred:CPIAUCSL:2024-01-01:2024-02-13"


def test_non_finite_value_is_rejected() -> None:
    obs = FredVintageObservation(
        series_id="VIXCLS", observation_date=date(2024, 1, 2), value=float("nan"),
        realtime_start=date(2024, 1, 3), realtime_end=None, retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError):
        vintage_to_macro_record(obs, ingestion_time=datetime(2026, 9, 26, tzinfo=timezone.utc))


def test_catalog_ids_are_unique() -> None:
    ids = [spec.series_id for spec in MACRO_SERIES_CATALOG]
    assert len(ids) == len(set(ids))
