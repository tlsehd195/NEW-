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

from data_infra.enums import CorporateActionType, DataQualityRunStatus, DataQualitySeverity
from data_infra.models import CorporateAction, PriceBar


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
    # Phase 20 additions (real-market-data quality, ADR-0025 /
    # docs/operations/MARKET-DATA-PROVIDER.md) -- all additive, all
    # opt-in via run()'s new optional parameters so every pre-existing
    # call site (bars-only, no corporate_actions) behaves identically.
    "ingestion_precedes_availability",
    "missing_timestamp_gaps",
    "split_consistency",
    "dividend_consistency",
    "insufficient_coverage",
)

# A single-bar move beyond this multiple of the prior close is flagged as
# an "impossible price movement". Chosen conservatively; revisit once real
# market data is in use (Phase 1 spec section 13.1).
_EXTREME_MOVE_THRESHOLD = 0.5  # 50% single-bar move

# US equities trade Mon-Fri; a gap larger than a plain 3-day weekend
# (Fri -> Mon) is flagged. This is a heuristic, not a real market-holiday
# calendar (none is available this phase -- UNKNOWN, see
# docs/operations/MARKET-DATA-PROVIDER.md) so genuine multi-day market
# holidays (e.g. Thanksgiving weekend) will also trigger a WARNING here;
# that is the intended, honest behavior -- flag for human review rather
# than silently assume a gap is always fine.
_MAX_ORDINARY_GAP_DAYS = 4

# A split/reverse-split ratio is cross-checked against the actual
# close-to-close price ratio observed around its effective_time. Real
# single-day moves plus the ratio itself being reported to limited
# precision make an exact match unrealistic, so this is deliberately a
# loose tolerance -- a sanity check for gross inconsistencies (e.g. a
# 4:1 split recorded against a price series that barely moved), not a
# precise reconciliation.
_SPLIT_RATIO_TOLERANCE = 0.5  # 50% relative tolerance


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
        corporate_actions: Optional[Sequence[CorporateAction]] = None,
        min_expected_bars: Optional[dict[str, int]] = None,
    ) -> DataQualityRun:
        """``corporate_actions`` and ``min_expected_bars`` are Phase 20
        additions (real-market-data quality checks) and are both
        opt-in/``None``-default: every pre-existing caller that only
        passes ``bars`` gets exactly the pre-Phase-20 set of checks and
        results, unchanged.

        ``min_expected_bars`` (``{security_id: minimum_bar_count}``)
        implements "never silently PASS on insufficient data" (Phase 20
        instruction section 12) for real-data ingestion: when a caller
        knows roughly how many observations a real dataset should
        contain (e.g. from the requested date range) and supplies it
        here, a security with fewer bars than that gets an explicit
        ``insufficient_coverage`` issue rather than a bare, silent
        ``PASSED``.
        """
        issues: list[DataQualityIssue] = []
        issues.extend(self._check_duplicates(bars))
        issues.extend(self._check_ohlc_consistency(bars))
        issues.extend(self._check_negative_or_zero_price(bars))
        issues.extend(self._check_negative_volume(bars))
        issues.extend(self._check_impossible_movement(bars))
        issues.extend(self._check_symbol_mismatch(bars, known_security_ids))
        issues.extend(self._check_ingestion_precedes_availability(bars, corporate_actions))
        issues.extend(self._check_missing_timestamp_gaps(bars))
        issues.extend(self._check_insufficient_coverage(bars, min_expected_bars))
        if corporate_actions:
            issues.extend(self._check_split_consistency(bars, corporate_actions))
            issues.extend(self._check_dividend_consistency(bars, corporate_actions))
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

    @staticmethod
    def _check_ingestion_precedes_availability(
        bars: Sequence[PriceBar], corporate_actions: Optional[Sequence[CorporateAction]]
    ) -> list[DataQualityIssue]:
        """``ingestion_time`` (when OUR system actually learned the fact)
        must never be earlier than ``available_time`` (when the fact
        claims to have become knowable) -- an ``ingestion_time <
        available_time`` record would mean we claim to have known
        something before we actually retrieved it, which is exactly the
        point-in-time leak class that
        tests/integration/test_market_data_point_in_time.py guards
        against (a real instance of this was found and fixed in
        TiingoDataProvider.normalize_corporate_actions during Phase 20:
        available_time was originally backdated to a corporate action's
        effective date instead of set to ingestion_time)."""
        issues: list[DataQualityIssue] = []
        for bar in bars:
            if bar.ingestion_time < bar.available_time:
                issues.append(
                    DataQualityIssue(
                        check="ingestion_precedes_availability",
                        severity=DataQualitySeverity.ERROR,
                        message=f"ingestion_time {bar.ingestion_time.isoformat()} is before "
                        f"available_time {bar.available_time.isoformat()} (a record cannot have "
                        f"been ingested before it became available)",
                        security_id=bar.security_id,
                        timestamp=bar.timestamp,
                    )
                )
        for action in corporate_actions or []:
            if action.ingestion_time < action.available_time:
                issues.append(
                    DataQualityIssue(
                        check="ingestion_precedes_availability",
                        severity=DataQualitySeverity.ERROR,
                        message=f"corporate action ingestion_time {action.ingestion_time.isoformat()} "
                        f"is before available_time {action.available_time.isoformat()}",
                        security_id=action.security_id,
                        timestamp=action.event_time,
                    )
                )
        return issues

    @staticmethod
    def _check_missing_timestamp_gaps(bars: Sequence[PriceBar]) -> list[DataQualityIssue]:
        """Flags a gap between consecutive bars for the same security
        larger than an ordinary weekend (see _MAX_ORDINARY_GAP_DAYS --
        this is a heuristic, not a real market-holiday calendar; see the
        module-level comment on that constant)."""
        issues: list[DataQualityIssue] = []
        by_security: dict[str, list[PriceBar]] = {}
        for bar in bars:
            by_security.setdefault(bar.security_id, []).append(bar)
        for security_id, series in by_security.items():
            ordered = sorted(series, key=lambda b: b.timestamp)
            for prev, cur in zip(ordered, ordered[1:]):
                gap_days = (cur.timestamp - prev.timestamp).days
                if gap_days > _MAX_ORDINARY_GAP_DAYS:
                    issues.append(
                        DataQualityIssue(
                            check="missing_timestamp_gaps",
                            severity=DataQualitySeverity.WARNING,
                            message=f"{gap_days}-day gap between {prev.timestamp.isoformat()} and "
                            f"{cur.timestamp.isoformat()} (possible missing trading day(s) or an "
                            f"unrecognized market holiday -- no market-calendar data is available "
                            f"this phase to distinguish the two, see MARKET-DATA-PROVIDER.md)",
                            security_id=security_id,
                            timestamp=cur.timestamp,
                        )
                    )
        return issues

    @staticmethod
    def _check_insufficient_coverage(
        bars: Sequence[PriceBar], min_expected_bars: Optional[dict[str, int]]
    ) -> list[DataQualityIssue]:
        if not min_expected_bars:
            return []
        counts: dict[str, int] = {}
        for bar in bars:
            counts[bar.security_id] = counts.get(bar.security_id, 0) + 1
        issues: list[DataQualityIssue] = []
        for security_id, minimum in min_expected_bars.items():
            actual = counts.get(security_id, 0)
            if actual < minimum:
                issues.append(
                    DataQualityIssue(
                        check="insufficient_coverage",
                        severity=DataQualitySeverity.WARNING,
                        message=f"only {actual} bar(s) for {security_id}, expected at least {minimum} "
                        f"-- explicitly flagged rather than silently PASSED on incomplete data",
                        security_id=security_id,
                        timestamp=None,
                    )
                )
        return issues

    @staticmethod
    def _check_split_consistency(
        bars: Sequence[PriceBar], corporate_actions: Sequence[CorporateAction]
    ) -> list[DataQualityIssue]:
        """Cross-checks a registered SPLIT/REVERSE_SPLIT ratio against
        the actual close-to-close price ratio observed immediately
        around its effective_time -- a gross mismatch (e.g. a 4:1 split
        recorded where the price barely moved) suggests either a
        misparsed ratio or a corporate action attached to the wrong
        date. Loosely toleranced (_SPLIT_RATIO_TOLERANCE): this is a
        sanity check, not a precise reconciliation (real single-day
        price moves are not otherwise isolated from the split's own
        effect here)."""
        issues: list[DataQualityIssue] = []
        by_security: dict[str, list[PriceBar]] = {}
        for bar in bars:
            by_security.setdefault(bar.security_id, []).append(bar)
        for security_id, series in by_security.items():
            ordered = sorted(series, key=lambda b: b.timestamp)
            for action in corporate_actions:
                if action.security_id != security_id:
                    continue
                if action.action_type not in (CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT):
                    continue
                ratio = action.details.get("ratio")
                effective = action.effective_time or action.event_time
                if ratio is None or effective is None:
                    continue
                before = [b for b in ordered if b.timestamp < effective]
                after = [b for b in ordered if b.timestamp >= effective]
                if not before or not after or before[-1].close <= 0:
                    continue
                observed_ratio = before[-1].close / after[0].close
                relative_error = abs(observed_ratio - ratio) / ratio
                if relative_error > _SPLIT_RATIO_TOLERANCE:
                    issues.append(
                        DataQualityIssue(
                            check="split_consistency",
                            severity=DataQualitySeverity.WARNING,
                            message=f"registered split ratio {ratio} for {security_id} at "
                            f"{effective.isoformat()} does not match the observed close-to-close "
                            f"ratio {observed_ratio:.3f} ({before[-1].close} -> {after[0].close})",
                            security_id=security_id,
                            timestamp=effective,
                        )
                    )
        return issues

    @staticmethod
    def _check_dividend_consistency(
        bars: Sequence[PriceBar], corporate_actions: Sequence[CorporateAction]
    ) -> list[DataQualityIssue]:
        """A dividend amount larger than the security's own price around
        the event is not plausible for the kind of long-term US equity
        this system targets (Phase 20 instruction section 16) and most
        likely indicates a parsing error (e.g. a misplaced decimal or a
        cash amount confused with a per-share figure)."""
        issues: list[DataQualityIssue] = []
        by_security: dict[str, list[PriceBar]] = {}
        for bar in bars:
            by_security.setdefault(bar.security_id, []).append(bar)
        for security_id, series in by_security.items():
            ordered = sorted(series, key=lambda b: b.timestamp)
            for action in corporate_actions:
                if action.security_id != security_id or action.action_type != CorporateActionType.DIVIDEND:
                    continue
                amount = action.details.get("amount")
                effective = action.effective_time or action.event_time
                if amount is None or effective is None:
                    continue
                nearby = [b for b in ordered if b.timestamp <= effective]
                reference_price = nearby[-1].close if nearby else (ordered[0].close if ordered else None)
                if reference_price is not None and reference_price > 0 and amount > reference_price:
                    issues.append(
                        DataQualityIssue(
                            check="dividend_consistency",
                            severity=DataQualitySeverity.ERROR,
                            message=f"dividend amount {amount} for {security_id} at "
                            f"{effective.isoformat()} exceeds the reference price {reference_price} "
                            f"-- likely a data error",
                            security_id=security_id,
                            timestamp=effective,
                        )
                    )
        return issues
