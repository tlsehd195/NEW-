"""Category: persistence, idempotency and point-in-time vintage
selection for `DuckDBMacroRepository` (ADR-0217): a read at `as_of`
must see the value as first published, not a later revision, and must
not see an observation before its release."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from data_infra.providers.fred import FredVintageObservation, vintage_to_macro_record

from storage.macro_repository import DuckDBMacroRepository
from storage_helpers import new_engine

_NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def _utc(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def _rec(obs: date, value: Optional[float], start: date, end: Optional[date] = None, series="PAYEMS"):
    return vintage_to_macro_record(
        FredVintageObservation(series, obs, value, start, end, _NOW), ingestion_time=_NOW
    )


def _payems_with_revision():
    # January payrolls: first print on Feb 2, revised on Mar 8.
    return [
        _rec(date(2024, 1, 1), 100.0, date(2024, 2, 2), date(2024, 3, 7)),
        _rec(date(2024, 1, 1), 105.0, date(2024, 3, 8)),
        _rec(date(2024, 2, 1), 110.0, date(2024, 3, 8)),
    ]


def test_value_is_invisible_before_its_release(tmp_path) -> None:
    repo = DuckDBMacroRepository(new_engine(tmp_path))
    repo.add_macro_observations(_payems_with_revision())
    # Released Feb 2 (US date) -> available Feb 3 06:00 UTC.
    assert repo.get_series_as_of("PAYEMS", _utc(2024, 2, 3, 5)) == []
    assert [r.value for r in repo.get_series_as_of("PAYEMS", _utc(2024, 2, 3, 6))] == [100.0]


def test_first_print_is_used_until_the_revision_is_known(tmp_path) -> None:
    repo = DuckDBMacroRepository(new_engine(tmp_path))
    repo.add_macro_observations(_payems_with_revision())
    assert [r.value for r in repo.get_series_as_of("PAYEMS", _utc(2024, 3, 8, 12))] == [100.0]
    after = repo.get_series_as_of("PAYEMS", _utc(2024, 3, 9, 6))
    assert [(r.observation_date, r.value) for r in after] == [(_utc(2024, 1, 1), 105.0), (_utc(2024, 2, 1), 110.0)]
    assert repo.get_latest_as_of("PAYEMS", _utc(2024, 3, 9, 6)).value == 110.0


def test_insert_is_idempotent_and_survives_restart(tmp_path) -> None:
    engine = new_engine(tmp_path)
    repo = DuckDBMacroRepository(engine)
    repo.add_macro_observations(_payems_with_revision())
    repo.add_macro_observations(_payems_with_revision())
    engine.close()
    assert len(DuckDBMacroRepository(new_engine(tmp_path)).get_all_vintages("PAYEMS")) == 3


def test_missing_value_marker_and_withdrawn_observation_are_skipped(tmp_path) -> None:
    repo = DuckDBMacroRepository(new_engine(tmp_path))
    repo.add_macro_observations([
        _rec(date(2024, 1, 2), None, date(2024, 1, 3), series="VIXCLS"),
        # Published Jan 4, withdrawn after Jan 10 with no successor vintage.
        _rec(date(2024, 1, 3), 13.0, date(2024, 1, 4), date(2024, 1, 10), series="VIXCLS"),
    ])
    assert [r.value for r in repo.get_series_as_of("VIXCLS", _utc(2024, 1, 8))] == [13.0]
    assert repo.get_series_as_of("VIXCLS", _utc(2024, 1, 12, 6)) == []


def test_date_range_filter(tmp_path) -> None:
    repo = DuckDBMacroRepository(new_engine(tmp_path))
    repo.add_macro_observations(_payems_with_revision())
    result = repo.get_series_as_of("PAYEMS", _utc(2025, 1, 1), start=_utc(2024, 2, 1), end=_utc(2024, 2, 1))
    assert [r.value for r in result] == [110.0]
