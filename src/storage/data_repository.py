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
from data_infra.enums import DataQualitySeverity
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


def _dedupe_latest_per_timestamp(bars: list[PriceBar]) -> list[PriceBar]:
    """Collapses `bars` to at most one entry per `timestamp`, keeping the
    one with the latest `ingestion_time` (a tie -- same `ingestion_time`
    exactly -- breaks on `provenance.data_version` for a deterministic,
    if arbitrary, result). See `get_bars`'s own docstring for why more
    than one physical row for the same (security_id, timestamp) is an
    expected, legitimate outcome of ADR-0085's overlap re-fetch, not a
    sign of a broken ingestion run."""
    if len(bars) < 2:
        return list(bars)
    latest_by_timestamp: dict[datetime, PriceBar] = {}
    for bar in bars:
        current = latest_by_timestamp.get(bar.timestamp)
        if current is None:
            latest_by_timestamp[bar.timestamp] = bar
            continue
        candidate_key = (bar.ingestion_time, bar.provenance.data_version)
        current_key = (current.ingestion_time, current.provenance.data_version)
        if candidate_key > current_key:
            latest_by_timestamp[bar.timestamp] = bar
    return sorted(latest_by_timestamp.values(), key=lambda b: b.timestamp)


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
        self._next_raw_batch_id = self._compute_next_raw_batch_id()
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
        # Which (per-security) timestamps carry a CRITICAL-severity
        # data_quality_flags row -- see record_quality_issues/get_bars
        # below. Cached the same way _bars_cache is (per-security, keyed
        # off this instance's own reads), invalidated in
        # record_quality_issues for exactly the securities it just wrote.
        self._quality_rejections_cache: dict[str, set[datetime]] = {}
        # Session 36 continued addition: every `read_parquet(...)` call
        # over `self._price_bars_dir` below passes `union_by_name=true`.
        # `PriceBar`'s own columns have grown before (e.g. `vwap`/
        # `trade_count`) and will again -- each `write_batch` call always
        # writes the CURRENT full `PRICE_BAR_COLUMNS` tuple, but a file
        # written before a given column existed has a genuinely different
        # Arrow schema (missing that column entirely, not just NULL in
        # it). DuckDB's plain multi-file `read_parquet(glob)` is not
        # guaranteed to reconcile differing schemas across files in the
        # glob; `union_by_name=true` makes that reconciliation explicit
        # (missing columns read back as NULL), so an old real ingestion
        # someone already has on disk is never broken by a later,
        # additive schema change like this session's `adjusted_high`/
        # `adjusted_low` addition.

    def _compute_next_raw_batch_id(self) -> int:
        """Session 37 (ADR-0115, external review, previously-remaining
        MEDIUM): seeds the batch_id counter past every batch_id already
        persisted, mirroring the `advance_past`/`starting_id` restart-
        safe pattern already established elsewhere in this codebase
        (ADR-0073). Without this, a fresh process's counter always
        restarted at 1 -- `raw_ingestion_batches.batch_id` is a PRIMARY
        KEY with no `ON CONFLICT` handling, so the very next
        `append_raw_payloads()` call after a restart, whenever its
        freshly generated "RAW-000001" collided with an already-
        persisted row, crashed outright (a PK violation) rather than
        silently misbehaving -- restart-resume of raw ingestion was
        therefore structurally broken, not just degraded."""
        row = self._engine.connection.execute(
            "SELECT batch_id FROM raw_ingestion_batches ORDER BY batch_id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 1
        suffix = row[0].rsplit("-", 1)[-1]
        return int(suffix) + 1 if suffix.isdigit() else 1

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
            # Session 37 (ADR-0115, external review, previously-remaining
            # MEDIUM): the glob path is bound as a real query parameter,
            # not f-string-interpolated into the SQL text -- DuckDB
            # supports binding `read_parquet(?)`'s own path/glob argument
            # exactly like any other parameter (verified directly), so
            # there is no need to trust that a filesystem path never
            # contains a character (a single quote, primarily) that would
            # otherwise corrupt the surrounding SQL string literal.
            sql = (
                "SELECT * FROM read_parquet(?, union_by_name=true) "
                "WHERE security_id = ? ORDER BY timestamp"
            )
            cur = self._engine.connection.execute(sql, [glob_pattern(self._price_bars_dir), security_id])
            bars = [row_to_price_bar(r) for r in _rows(cur)]
        self._bars_cache[security_id] = bars
        return bars

    def _critical_rejected_timestamps(self, security_id: str) -> set[datetime]:
        """Timestamps for which `security_id` has at least one
        CRITICAL-severity `data_quality_flags` row -- Phase 1 spec
        section 3.1's QUALITY_REJECTED state (a record that fails a
        CRITICAL check is not promoted from Raw to Clean). Cached per
        security like `_bars_for_security`; see `record_quality_issues`
        for how this table is populated and invalidated."""
        cached = self._quality_rejections_cache.get(security_id)
        if cached is not None:
            return cached
        cur = self._engine.connection.execute(
            "SELECT DISTINCT timestamp FROM data_quality_flags WHERE security_id = ? AND severity = ?",
            [security_id, DataQualitySeverity.CRITICAL.value],
        )
        rejected = {from_utc_naive(row[0]) for row in cur.fetchall()}
        self._quality_rejections_cache[security_id] = rejected
        return rejected

    def get_bars(
        self,
        security_id: str,
        start: datetime,
        end: datetime,
        as_of_time: datetime,
        *,
        include_quality_rejected: bool = False,
    ) -> list[PriceBar]:
        """`include_quality_rejected=True` bypasses the QUALITY_REJECTED
        filter below, and the same-timestamp dedup after it, for
        audit/debugging (`scripts/ingest_real_market_data.py`'s own data
        quality run uses this to see every physical row, including
        ones a later provider revision superseded, so
        `DataQualityFramework._check_duplicates` can still surface
        them) -- the underlying Parquet bar is never deleted (Raw
        Immutability, Phase 1 spec section 17), only excluded from the
        default query view every real consumer (Paper Trading,
        backtest, strategy_research, Learning Cycle) uses.

        For that default view, when more than one physical bar exists
        for the same (security_id, timestamp) -- ADR-0085's deliberate
        7-day ingestion overlap re-fetches recent days specifically to
        catch a provider revising an already-ingested value, which
        lands as a second physical row rather than replacing the first
        (append_bars's own dedup key includes provenance.data_version,
        a content hash, so a genuinely revised value is intentionally
        NOT treated as a duplicate at write time) -- only the most
        recently ingested version is returned, so a caller never sees
        the same calendar day twice (external review, 2026-09-18: this
        was previously reaching every real consumer as two bars for one
        trading day)."""
        for name, value in (("start", start), ("end", end), ("as_of_time", as_of_time)):
            _require_aware(name, value)
        bars = self._bars_for_security(security_id)
        lo = bisect.bisect_left(bars, start, key=lambda b: b.timestamp)
        hi = bisect.bisect_right(bars, end, key=lambda b: b.timestamp)
        result = [b for b in bars[lo:hi] if b.available_time <= as_of_time]
        if not include_quality_rejected:
            rejected = self._critical_rejected_timestamps(security_id)
            if rejected:
                result = [b for b in result if b.timestamp not in rejected]
            result = _dedupe_latest_per_timestamp(result)
        return result

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
        # See `_bars_for_security`'s own comment on binding the glob path
        # as a real parameter rather than f-string-interpolating it.
        sql = "SELECT * FROM read_parquet(?, union_by_name=true)"
        cur = self._engine.connection.execute(sql, [glob_pattern(self._price_bars_dir)])
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
            # See `_bars_for_security`'s own comment on binding the glob
            # path as a real parameter rather than f-string-interpolating
            # it.
            sql = (
                "SELECT DISTINCT security_id, timestamp, provenance_source, provenance_data_version "
                "FROM read_parquet(?, union_by_name=true) "
                f"WHERE security_id IN ({placeholders})"
            )
            cur = self._engine.connection.execute(sql, [glob_pattern(self._price_bars_dir), *security_ids])
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
        # See `_bars_for_security`'s own comment on binding the glob path
        # as a real parameter rather than f-string-interpolating it.
        sql = "SELECT * FROM read_parquet(?) WHERE security_id = ? ORDER BY ingestion_time"
        cur = self._engine.connection.execute(sql, [glob_pattern(self._raw_market_data_dir), security_id])
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
        cols = (
            "security_id", "ticker", "exchange", "currency", "company_id",
            "instrument_type", "valid_from", "valid_to", "status",
            "provenance_source", "provenance_source_dataset", "provenance_source_record_id",
            "provenance_retrieved_at", "provenance_data_version", "provenance_schema_version",
        )
        self._engine.connection.execute(
            f"INSERT INTO security_master ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            "ON CONFLICT (security_id, valid_from) DO NOTHING",
            [row[c] for c in cols],
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

    def record_quality_issues(self, quality_run) -> int:
        """Persists every issue from a `DataQualityFramework.run()` result
        that is tied to a specific bar (`security_id` + `timestamp` both
        set) into `data_quality_flags`, implementing Phase 1 spec section
        3.1's QUALITY_REJECTED/QUALITY_FLAGGED states for the first time:
        CRITICAL-severity rows make `get_bars()` exclude that bar by
        default going forward (this call and every later run against the
        same catalog, since this table round-trips with it); WARNING/ERROR
        rows are recorded too, so a consumer can inspect/filter on them,
        but are never excluded (QUALITY_FLAGGED stays promoted to Clean).
        Dataset/security-level issues with no timestamp (e.g.
        insufficient_coverage) are not stored here -- there is no single
        bar to attach them to -- they remain visible in the caller's own
        manifest/report instead. Returns how many rows were written (an
        idempotent re-run of the same quality_run over an already-recorded
        (security_id, timestamp, check_name) writes nothing new)."""
        rows = [
            (
                issue.security_id,
                to_utc_naive(issue.timestamp),
                issue.check,
                issue.severity.value,
                issue.message,
                quality_run.validation_id,
                quality_run.dataset,
                to_utc_naive(quality_run.timestamp),
            )
            for issue in quality_run.issues
            if issue.security_id is not None and issue.timestamp is not None
        ]
        for row in rows:
            self._engine.connection.execute(
                "INSERT INTO data_quality_flags (security_id, timestamp, check_name, severity, "
                "message, validation_id, dataset, flagged_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (security_id, timestamp, check_name) DO NOTHING",
                list(row),
            )
        # DuckDB's INSERT ... ON CONFLICT DO NOTHING does not portably
        # report how many rows it actually wrote per statement, so this
        # counts attempted (deduplicated-by-key) rows instead -- good
        # enough for a caller that only wants "did this add anything," not
        # an exact idempotency-aware count.
        written = len({(r[0], r[1], r[2]) for r in rows})
        for security_id in {r[0] for r in rows if r[3] == DataQualitySeverity.CRITICAL.value}:
            self._quality_rejections_cache.pop(security_id, None)
        return written

    def add_universe_membership(self, membership: UniverseMembership) -> None:
        row = universe_membership_to_row(membership)
        cols = (
            "security_id", "universe", "valid_from", "valid_to",
            "provenance_source", "provenance_source_dataset", "provenance_source_record_id",
            "provenance_retrieved_at", "provenance_data_version", "provenance_schema_version",
        )
        self._engine.connection.execute(
            f"INSERT INTO universe_membership ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            "ON CONFLICT (security_id, universe, valid_from) DO NOTHING",
            [row[c] for c in cols],
        )
