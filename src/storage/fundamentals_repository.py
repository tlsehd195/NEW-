"""DuckDBFundamentalsRepository: persistent storage + point-in-time-safe
query for `FundamentalRecord`s (Phase 33, ADR-0042).

Stored as a DuckDB table (not Parquet) -- fundamentals data is
low-volume and point-lookup/filter-heavy (one company's full history
across a handful of concepts is at most a few hundred rows), the same
criterion ADR-0010 section 1 already applied to Benchmark data (see
`schema.py`'s comment on `fundamental_records`).

**Point-in-time discipline**: every query method takes `as_of_time`
and filters on `available_time <= as_of_time` -- exactly the same
look-ahead guard `DuckDBDataRepository.get_bars`/`get_corporate_actions`
apply, extended to fundamentals' own point-in-time-critical field (see
`data_infra.fundamentals_models`'s module docstring for why
`available_time` here is the actual filing date, never `period_end`).
Idempotent insert, mirroring `add_corporate_action`/`add_benchmark_point`:
`provenance_source_record_id` is the natural key, `ON CONFLICT ...
DO NOTHING` makes re-ingesting an already-stored record a no-op rather
than a duplicate or an error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.fundamentals_models import FundamentalRecord

from storage.engine import StorageEngine
from storage.serialization import fundamental_record_to_row, row_to_fundamental_record, to_utc_naive


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_COLUMNS = (
    "provenance_source_record_id", "security_id", "concept", "period_start", "period_end",
    "fiscal_year", "fiscal_period", "form_type", "value", "unit", "available_time",
    "ingestion_time", "provenance_source", "provenance_source_dataset",
    "provenance_retrieved_at", "provenance_data_version", "provenance_schema_version",
)


class DuckDBFundamentalsRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def add_fundamental(self, record: FundamentalRecord) -> None:
        row = fundamental_record_to_row(record)
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        self._engine.connection.execute(
            f"INSERT INTO fundamental_records ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in _COLUMNS],
        )

    def add_fundamentals(self, records: Sequence[FundamentalRecord]) -> int:
        """Convenience batch wrapper over `add_fundamental` -- returns
        how many records were passed (not how many were actually new;
        `ON CONFLICT DO NOTHING` makes the exact new-vs-duplicate count
        unavailable per-statement without a slower round-trip DuckDB
        does not need for this data volume)."""
        for record in records:
            self.add_fundamental(record)
        return len(records)

    def get_fundamentals(
        self,
        security_id: str,
        concept: str,
        as_of_time: datetime,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[FundamentalRecord]:
        """Every record for `(security_id, concept)` whose `available_time
        <= as_of_time` (look-ahead guard), optionally restricted to
        `period_end` within `[start, end]`, sorted by `period_end`.
        Multiple records can legitimately share a `period_end` (e.g. an
        originally-filed 10-Q value and a later 10-K restating the same
        period) -- this method returns all of them; a caller wanting
        exactly one "the value as currently known" figure should use
        `latest_known_value` instead."""
        _require_aware("as_of_time", as_of_time)
        if start is not None:
            _require_aware("start", start)
        if end is not None:
            _require_aware("end", end)

        conditions = ["security_id = ?", "concept = ?", "available_time <= ?"]
        params: list = [security_id, concept, to_utc_naive(as_of_time)]
        if start is not None:
            conditions.append("period_end >= ?")
            params.append(to_utc_naive(start))
        if end is not None:
            conditions.append("period_end <= ?")
            params.append(to_utc_naive(end))

        sql = f"SELECT * FROM fundamental_records WHERE {' AND '.join(conditions)} ORDER BY period_end"
        cur = self._engine.connection.execute(sql, params)
        return [row_to_fundamental_record(r) for r in _rows(cur)]

    def latest_known_value(
        self, security_id: str, concept: str, as_of_time: datetime
    ) -> Optional[FundamentalRecord]:
        """The single most-recently-*reported* (highest `period_end`)
        record for `(security_id, concept)` that was already knowable
        `as_of_time` (`available_time <= as_of_time`) -- the practical
        query a point-in-time-safe feature computation actually wants
        ("what is the latest value of this concept we could have known
        at this moment"), as opposed to `get_fundamentals`'s full
        history. Ties on `period_end` (a restated figure) break toward
        the most recently *filed* one (`available_time` descending),
        since a later filing for the same period supersedes an earlier
        one's figure for "current best known value" purposes -- unlike
        `get_fundamentals`, which never resolves this and returns both."""
        _require_aware("as_of_time", as_of_time)
        sql = (
            "SELECT * FROM fundamental_records WHERE security_id = ? AND concept = ? "
            "AND available_time <= ? ORDER BY period_end DESC, available_time DESC LIMIT 1"
        )
        cur = self._engine.connection.execute(
            sql, [security_id, concept, to_utc_naive(as_of_time)]
        )
        rows = _rows(cur)
        return row_to_fundamental_record(rows[0]) if rows else None

    def all_fundamentals(self) -> tuple[FundamentalRecord, ...]:
        """Every record currently stored, unfiltered by `as_of_time` --
        for ingestion-side bookkeeping and tests only, mirroring
        `DuckDBDataRepository.all_bars`'s identical "not for
        Backtest/Feature/Decision code" scoping."""
        cur = self._engine.connection.execute("SELECT * FROM fundamental_records")
        return tuple(row_to_fundamental_record(r) for r in _rows(cur))
