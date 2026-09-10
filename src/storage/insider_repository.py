"""DuckDBInsiderRepository: persistent storage + point-in-time-safe
query for `InsiderTransaction`s (Session 36 continued, ADR-0086).
Mirrors `DuckDBFundamentalsRepository`'s exact shape and point-in-time
discipline (`available_time <= as_of_time` on every read, idempotent
insert via `ON CONFLICT ... DO NOTHING` on the natural key), applied to
insider transactions instead of financial-statement facts -- see that
module's own docstring for the reasoning this one deliberately
repeats rather than abstracts, matching this project's established
per-repository-type convention (`storage.data_repository`,
`storage.fundamentals_repository`, `broker.live.*` all keep their own
copy of shared plumbing rather than sharing one across modules)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from data_infra.insider_models import InsiderTransaction

from storage.engine import StorageEngine
from storage.serialization import insider_transaction_to_row, row_to_insider_transaction, to_utc_naive


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


_COLUMNS = (
    "provenance_source_record_id", "security_id", "reporting_owner_cik", "reporting_owner_name",
    "is_officer", "is_director", "is_ten_percent_owner", "officer_title", "transaction_date",
    "transaction_code", "acquired_disposed_code", "shares", "price_per_share", "is_10b5_1_plan",
    "accession_number", "available_time", "ingestion_time", "provenance_source",
    "provenance_source_dataset", "provenance_retrieved_at", "provenance_data_version",
    "provenance_schema_version",
)


class DuckDBInsiderRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def add_insider_transaction(self, record: InsiderTransaction) -> None:
        row = insider_transaction_to_row(record)
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        self._engine.connection.execute(
            f"INSERT INTO insider_transactions ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in _COLUMNS],
        )

    def add_insider_transactions(self, records: Sequence[InsiderTransaction]) -> int:
        """Convenience batch wrapper over `add_insider_transaction` --
        returns how many records were passed, not how many were
        actually new (same caveat as `DuckDBFundamentalsRepository.
        add_fundamentals`)."""
        for record in records:
            self.add_insider_transaction(record)
        return len(records)

    def get_insider_transactions(
        self,
        security_id: str,
        as_of_time: datetime,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[InsiderTransaction]:
        """Every transaction for `security_id` whose `available_time <=
        as_of_time` (look-ahead guard), optionally restricted to
        `transaction_date` within `[start, end]`, sorted by
        `transaction_date`."""
        _require_aware("as_of_time", as_of_time)
        if start is not None:
            _require_aware("start", start)
        if end is not None:
            _require_aware("end", end)

        conditions = ["security_id = ?", "available_time <= ?"]
        params: list = [security_id, to_utc_naive(as_of_time)]
        if start is not None:
            conditions.append("transaction_date >= ?")
            params.append(to_utc_naive(start))
        if end is not None:
            conditions.append("transaction_date <= ?")
            params.append(to_utc_naive(end))

        sql = f"SELECT * FROM insider_transactions WHERE {' AND '.join(conditions)} ORDER BY transaction_date"
        cur = self._engine.connection.execute(sql, params)
        return [row_to_insider_transaction(r) for r in _rows(cur)]
