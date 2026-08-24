"""Data Quality Framework.

See docs/specifications/PHASE-1-data-infrastructure.md section 13.

Checks here are deliberately non-destructive: running the framework never
mutates or drops a record. It only produces a DataQualityRun describing
what it found, at what severity, so that promotion (Raw -> Clean) and
downstream consumers can decide what to do with the result (Phase 1 spec
section 3.1 error states).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from data_infra.enums import DataQualityRunStatus, DataQualitySeverity
from data_infra.models import PriceBar


@dataclass(frozen=True)
class DataQualityIssue:
    check: str
    severity: DataQualitySeverity
    message: str
    security_id: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass(frozen=True)
class DataQualityRun:
    validation_id: str
    dataset: str
    data_version: str
    timestamp: datetime
    checks: tuple[str, ...]
    issues: tuple[DataQualityIssue, ...]
    status: DataQualityRunStatus

    @property
    def warnings(self) -> tuple[DataQualityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == DataQualitySeverity.WARNING)

    @property
    def errors(self) -> tuple[DataQualityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == DataQualitySeverity.ERROR)

    @property
    def critical_errors(self) -> tuple[DataQualityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == DataQualitySeverity.CRITICAL)


_CHECK_NAMES = (
    # missing_values and invalid_timestamps are enforced structurally at
    # PriceBar construction (data_infra.models.__post_init__) rather than
    # here: a PriceBar instance reaching this framework has already,
    # necessarily, passed both checks. They are still listed as checks
    # performed, since that guarantee is exactly what "check passed" means.
    "missing_values",
    "invalid_timestamps",
    "duplicate_records",
    "ohlc_consistency",
    "negative_or_zero_price",
    "negative_volume",
    "impossible_price_movement",
    "stale_data",
    "symbol_mismatch",
    "future_dated",
)

# A single-bar move beyond this multiple of the prior close is flagged as
# an "impossible price movement". Chosen conservatively; revisit once real
# market data is in use (Phase 1 spec section 13.1).
_EXTREME_MOVE_THRESHOLD = 0.5  # 50% single-bar move


class DataQualityFramework:
    """Runs Phase 1 data quality checks over a batch of PriceBars.

    One instance is expected to be reused across a session so that
    validation_id increments monotonically per Phase 1 spec section
    13.3 ("DQ-000001" style, monotonic) — this is intentionally simple,
    in-process, sequential state, not a persisted registry.
    """

    def __init__(self) -> None:
        self._next_id = 1

    def _allocate_id(self) -> str:
        vid = f"DQ-{self._next_id:06d}"
        self._next_id += 1
        return vid

    def run(
        self,
        bars: Sequence[PriceBar],
        *,
        dataset: str,
        data_version: str,
        known_security_ids: Optional[set[str]] = None,
        expected_update_interval: timedelta = timedelta(days=5),
        as_of_now: Optional[datetime] = None,
    ) -> DataQualityRun:
        issues: list[DataQualityIssue] = []
        issues.extend(self._check_duplicates(bars))
        issues.extend(self._check_ohlc_consistency(bars))
        issues.extend(self._check_negative_or_zero_price(bars))
        issues.extend(self._check_negative_volume(bars))
        issues.extend(self._check_impossible_movement(bars))
        issues.extend(self._check_symbol_mismatch(bars, known_security_ids))
        if as_of_now is not None:
            issues.extend(self._check_future_dated(bars, as_of_now))
            issues.extend(self._check_stale_data(bars, as_of_now, expected_update_interval))

        status = self._resolve_status(issues)
        return DataQualityRun(
            validation_id=self._allocate_id(),
            dataset=dataset,
            data_version=data_version,
            timestamp=as_of_now or datetime.now().astimezone(),
            checks=_CHECK_NAMES,
            issues=tuple(issues),
            status=status,
        )

    @staticmethod
    def _resolve_status(issues: Iterable[DataQualityIssue]) -> DataQualityRunStatus:
        issues = list(issues)
        if any(i.severity == DataQualitySeverity.CRITICAL for i in issues):
            return DataQualityRunStatus.CRITICAL_FAILURE
        if any(i.severity == DataQualitySeverity.ERROR for i in issues):
            return DataQualityRunStatus.FAILED
        if any(i.severity == DataQualitySeverity.WARNING for i in issues):
            return DataQualityRunStatus.PASSED_WITH_WARNINGS
        return DataQualityRunStatus.PASSED

    @staticmethod
    def _check_duplicates(bars: Sequence[PriceBar]) -> list[DataQualityIssue]:
        seen: dict[tuple[str, datetime, str], int] = {}
        issues: list[DataQualityIssue] = []
        for bar in bars:
            key = (bar.security_id, bar.timestamp, bar.provenance.source)
            seen[key] = seen.get(key, 0) + 1
        for (security_id, timestamp, source), count in seen.items():
            if count > 1:
                issues.append(
                    DataQualityIssue(
                        check="duplicate_records",
                        severity=DataQualitySeverity.ERROR,
                        message=f"{count} records found for security_id={security_id} "
                        f"timestamp={timestamp.isoformat()} source={source}",
                        security_id=security_id,
                        timestamp=timestamp,
                    )
                )
        return issues

    @staticmethod
    def _check_ohlc_consistency(bars: Sequence[PriceBar]) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        for bar in bars:
            valid = (
                bar.high >= max(bar.open, bar.close)
                and bar.low <= min(bar.open, bar.close)
                and bar.high >= bar.low
            )
            if not valid:
                issues.append(
                    DataQualityIssue(
                        check="ohlc_consistency",
                        severity=DataQualitySeverity.ERROR,
                        message=(
                            f"OHLC invariant violated: open={bar.open} high={bar.high} "
                            f"low={bar.low} close={bar.close}"
                        ),
                        security_id=bar.security_id,
                        timestamp=bar.timestamp,
                    )
                )
        return issues

    @staticmethod
    def _check_negative_or_zero_price(bars: Sequence[PriceBar]) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        for bar in bars:
            if min(bar.open, bar.high, bar.low, bar.close) <= 0:
                issues.append(
                    DataQualityIssue(
                        check="negative_or_zero_price",
                        severity=DataQualitySeverity.ERROR,
                        message=f"Non-positive price in bar: {bar.open=} {bar.high=} {bar.low=} {bar.close=}",
                        security_id=bar.security_id,
                        timestamp=bar.timestamp,
                    )
                )
        return issues

    @staticmethod
    def _check_negative_volume(bars: Sequence[PriceBar]) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        for bar in bars:
            if bar.volume < 0:
                issues.append(
                    DataQualityIssue(
                        check="negative_volume",
                        severity=DataQualitySeverity.ERROR,
                        message=f"Negative volume: {bar.volume}",
                        security_id=bar.security_id,
                        timestamp=bar.timestamp,
                    )
                )
        return issues

    @staticmethod
    def _check_impossible_movement(bars: Sequence[PriceBar]) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        by_security: dict[str, list[PriceBar]] = {}
        for bar in bars:
            by_security.setdefault(bar.security_id, []).append(bar)
        for security_id, series in by_security.items():
            ordered = sorted(series, key=lambda b: b.timestamp)
            for prev, cur in zip(ordered, ordered[1:]):
                if prev.close <= 0:
                    continue
                move = abs(cur.close - prev.close) / prev.close
                if move > _EXTREME_MOVE_THRESHOLD:
                    issues.append(
                        DataQualityIssue(
                            check="impossible_price_movement",
                            severity=DataQualitySeverity.WARNING,
                            message=f"{move:.1%} move from {prev.close} to {cur.close}",
                            security_id=security_id,
                            timestamp=cur.timestamp,
                        )
                    )
        return issues

    @staticmethod
    def _check_symbol_mismatch(
        bars: Sequence[PriceBar], known_security_ids: Optional[set[str]]
    ) -> list[DataQualityIssue]:
        if known_security_ids is None:
            return []
        issues: list[DataQualityIssue] = []
        for bar in bars:
            if bar.security_id not in known_security_ids:
                issues.append(
                    DataQualityIssue(
                        check="symbol_mismatch",
                        severity=DataQualitySeverity.ERROR,
                        message=f"Unknown security_id: {bar.security_id}",
                        security_id=bar.security_id,
                        timestamp=bar.timestamp,
                    )
                )
        return issues

    @staticmethod
    def _check_future_dated(bars: Sequence[PriceBar], as_of_now: datetime) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        for bar in bars:
            if bar.available_time > as_of_now:
                issues.append(
                    DataQualityIssue(
                        check="future_dated",
                        severity=DataQualitySeverity.ERROR,
                        message=f"available_time {bar.available_time.isoformat()} is after as_of_now "
                        f"{as_of_now.isoformat()}",
                        security_id=bar.security_id,
                        timestamp=bar.timestamp,
                    )
                )
        return issues

    @staticmethod
    def _check_stale_data(
        bars: Sequence[PriceBar], as_of_now: datetime, expected_update_interval: timedelta
    ) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        latest_by_security: dict[str, datetime] = {}
        for bar in bars:
            latest = latest_by_security.get(bar.security_id)
            if latest is None or bar.timestamp > latest:
                latest_by_security[bar.security_id] = bar.timestamp
        for security_id, latest in latest_by_security.items():
            if as_of_now - latest > expected_update_interval:
                issues.append(
                    DataQualityIssue(
                        check="stale_data",
                        severity=DataQualitySeverity.WARNING,
                        message=f"Last observation at {latest.isoformat()}, "
                        f"more than {expected_update_interval} before {as_of_now.isoformat()}",
                        security_id=security_id,
                        timestamp=latest,
                    )
                )
        return issues
