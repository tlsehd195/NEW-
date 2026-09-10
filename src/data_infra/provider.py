"""DataProvider interface, a deterministic MockDataProvider, and an
IngestionRunner implementing retry/backoff, idempotency, partial-failure
handling, and checkpoint recovery.

See docs/specifications/PHASE-1-data-infrastructure.md sections 2.1
(Data Ingestion), 14 (test strategy items 8-11), 14.1 (mock data), and
ADR-0005 (no real provider is integrated in Phase 1 — this module is
exercised only against MockDataProvider).
"""

from __future__ import annotations

import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol, Sequence

from data_infra.enums import IngestionStatus
from data_infra.models import PriceBar, Provenance
from data_infra.repository import AppendableDataRepository
from data_infra.versioning import compute_data_version

# Session 36 continued (external review remediation): the real, provider-
# quoted event date/time a daily EOD bar carries (Tiingo/Stooq/a local
# CSV import all report midnight UTC of the trading day, e.g.
# `2024-06-10T00:00:00Z`) is NOT when that bar's closing price actually
# became knowable -- a US equity market does not close until roughly
# 20:00-21:00 UTC (varying with DST). Using the bare event date as
# `available_time` let an intraday as-of query made on the SAME calendar
# day see that day's own not-yet-final close hours before the market
# actually closed -- a real, if narrow, look-ahead gap (ADR-0004's own
# "never event_time" principle). This does NOT use each record's own
# real `ingestion_time`/`retrieved_at` instead (the fix `normalize_
# corporate_actions`'s dividend branch uses, Session 36 continued) --
# `fetch()` stamps that as ONE value across an entire batched date
# range, so backdating every bar in a broad historical backfill to it
# would make months of already-public, ordinarily-knowable history
# falsely invisible until the batch's own end date, a worse regression
# than the gap being fixed. `END_OF_SESSION_OFFSET` is instead the same
# fixed, conservative, documented convention `backtest.clock.
# build_daily_checkpoints`'s own default `checkpoint_time=time(20, 0)`
# already assumes ("mirrors the convention Phase 1's mock data used for
# available_time") -- applied per-record here so every real provider
# matches what this project's own mock data and checkpoint clock already
# assume, not a new, independently-guessed value.
#
# KNOWN, ACCEPTED LIMITATION (Session 37, external review, ADR-0112):
# 20:00 UTC matches US equity market close exactly only during Eastern
# DAYLIGHT time (EDT, UTC-4, roughly mid-March to early November); during
# Eastern STANDARD time (EST, UTC-5, roughly November to March) the real
# close is 21:00 UTC, one hour later. This constant does not vary by
# calendar date, so for ~4 months a year a bar's `available_time` is
# stamped up to 1 hour EARLIER than the market actually closed -- a
# narrower reopening of the same class of look-ahead gap this constant
# exists to fix, not a new one. Left as a deliberate, documented project
# convention rather than fixed now: `backtest.clock.build_daily_
# checkpoints`'s own `checkpoint_time=time(20, 0)` default has the
# identical DST blind spot and is the precedent this constant was
# explicitly chosen to match (see above) -- fixing one without the other
# would make an as-of query and the checkpoint clock it drives disagree
# about when a winter session actually closed, a worse inconsistency
# than the shared 1-hour winter gap both already accept today. A real
# fix (varying the offset by whether `event_date` falls in EDT or EST)
# would need to change both together and is left for a future session
# that revisits this pair intentionally, not as a side effect of a
# review remediation pass.
END_OF_SESSION_OFFSET = timedelta(hours=20)


def bar_available_time(event_date: datetime) -> datetime:
    """`event_date` (midnight UTC of the trading day, as every real
    provider in this package reports it) plus `END_OF_SESSION_OFFSET` --
    see that constant's own docstring for why this, not the batch-level
    `ingestion_time`, is this project's chosen `available_time` for a
    daily EOD price bar."""
    return event_date + END_OF_SESSION_OFFSET


class ProviderError(Exception):
    """Base class for DataProvider failures."""


class TransientProviderError(ProviderError):
    """A retryable failure (e.g. rate limit, timeout, transient network
    error)."""


class PermanentProviderError(ProviderError):
    """A non-retryable failure (e.g. unknown symbol, auth failure)."""


class DataProvider(Protocol):
    """PROJECT_MASTER_PLAN.md section 21: fetch / validate / normalize /
    metadata, mirrored here for data providers (as distinct from the AI
    provider interface in section 11 of the master plan, which this
    intentionally parallels in shape but not in purpose)."""

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]: ...

    def validate(self, raw_records: Sequence[dict]) -> list[str]: ...

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]: ...

    def metadata(self) -> dict: ...


_REQUIRED_RAW_FIELDS = (
    "security_id",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "available_time",
    "source",
)


class MockDataProvider:
    """Deterministic, in-process provider for tests and design validation.

    Never calls a real external API (Phase 1 spec section 14.1 / ADR-0005).
    `dataset` maps security_id -> list of raw record dicts (see
    _REQUIRED_RAW_FIELDS). `transient_failures` maps security_id -> number
    of times fetch() should raise TransientProviderError before
    succeeding (for retry testing). `permanent_failures` is a set of
    security_ids that always fail with PermanentProviderError (for
    partial-failure testing).
    """

    def __init__(
        self,
        dataset: dict[str, list[dict]],
        *,
        transient_failures: Optional[dict[str, int]] = None,
        permanent_failures: Optional[set[str]] = None,
    ) -> None:
        self._dataset = dataset
        self._transient_failures = dict(transient_failures or {})
        self._permanent_failures = set(permanent_failures or set())
        self.call_count: dict[str, int] = {}

    def fetch(self, security_id: str, start: datetime, end: datetime) -> list[dict]:
        self.call_count[security_id] = self.call_count.get(security_id, 0) + 1

        if security_id in self._permanent_failures:
            raise PermanentProviderError(f"unknown symbol: {security_id}")

        remaining = self._transient_failures.get(security_id, 0)
        if remaining > 0:
            self._transient_failures[security_id] = remaining - 1
            raise TransientProviderError(
                f"transient failure for {security_id} ({remaining} more scheduled)"
            )

        records = self._dataset.get(security_id, [])
        return [r for r in records if start <= r["timestamp"] <= end]

    def validate(self, raw_records: Sequence[dict]) -> list[str]:
        issues: list[str] = []
        for i, record in enumerate(raw_records):
            missing = [f for f in _REQUIRED_RAW_FIELDS if f not in record]
            if missing:
                issues.append(f"record[{i}] missing fields: {missing}")
        return issues

    def normalize(self, security_id: str, raw_records: Sequence[dict]) -> list[PriceBar]:
        bars: list[PriceBar] = []
        for record in raw_records:
            provenance = Provenance(
                source=record["source"],
                source_dataset=f"mock_ohlcv_{record['source']}",
                source_record_id=f"{record['security_id']}:{record['timestamp'].isoformat()}",
                retrieved_at=record.get("retrieved_at", record["available_time"]),
                data_version=compute_data_version(
                    {k: v for k, v in record.items() if k != "retrieved_at"}
                ),
            )
            bars.append(
                PriceBar(
                    security_id=record["security_id"],
                    timestamp=record["timestamp"],
                    open=record["open"],
                    high=record["high"],
                    low=record["low"],
                    close=record["close"],
                    volume=record["volume"],
                    available_time=record["available_time"],
                    ingestion_time=record.get("ingestion_time", record["available_time"]),
                    provenance=provenance,
                    adjusted_close=record.get("adjusted_close"),
                )
            )
        return bars

    def metadata(self) -> dict:
        return {
            "provider_id": "mock_provider_v1",
            "provider_name": "Phase 1 Mock Data Provider",
            "rate_limit_per_minute": 60,
            "is_real_external_provider": False,
        }


@dataclass
class IngestionCheckpoint:
    """Tracks which security_ids have already completed successfully, so a
    resumed run does not re-fetch them (Phase 1 spec section 27)."""

    completed_security_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class IngestionRecordResult:
    security_id: str
    status: IngestionStatus
    bars_ingested: int
    error: Optional[str] = None


@dataclass(frozen=True)
class IngestionRunResult:
    run_id: str
    status: IngestionStatus
    results: tuple[IngestionRecordResult, ...]
    checkpoint: IngestionCheckpoint

    @property
    def failed(self) -> tuple[IngestionRecordResult, ...]:
        return tuple(r for r in self.results if r.status == IngestionStatus.FAILED)


def default_backoff_seconds(attempt: int) -> float:
    return float(min(2**attempt, 30))


class IngestionRunner:
    """Drives DataProvider.fetch/normalize into a DataRepository with
    retry+backoff, idempotency, partial-failure reporting, and checkpoint
    support (Phase 1 spec section 21-27)."""

    def __init__(
        self,
        provider: DataProvider,
        repository: AppendableDataRepository,
        *,
        max_retries: int = 3,
        backoff_fn: Callable[[int], float] = default_backoff_seconds,
        sleep_fn: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._max_retries = max_retries
        self._backoff_fn = backoff_fn
        self._sleep_fn = sleep_fn
        self._next_run_id = 1
        # Idempotency: seed from whatever the repository already has, so
        # re-running ingestion (even via a fresh IngestionRunner instance
        # against the same repository) never duplicates a record (Phase 1
        # spec section 25).
        self._seen_keys: set[tuple] = {
            (bar.security_id, bar.timestamp, bar.provenance.source, bar.provenance.data_version)
            for bar in repository.all_bars()
        }

    def run(
        self,
        security_ids: Sequence[str],
        start: datetime,
        end: datetime,
        *,
        checkpoint: Optional[IngestionCheckpoint] = None,
    ) -> IngestionRunResult:
        checkpoint = checkpoint or IngestionCheckpoint()
        results: list[IngestionRecordResult] = []

        for security_id in security_ids:
            if security_id in checkpoint.completed_security_ids:
                continue  # checkpoint recovery: do not re-fetch completed symbols
            result = self._ingest_one(security_id, start, end)
            results.append(result)
            if result.status == IngestionStatus.SUCCESS:
                checkpoint.completed_security_ids.add(security_id)

        status = self._resolve_overall_status(results)
        run_id = f"ING-{self._next_run_id:06d}"
        self._next_run_id += 1
        return IngestionRunResult(
            run_id=run_id, status=status, results=tuple(results), checkpoint=checkpoint
        )

    def _ingest_one(self, security_id: str, start: datetime, end: datetime) -> IngestionRecordResult:
        raw_records: Optional[list[dict]] = None
        last_error: Optional[str] = None

        for attempt in range(1, self._max_retries + 2):  # first try + up to max_retries retries
            try:
                raw_records = self._provider.fetch(security_id, start, end)
                break
            except TransientProviderError as exc:
                last_error = str(exc)
                if attempt <= self._max_retries:
                    self._sleep_fn(self._backoff_fn(attempt))
                    continue
                return IngestionRecordResult(security_id, IngestionStatus.FAILED, 0, last_error)
            except PermanentProviderError as exc:
                return IngestionRecordResult(security_id, IngestionStatus.FAILED, 0, str(exc))

        if raw_records is None:
            return IngestionRecordResult(security_id, IngestionStatus.FAILED, 0, last_error)

        bars = self._provider.normalize(security_id, raw_records)

        new_bars: list[PriceBar] = []
        for bar in bars:
            key = (bar.security_id, bar.timestamp, bar.provenance.source, bar.provenance.data_version)
            if key in self._seen_keys:
                continue  # idempotent: already ingested this exact record
            self._seen_keys.add(key)
            new_bars.append(bar)

        self._repository.append_bars(new_bars)
        return IngestionRecordResult(security_id, IngestionStatus.SUCCESS, len(new_bars), None)

    @staticmethod
    def _resolve_overall_status(results: Sequence[IngestionRecordResult]) -> IngestionStatus:
        if not results:
            return IngestionStatus.SUCCESS
        statuses = {r.status for r in results}
        if statuses == {IngestionStatus.SUCCESS}:
            return IngestionStatus.SUCCESS
        if IngestionStatus.SUCCESS in statuses:
            return IngestionStatus.PARTIAL_SUCCESS
        return IngestionStatus.FAILED
