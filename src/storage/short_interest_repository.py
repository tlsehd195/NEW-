"""DuckDBShortInterestRepository: persistent storage + point-in-time-safe
query for `ShortInterestRecord`s (Session 36 continued). Mirrors
`DuckDBInsiderRepository`'s exact shape and point-in-time discipline
(`available_time <= as_of_time` on every read, idempotent insert via
`ON CONFLICT ... DO NOTHING` on the natural key), applied to short
interest reports instead of insider transactions -- see that module's
own docstring for the reasoning this one deliberately repeats rather
than abstracts, matching this project's established per-repository-type
convention."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.short_interest_models import ShortInterestRecord

from storage.engine import StorageEngine
from storage.serialization import row_to_short_interest_record, short_interest_record_to_row, to_utc_naive


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_COLUMNS = (
    "provenance_source_record_id", "security_id", "settlement_date", "short_interest_quantity",
    "average_daily_volume", "days_to_cover", "available_time", "ingestion_time",
    "provenance_source", "provenance_source_dataset", "provenance_retrieved_at",
    "provenance_data_version", "provenance_schema_version",
)


class DuckDBShortInterestRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def add_short_interest(self, record: ShortInterestRecord) -> None:
        row = short_interest_record_to_row(record)
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        self._engine.connection.execute(
            f"INSERT INTO short_interest_records ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in _COLUMNS],
        )

    def add_short_interest_records(self, records: Sequence[ShortInterestRecord]) -> int:
        """Convenience batch wrapper over `add_short_interest` -- returns
        how many records were passed, not how many were actually new
        (same caveat as `DuckDBInsiderRepository.add_insider_transactions`)."""
        for record in records:
            self.add_short_interest(record)
        return len(records)

    def get_latest_short_interest(self, security_id: str, as_of_time: datetime) -> Optional[ShortInterestRecord]:
        """The most recent report for `security_id` whose `available_time
        <= as_of_time` (look-ahead guard), ranked by `settlement_date`
        -- `None` if no such report exists yet, never a fabricated one."""
        _require_aware("as_of_time", as_of_time)
        sql = (
            "SELECT * FROM short_interest_records WHERE security_id = ? AND available_time <= ? "
            "ORDER BY settlement_date DESC LIMIT 1"
        )
        cur = self._engine.connection.execute(sql, [security_id, to_utc_naive(as_of_time)])
        rows = _rows(cur)
        return row_to_short_interest_record(rows[0]) if rows else None

    def get_short_interest_history(
        self, security_id: str, as_of_time: datetime, *, start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[ShortInterestRecord]:
        """Every report for `security_id` whose `available_time <=
        as_of_time`, optionally restricted to `settlement_date` within
        `[start, end]`, sorted by `settlement_date`."""
        _require_aware("as_of_time", as_of_time)
        if start is not None:
            _require_aware("start", start)
        if end is not None:
            _require_aware("end", end)

        conditions = ["security_id = ?", "available_time <= ?"]
        params: list = [security_id, to_utc_naive(as_of_time)]
        if start is not None:
            conditions.append("settlement_date >= ?")
            params.append(to_utc_naive(start))
        if end is not None:
            conditions.append("settlement_date <= ?")
            params.append(to_utc_naive(end))

        sql = f"SELECT * FROM short_interest_records WHERE {' AND '.join(conditions)} ORDER BY settlement_date"
        cur = self._engine.connection.execute(sql, params)
        return [row_to_short_interest_record(r) for r in _rows(cur)]
