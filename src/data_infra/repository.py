"""Data Access Interface (DataRepository) and its Phase 1 in-memory
reference implementation.

See docs/specifications/PHASE-1-data-infrastructure.md section 12 (Data
Access Interface) and section 15 (Look-ahead Guard), and ADR-0004.

Every point-in-time-sensitive method requires `as_of_time` — there is no
overload that omits it, so a caller cannot accidentally get an
un-filtered, leakage-prone result (ADR-0004, decision point 3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, Sequence

from data_infra.calendar import TradingCalendar
from data_infra.models import (
    BenchmarkPoint,
    CorporateAction,
    PriceBar,
    SecurityMaster,
    UniverseMembership,
)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


class DataRepository(Protocol):
    """The only interface Backtest/Feature/ML/Trade Journal/Decision
    Replay code is allowed to read data through (PROJECT_MASTER_PLAN.md
    section 19)."""

    def get_bars(
        self, security_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[PriceBar]: ...

    def get_security(self, security_id: str, as_of_time: datetime) -> Optional[SecurityMaster]: ...

    def get_corporate_actions(
        self, security_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[CorporateAction]: ...

    def get_trading_calendar(self, market: str) -> TradingCalendar: ...

    def get_benchmark(
        self, benchmark_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[BenchmarkPoint]: ...

    def get_universe(self, market: str, universe: str, as_of_time: datetime) -> list[str]: ...


class AppendableDataRepository(DataRepository, Protocol):
    """DataRepository plus the ingestion-side bookkeeping methods
    `data_infra.provider.IngestionRunner` needs (`all_bars`/`append_bars`).

    Added in Phase 4 (docs/specifications/PHASE-4-baseline-models-and-storage.md
    section 4) purely so IngestionRunner can be typed against a Protocol
    instead of the concrete `InMemoryDataRepository` class, letting a
    persistent, DuckDB/Parquet-backed repository (storage.data_repository.
    DuckDBDataRepository) be used as an ingestion target without any
    IngestionRunner code change -- this is a widening, backward-compatible
    type-hint change only; `InMemoryDataRepository` already satisfies this
    Protocol structurally, and no runtime behavior changes.
    """

    def all_bars(self) -> Sequence[PriceBar]: ...

    def append_bars(self, new_bars: Sequence[PriceBar]) -> object: ...


class InMemoryDataRepository:
    """Phase 1 reference implementation of DataRepository.

    Backed by plain Python lists — no persistence, no query optimization.
    This exists to make the DataRepository contract testable now (Phase 1
    spec section 2.2); a DuckDB/Parquet-backed implementation (ADR-0002)
    must satisfy the exact same Protocol and pass the exact same test
    suite unmodified.
    """

    def __init__(
        self,
        *,
        bars: Optional[Sequence[PriceBar]] = None,
        securities: Optional[Sequence[SecurityMaster]] = None,
        corporate_actions: Optional[Sequence[CorporateAction]] = None,
        benchmarks: Optional[Sequence[BenchmarkPoint]] = None,
        universe_memberships: Optional[Sequence[UniverseMembership]] = None,
        calendars: Optional[dict[str, TradingCalendar]] = None,
    ) -> None:
        # Stored as tuples: this repository is a read-oriented reference
        # implementation, not intended for in-place mutation of existing
        # entries (Raw immutability principle, Phase 1 spec section 17).
        self._bars: tuple[PriceBar, ...] = tuple(bars or ())
        self._securities: tuple[SecurityMaster, ...] = tuple(securities or ())
        self._corporate_actions: tuple[CorporateAction, ...] = tuple(corporate_actions or ())
        self._benchmarks: tuple[BenchmarkPoint, ...] = tuple(benchmarks or ())
        self._universe_memberships: tuple[UniverseMembership, ...] = tuple(universe_memberships or ())
        self._calendars: dict[str, TradingCalendar] = dict(calendars or {})

    def all_bars(self) -> tuple[PriceBar, ...]:
        """Read-only access to every bar currently stored, regardless of
        as_of_time. Not part of the DataRepository Protocol (which is
        as-of-query-only for consumers) — intended for ingestion-side
        bookkeeping (e.g. IngestionRunner idempotency seeding) and tests,
        not for Backtest/Feature/Decision code."""
        return self._bars

    def append_bars(self, new_bars: Sequence[PriceBar]) -> None:
        """Append-only ingestion of new bars. Does not remove or rewrite
        existing entries (a later data_version for the same
        security/timestamp simply becomes an additional entry; callers
        needing "latest" must resolve that themselves — Phase 1 does not
        yet implement automatic supersession resolution)."""
        self._bars = self._bars + tuple(new_bars)

    def get_bars(
        self, security_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[PriceBar]:
        for name, value in (("start", start), ("end", end), ("as_of_time", as_of_time)):
            _require_aware(name, value)
        results = [
            bar
            for bar in self._bars
            if bar.security_id == security_id
            and start <= bar.timestamp <= end
            and bar.available_time <= as_of_time  # look-ahead guard
        ]
        return sorted(results, key=lambda b: b.timestamp)

    def get_security(self, security_id: str, as_of_time: datetime) -> Optional[SecurityMaster]:
        _require_aware("as_of_time", as_of_time)
        for sec in self._securities:
            if sec.security_id == security_id and sec.is_valid_at(as_of_time):
                return sec
        return None

    def get_corporate_actions(
        self, security_id: str, start: datetime, end: datetime, as_of_time: datetime
    ) -> list[CorporateAction]:
        for name, value in (("start", start), ("end", end), ("as_of_time", as_of_time)):
            _require_aware(name, value)

        def _reference_time(action: CorporateAction) -> Optional[datetime]:
            return action.effective_time or action.event_time

        results = []
        for action in self._corporate_actions:
            if action.security_id != security_id:
                continue
            if action.available_time > as_of_time:  # look-ahead guard
                continue
            ref = _reference_time(action)
            if ref is not None and not (start <= ref <= end):
                continue
            results.append(action)
        return sorted(results, key=lambda a: _reference_time(a) or a.available_time)

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
        results = [
            point
            for point in self._benchmarks
            if point.benchmark_id == benchmark_id
            and start <= point.timestamp <= end
            and point.available_time <= as_of_time  # look-ahead guard
        ]
        return sorted(results, key=lambda p: p.timestamp)

    def get_universe(self, market: str, universe: str, as_of_time: datetime) -> list[str]:
        _require_aware("as_of_time", as_of_time)
        # `market` is accepted for interface symmetry with a future
        # multi-market universe registry; Phase 1's mock membership data
        # is not partitioned by market.
        members = [
            m.security_id
            for m in self._universe_memberships
            if m.universe == universe and m.is_member_at(as_of_time)
        ]
        return sorted(set(members))
