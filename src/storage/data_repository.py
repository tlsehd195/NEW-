"""DuckDBDataRepository: a persistent implementation of Phase 1's
DataRepository Protocol, backed by DuckDB (relational/metadata tables)
and Parquet (Raw + Clean market data time series).

See docs/specifications/PHASE-4-baseline-models-and-storage.md section 4
and ADR-0010. Must satisfy the exact same Protocol
(data_infra.repository.DataRepository) and the same look-ahead-guard
discipline (ADR-0004) as Phase 1's InMemoryDataRepository -- every
as-of-aware method filters on ``available_time <= as_of_time`` before
returning results, applied identically whether the record came from
Parquet or a DuckDB table.

Also implements the extra, non-Protocol methods
(``append_bars``/``all_bars``) that ``data_infra.provider.IngestionRunner``
depends on, so ingestion code written against Phase 1's in-memory
repository works unmodified against this persistent one (duck typing --
see the ``AppendableDataRepository`` Protocol in data_infra.repository).
"""

from __future__ import annotations

import bisect
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from data_infra.calendar import TradingCalendar
from data_infra.models import (
    BenchmarkPoint,
    CorporateAction,
    PriceBar,
    SecurityMaster,
    UniverseMembership,
)

from storage.engine import StorageEngine
from storage.parquet_layer import existing_files, glob_pattern, write_batch
from storage.serialization import (
    PRICE_BAR_COLUMNS,
    benchmark_point_to_row,
    corporate_action_to_row,
    from_utc_naive,
    json_dumps,
    price_bar_to_row,
    row_to_benchmark_point,
    row_to_corporate_action,
    row_to_price_bar,
    row_to_security_master,
    security_master_to_row,
    to_utc_naive,
    universe_membership_to_row,
)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


RAW_MARKET_DATA_COLUMNS = ("security_id", "source", "ingestion_time", "batch_id", "raw_payload_json")


class DuckDBDataRepository:
    def __init__(
        self,
        engine: StorageEngine,
        *,
        calendars: Optional[dict[str, TradingCalendar]] = None,
    ) -> None:
        self._engine = engine
        self._calendars: dict[str, TradingCalendar] = dict(calendars or {})
        self._price_bars_dir = engine.config.parquet_dir / "price_bars"
        self._raw_market_data_dir = engine.config.parquet_dir / "raw_market_data"
        self._next_raw_batch_id = 1
        # Per-security in-memory cache of this instance's own reads, keyed
        # by security_id, each held sorted by timestamp -- populated
        # lazily by _bars_for_security/_corporate_actions_for_security on
        # first access. get_bars/get_corporate_actions were previously
        # re-querying the full Parquet/DuckDB dataset (including a
        # directory glob) on every single call; a walk-forward run calls
        # them per security per checkpoint, so this cache is the
        # difference between one query per security for a whole run and
        # one query per security per DAY. Caching the raw, UNFILTERED
        # per-security series and re-applying the as_of_time/date-range
        # filter in Python on every call (never caching a filtered view)
        # keeps point-in-time correctness identical to the un-cached
        # version -- see the as_of_time filtering in _bars_for_security's
        # callers below. Invalidated per-security in append_bars/
        # add_corporate_action so a write is never served stale.
        self._bars_cache: dict[str, list[PriceBar]] = {}
        self._corporate_actions_cache: dict[str, list[CorporateAction]] = {}

    # -- DataRepository Protocol --------------------------------------

    def _bars_for_security(self, security_id: str) -> list[PriceBar]:
        """Every bar ever ingested for `security_id`, unfiltered, sorted
        by timestamp, loaded from Parquet once per instance and cached
        (see `self._bars_cache` in `__init__`)."""
        cached = self._bars_cache.get(security_id)
        if cached is not None:
            return cached
        files = existing_files(self._price_bars_dir)
        if not files:
            bars: list[PriceBar] = []
        else:
            sql = (
                f"SELECT * FROM read_parquet('{glob_pattern(self._price_bars_dir)}') "
                "WHERE security_id = ? ORDER BY timestamp"
            )
            cur = self._engine.connection.execute(sql, [security_id])
            bars = [row_to_price_bar(r) for r in _rows(cur)]
        self._bars_cache[security_id] = bars
        return bars

    def get_bars(
        self, security_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[PriceBar]:
        for name, value in (("start", start), ("end", end), ("as_of_time", as_of_time)):
            _require_aware(name, value)
        bars = self._bars_for_security(security_id)
        lo = bisect.bisect_left(bars, start, key=lambda b: b.timestamp)
        hi = bisect.bisect_right(bars, end, key=lambda b: b.timestamp)
        return [b for b in bars[lo:hi] if b.available_time <= as_of_time]

    def get_security(self, security_id: str, as_of_time: datetime) -> Optional[SecurityMaster]:
        _require_aware("as_of_time", as_of_time)
        sql = (
            "SELECT * FROM security_master WHERE security_id = ? AND valid_from <= ? "
            "AND (valid_to IS NULL OR ? < valid_to) ORDER BY valid_from DESC LIMIT 1"
        )
        as_of_naive = to_utc_naive(as_of_time)
        cur = self._engine.connection.execute(sql, [security_id, as_of_naive, as_of_naive])
        rows = _rows(cur)
        return row_to_security_master(rows[0]) if rows else None

    def _corporate_actions_for_security(self, security_id: str) -> list[CorporateAction]:
        """Every corporate action ever ingested for `security_id`,
        unfiltered, sorted the same way `get_corporate_actions`'s
        previous per-call SQL ordered its result (by
        COALESCE(effective_time, event_time), falling back to
        available_time), loaded from DuckDB once per instance and
        cached (see `self._corporate_actions_cache` in `__init__`)."""
        cached = self._corporate_actions_cache.get(security_id)
        if cached is not None:
            return cached
        sql = "SELECT * FROM corporate_actions WHERE security_id = ?"
        cur = self._engine.connection.execute(sql, [security_id])
        actions = [row_to_corporate_action(r) for r in _rows(cur)]
        actions.sort(key=lambda a: a.effective_time or a.event_time or a.available_time)
        self._corporate_actions_cache[security_id] = actions
        return actions

    def get_corporate_actions(
        self, security_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[CorporateAction]:
        for name, value in (("start", start), ("end", end), ("as_of_time", as_of_time)):
            _require_aware(name, value)
        result = []
        for action in self._corporate_actions_for_security(security_id):
            if action.available_time > as_of_time:
                continue
            reference_time = action.effective_time or action.event_time
            if reference_time is not None and not (start <= reference_time <= end):
                continue
            result.append(action)
        return result

    def get_trading_calendar(self, market: str) -> TradingCalendar:
        try:
            return self._calendars[market]
        except KeyError as exc:
            raise KeyError(f"No trading calendar registered for market={market!r}") from exc

    def get_benchmark(
        self, benchmark_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[BenchmarkPoint]:
        for name, value in (("start", start), ("end", end), ("as_of_time", as_of_time)):
            _require_aware(name, value)
        sql = (
            "SELECT * FROM benchmark_points WHERE benchmark_id = ? AND timestamp >= ? "
            "AND timestamp <= ? AND available_time <= ? ORDER BY timestamp"
        )
        cur = self._engine.connection.execute(
            sql,
            [benchmark_id, to_utc_naive(start), to_utc_naive(end), to_utc_naive(as_of_time)],
        )
        return [row_to_benchmark_point(r) for r in _rows(cur)]

    def get_universe(self, market: str, universe: str, as_of_time: datetime) -> list[str]:
        _require_aware("as_of_time", as_of_time)
        as_of_naive = to_utc_naive(as_of_time)
        sql = (
            "SELECT DISTINCT security_id FROM universe_membership WHERE universe = ? "
            "AND valid_from <= ? AND (valid_to IS NULL OR ? < valid_to) ORDER BY security_id"
        )
        cur = self._engine.connection.execute(sql, [universe, as_of_naive, as_of_naive])
        return [r[0] for r in cur.fetchall()]

    # -- Ingestion-side bookkeeping (mirrors InMemoryDataRepository) ----

    def all_bars(self) -> tuple[PriceBar, ...]:
        files = existing_files(self._price_bars_dir)
        if not files:
            return ()
        sql = f"SELECT * FROM read_parquet('{glob_pattern(self._price_bars_dir)}')"
        cur = self._engine.connection.execute(sql)
        return tuple(row_to_price_bar(r) for r in _rows(cur))

    def append_bars(self, new_bars: Sequence[PriceBar]) -> int:
        """Append-only ingestion of new bars into a new immutable Parquet
        file. Idempotent: bars whose (security_id, timestamp,
        provenance.source, provenance.data_version) natural key already
        exists in a previously-written batch are silently skipped (Phase
        4 spec section 8, mirrors data_infra.provider.IngestionRunner's
        in-memory dedup at the repository layer too). Returns the number
        of bars actually written."""
        if not new_bars:
            return 0

        security_ids = sorted({b.security_id for b in new_bars})
        existing_keys: set[tuple] = set()
        files = existing_files(self._price_bars_dir)
        if files:
            placeholders = ", ".join(["?"] * len(security_ids))
            sql = (
                "SELECT DISTINCT security_id, timestamp, provenance_source, provenance_data_version "
                f"FROM read_parquet('{glob_pattern(self._price_bars_dir)}') "
                f"WHERE security_id IN ({placeholders})"
            )
            cur = self._engine.connection.execute(sql, security_ids)
            existing_keys = {tuple(row) for row in cur.fetchall()}

        rows_to_write = []
        for bar in new_bars:
            key = (
                bar.security_id,
                to_utc_naive(bar.timestamp),
                bar.provenance.source,
                bar.provenance.data_version,
            )
            if key in existing_keys:
                continue
            existing_keys.add(key)
            rows_to_write.append(price_bar_to_row(bar))

        if not rows_to_write:
            return 0
        write_batch(self._price_bars_dir, rows_to_write, columns=PRICE_BAR_COLUMNS)
        for sid in security_ids:
            self._bars_cache.pop(sid, None)
        return len(rows_to_write)

    # -- Raw market data (pre-normalization payloads) -------------------

    def append_raw_payloads(
        self, security_id: str, source: str, raw_records: Sequence[dict], *, ingestion_time: datetime
    ) -> Optional[Path]:
        """Persists the exact, pre-normalization payload dicts
        DataProvider.fetch() returned, before Normalization/Data Quality
        ran (Phase 1 spec section 2.1's "Raw Data" layer, section 17
        Raw Immutability). Never rewritten -- a re-ingestion appends a new
        batch file rather than touching a prior one, even for identical
        content (Raw is a record of what was received and when, not a
        deduplicated current-value store; that is the Clean layer's job).
        """
        _require_aware("ingestion_time", ingestion_time)
        if not raw_records:
            return None
        batch_id = f"RAW-{self._next_raw_batch_id:06d}"
        self._next_raw_batch_id += 1
        rows = [
            {
                "security_id": security_id,
                "source": source,
                "ingestion_time": to_utc_naive(ingestion_time),
                "batch_id": batch_id,
                "raw_payload_json": json_dumps(record),
            }
            for record in raw_records
        ]
        path = write_batch(self._raw_market_data_dir, rows, columns=RAW_MARKET_DATA_COLUMNS)
        self._engine.connection.execute(
            "INSERT INTO raw_ingestion_batches "
            "(batch_id, security_id, source, record_count, ingested_at, parquet_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [batch_id, security_id, source, len(raw_records), to_utc_naive(ingestion_time), str(path)],
        )
        return path

    def get_raw_payloads(self, security_id: str) -> list[dict]:
        """Admin/audit read path -- not part of the point-in-time
        DataRepository Protocol consumers use, mirroring
        InMemoryDataRepository.all_bars()'s scoping."""
        files = existing_files(self._raw_market_data_dir)
        if not files:
            return []
        sql = (
            f"SELECT * FROM read_parquet('{glob_pattern(self._raw_market_data_dir)}') "
            "WHERE security_id = ? ORDER BY ingestion_time"
        )
        cur = self._engine.connection.execute(sql, [security_id])
        return [
            {
                "security_id": r["security_id"],
                "source": r["source"],
                "ingestion_time": from_utc_naive(r["ingestion_time"]),
                "batch_id": r["batch_id"],
                "payload": json.loads(r["raw_payload_json"]),
            }
            for r in _rows(cur)
        ]

    # -- Write paths for relational/metadata tables ---------------------

    def add_security(self, security: SecurityMaster) -> None:
        row = security_master_to_row(security)
        self._engine.connection.execute(
            "INSERT INTO security_master (security_id, ticker, exchange, currency, company_id, "
            "instrument_type, valid_from, valid_to, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (security_id, valid_from) DO NOTHING",
            [row[c] for c in (
                "security_id", "ticker", "exchange", "currency", "company_id",
                "instrument_type", "valid_from", "valid_to", "status",
            )],
        )

    def add_corporate_action(self, action: CorporateAction) -> None:
        row = corporate_action_to_row(action)
        cols = (
            "provenance_source_record_id", "security_id", "action_type", "event_time",
            "announcement_time", "effective_time", "available_time", "ingestion_time",
            "details_json", "provenance_source", "provenance_source_dataset",
            "provenance_retrieved_at", "provenance_data_version", "provenance_schema_version",
        )
        placeholders = ", ".join(["?"] * len(cols))
        self._engine.connection.execute(
            f"INSERT INTO corporate_actions ({', '.join(cols)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in cols],
        )
        self._corporate_actions_cache.pop(action.security_id, None)

    def add_benchmark_point(self, point: BenchmarkPoint) -> None:
        row = benchmark_point_to_row(point)
        cols = (
            "provenance_source_record_id", "benchmark_id", "timestamp", "level", "return_type",
            "currency", "available_time", "ingestion_time", "provenance_source",
            "provenance_source_dataset", "provenance_retrieved_at", "provenance_data_version",
            "provenance_schema_version",
        )
        placeholders = ", ".join(["?"] * len(cols))
        self._engine.connection.execute(
            f"INSERT INTO benchmark_points ({', '.join(cols)}) VALUES ({placeholders}) "
            "ON CONFLICT (provenance_source_record_id) DO NOTHING",
            [row[c] for c in cols],
        )

    def add_universe_membership(self, membership: UniverseMembership) -> None:
        row = universe_membership_to_row(membership)
        self._engine.connection.execute(
            "INSERT INTO universe_membership (security_id, universe, valid_from, valid_to) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (security_id, universe, valid_from) DO NOTHING",
            [row["security_id"], row["universe"], row["valid_from"], row["valid_to"]],
        )
