"""DuckDBInstitutionalFilerHoldingRepository: persistent storage + point-
in-time-safe query for `InstitutionalFilerHoldingRecord`s -- the
per-filer counterpart to `institutional_holding_repository.
DuckDBInstitutionalHoldingRepository` (see that module's own docstring
for the point-in-time discipline this one deliberately repeats rather
than abstracts, matching this project's established per-repository-type
convention). Backs `data_infra.tracked_institutional_filers`/
`strategy_research.factor_scores.guru_consensus_score`."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.institutional_holding_models import InstitutionalFilerHoldingRecord

from storage.engine import StorageEngine
from storage.serialization import (
    institutional_filer_holding_record_to_row,
    row_to_institutional_filer_holding_record,
    to_utc_naive,
)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_COLUMNS = (
    "provenance_source_record_id", "security_id", "filer_cik", "quarter_end", "shares_held",
    "available_time", "ingestion_time",
    "provenance_source", "provenance_source_dataset", "provenance_retrieved_at",
    "provenance_data_version", "provenance_schema_version",
)


class DuckDBInstitutionalFilerHoldingRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def add_institutional_filer_holding(self, record: InstitutionalFilerHoldingRecord) -> None:
        row = institutional_filer_holding_record_to_row(record)
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        self._engine.connection.execute(
            f"INSERT INTO institutional_filer_holding_records ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in _COLUMNS],
        )

    def add_institutional_filer_holdings(self, records: Sequence[InstitutionalFilerHoldingRecord]) -> int:
        """Convenience batch wrapper over `add_institutional_filer_holding`
        -- returns how many records were passed, not how many were
        actually new (same caveat as `DuckDBInstitutionalHoldingRepository.
        add_institutional_holdings`)."""
        for record in records:
            self.add_institutional_filer_holding(record)
        return len(records)

    def get_latest_institutional_filer_holding(
        self, security_id: str, filer_cik: str, as_of_time: datetime,
    ) -> Optional[InstitutionalFilerHoldingRecord]:
        """The most recent report for this `(security_id, filer_cik)`
        pair whose `available_time <= as_of_time` (look-ahead guard),
        ranked by `quarter_end` -- `None` if no such report exists yet,
        never a fabricated one."""
        _require_aware("as_of_time", as_of_time)
        sql = (
            "SELECT * FROM institutional_filer_holding_records "
            "WHERE security_id = ? AND filer_cik = ? AND available_time <= ? "
            "ORDER BY quarter_end DESC LIMIT 1"
        )
        cur = self._engine.connection.execute(sql, [security_id, filer_cik, to_utc_naive(as_of_time)])
        rows = _rows(cur)
        return row_to_institutional_filer_holding_record(rows[0]) if rows else None

    def get_latest_holdings_for_security(
        self, security_id: str, filer_ciks: Sequence[str], as_of_time: datetime,
    ) -> dict[str, InstitutionalFilerHoldingRecord]:
        """The most recent known report as of `as_of_time` for
        `security_id`, for each of `filer_ciks` that has one --
        `guru_consensus_score`'s own primary read path (one query per
        security, not one query per (security, filer) pair). Filers
        with no known report yet are simply absent from the returned
        dict, never a fabricated zero-position entry."""
        _require_aware("as_of_time", as_of_time)
        if not filer_ciks:
            return {}
        placeholders = ", ".join(["?"] * len(filer_ciks))
        sql = (
            "SELECT * FROM institutional_filer_holding_records "
            f"WHERE security_id = ? AND filer_cik IN ({placeholders}) AND available_time <= ? "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY filer_cik ORDER BY quarter_end DESC) = 1"
        )
        params = [security_id, *filer_ciks, to_utc_naive(as_of_time)]
        cur = self._engine.connection.execute(sql, params)
        records = [row_to_institutional_filer_holding_record(r) for r in _rows(cur)]
        return {record.filer_cik: record for record in records}
