"""DuckDBInstitutionalHoldingRepository: persistent storage + point-in-
time-safe query for `InstitutionalHoldingRecord`s (Session 36
continued). Mirrors `DuckDBShortInterestRepository`'s exact shape and
point-in-time discipline (`available_time <= as_of_time` on every read,
idempotent insert via `ON CONFLICT ... DO NOTHING` on the natural key),
applied to aggregate Form 13F institutional holdings instead of short
interest reports -- see that module's own docstring for the reasoning
this one deliberately repeats rather than abstracts, matching this
project's established per-repository-type convention."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.institutional_holding_models import InstitutionalHoldingRecord

from storage.engine import StorageEngine
from storage.serialization import (
    institutional_holding_record_to_row,
    row_to_institutional_holding_record,
    to_utc_naive,
)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_COLUMNS = (
    "provenance_source_record_id", "security_id", "quarter_end", "institutional_shares",
    "num_institutions", "available_time", "ingestion_time",
    "provenance_source", "provenance_source_dataset", "provenance_retrieved_at",
    "provenance_data_version", "provenance_schema_version",
)


class DuckDBInstitutionalHoldingRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def add_institutional_holding(self, record: InstitutionalHoldingRecord) -> None:
        row = institutional_holding_record_to_row(record)
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        self._engine.connection.execute(
            f"INSERT INTO institutional_holding_records ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in _COLUMNS],
        )

    def add_institutional_holdings(self, records: Sequence[InstitutionalHoldingRecord]) -> int:
        """Convenience batch wrapper over `add_institutional_holding` --
        returns how many records were passed, not how many were
        actually new (same caveat as
        `DuckDBShortInterestRepository.add_short_interest_records`)."""
        for record in records:
            self.add_institutional_holding(record)
        return len(records)

    def get_latest_institutional_holding(self, security_id: str, as_of_time: datetime) -> Optional[InstitutionalHoldingRecord]:
        """The most recent report for `security_id` whose `available_time
        <= as_of_time` (look-ahead guard), ranked by `quarter_end` --
        `None` if no such report exists yet, never a fabricated one."""
        _require_aware("as_of_time", as_of_time)
        sql = (
            "SELECT * FROM institutional_holding_records WHERE security_id = ? AND available_time <= ? "
            "ORDER BY quarter_end DESC LIMIT 1"
        )
        cur = self._engine.connection.execute(sql, [security_id, to_utc_naive(as_of_time)])
        rows = _rows(cur)
        return row_to_institutional_holding_record(rows[0]) if rows else None

    def get_institutional_holding_history(
        self, security_id: str, as_of_time: datetime, *, start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[InstitutionalHoldingRecord]:
        """Every report for `security_id` whose `available_time <=
        as_of_time`, optionally restricted to `quarter_end` within
        `[start, end]`, sorted by `quarter_end`."""
        _require_aware("as_of_time", as_of_time)
        if start is not None:
            _require_aware("start", start)
        if end is not None:
            _require_aware("end", end)

        conditions = ["security_id = ?", "available_time <= ?"]
        params: list = [security_id, to_utc_naive(as_of_time)]
        if start is not None:
            conditions.append("quarter_end >= ?")
            params.append(to_utc_naive(start))
        if end is not None:
            conditions.append("quarter_end <= ?")
            params.append(to_utc_naive(end))

        sql = f"SELECT * FROM institutional_holding_records WHERE {' AND '.join(conditions)} ORDER BY quarter_end"
        cur = self._engine.connection.execute(sql, params)
        return [row_to_institutional_holding_record(r) for r in _rows(cur)]
