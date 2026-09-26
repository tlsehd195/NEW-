"""DuckDBMacroRepository: persistent storage + point-in-time query for
`MacroObservationRecord`s (ADR-0217). Mirrors
`DuckDBShortInterestRepository`'s shape (idempotent insert on the natural
key, `available_time <= as_of_time` on every read), with one addition
that data needs: several vintages of the same observation coexist, so a
read picks, per `observation_date`, the latest vintage already known at
`as_of_time` -- never a later revision."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from data_infra.macro_models import MacroObservationRecord, vintage_available_time

from storage.engine import StorageEngine
from storage.serialization import macro_observation_record_to_row, row_to_macro_observation_record, to_utc_naive


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_COLUMNS = (
    "provenance_source_record_id", "series_id", "observation_date", "value", "realtime_start",
    "realtime_end", "available_time", "ingestion_time", "provenance_source",
    "provenance_source_dataset", "provenance_retrieved_at", "provenance_data_version",
    "provenance_schema_version",
)


def _withdrawn_as_of(record: MacroObservationRecord, as_of_time: datetime) -> bool:
    """True when ALFRED says this vintage stopped being current (a
    `realtime_end`) early enough that the change is already known at
    `as_of_time`, yet no later vintage for the same date exists -- i.e.
    FRED removed the observation. The end is "known" on the same
    conservative schedule a new vintage starting the next day would be."""
    if record.realtime_end is None:
        return False
    return vintage_available_time((record.realtime_end + timedelta(days=1)).date()) <= as_of_time


class DuckDBMacroRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def add_macro_observations(self, records: Sequence[MacroObservationRecord]) -> int:
        """Inserts every record not already stored (by natural key);
        returns how many records were passed, not how many were new."""
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        sql = (
            f"INSERT INTO macro_observation_vintages ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING"
        )
        rows = [macro_observation_record_to_row(r) for r in records]
        if rows:
            self._engine.connection.executemany(sql, [[row[c] for c in _COLUMNS] for row in rows])
        return len(records)

    def get_series_as_of(
        self, series_id: str, as_of_time: datetime, *, start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[MacroObservationRecord]:
        """The series exactly as it could have been read at `as_of_time`:
        per `observation_date` (optionally within `[start, end]`), the
        latest vintage whose `available_time <= as_of_time`, sorted by
        `observation_date`. Observations whose known value is FRED's "."
        (`value is None`) or that FRED had withdrawn by then are left out."""
        _require_aware("as_of_time", as_of_time)
        conditions = ["series_id = ?", "available_time <= ?"]
        params: list = [series_id, to_utc_naive(as_of_time)]
        if start is not None:
            _require_aware("start", start)
            conditions.append("observation_date >= ?")
            params.append(to_utc_naive(start))
        if end is not None:
            _require_aware("end", end)
            conditions.append("observation_date <= ?")
            params.append(to_utc_naive(end))
        sql = (
            f"SELECT * FROM macro_observation_vintages WHERE {' AND '.join(conditions)} "
            "QUALIFY row_number() OVER (PARTITION BY observation_date ORDER BY realtime_start DESC) = 1 "
            "ORDER BY observation_date"
        )
        records = [row_to_macro_observation_record(r) for r in _rows(self._engine.connection.execute(sql, params))]
        return [r for r in records if r.value is not None and not _withdrawn_as_of(r, as_of_time)]

    def get_latest_as_of(self, series_id: str, as_of_time: datetime) -> Optional[MacroObservationRecord]:
        """The most recent observation of `series_id` known at
        `as_of_time` (see `get_series_as_of`), or `None`."""
        series = self.get_series_as_of(series_id, as_of_time)
        return series[-1] if series else None

    def get_all_vintages(self, series_id: str) -> list[MacroObservationRecord]:
        """Every stored vintage, for audits and coverage reports -- not
        point-in-time safe, never for backtest reads."""
        sql = (
            "SELECT * FROM macro_observation_vintages WHERE series_id = ? "
            "ORDER BY observation_date, realtime_start"
        )
        return [row_to_macro_observation_record(r) for r in _rows(self._engine.connection.execute(sql, [series_id]))]
