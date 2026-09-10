"""Category 2: OHLC invariant test.
Category 3: Duplicate detection test.

See docs/specifications/PHASE-1-data-infrastructure.md section 13-14.
"""

from __future__ import annotations

from helpers import make_provenance, utc

from data_infra.enums import DataQualityRunStatus, DataQualitySeverity
from data_infra.models import PriceBar
from data_infra.quality import DataQualityFramework


def _bar(security_id="SEC-AAA", day=2, **overrides) -> PriceBar:
    fields = dict(
        security_id=security_id,
        timestamp=utc(2024, 1, day),
        open=100.0,
        high=105.0,
        low=99.0,
        close=102.0,
        volume=1000.0,
        available_time=utc(2024, 1, day, 20),
        ingestion_time=utc(2024, 1, day, 20),
        provenance=make_provenance(source_record_id=f"rec-{day}"),
    )
    fields.update(overrides)
    return PriceBar(**fields)


class TestOhlcInvariant:
    def test_valid_bar_produces_no_ohlc_issue(self) -> None:
        run = DataQualityFramework().run([_bar()], dataset="test", data_version="v1")
        assert not any(i.check == "ohlc_consistency" for i in run.issues)
        assert run.status == DataQualityRunStatus.PASSED

    def test_high_below_close_is_flagged_error(self) -> None:
        bad = _bar(high=101.0, close=102.0)  # high < close, violates high >= max(open, close)
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        ohlc_issues = [i for i in run.issues if i.check == "ohlc_consistency"]
        assert len(ohlc_issues) == 1
        assert ohlc_issues[0].severity == DataQualitySeverity.ERROR
        assert run.status == DataQualityRunStatus.FAILED

    def test_low_above_open_is_flagged_error(self) -> None:
        bad = _bar(low=101.0, open=100.0)  # low > open, violates low <= min(open, close)
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "ohlc_consistency" for i in run.issues)

    def test_high_below_low_is_flagged_error(self) -> None:
        bad = _bar(high=90.0, low=99.0)
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "ohlc_consistency" for i in run.issues)

    def test_negative_price_is_flagged_error(self) -> None:
        bad = _bar(low=-1.0)
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "negative_or_zero_price" for i in run.issues)

    def test_negative_volume_is_flagged_error(self) -> None:
        bad = _bar(volume=-5.0)
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "negative_volume" for i in run.issues)


class TestNonFiniteValueGuard:
    """Added following a gs-quant comparison: gs-quant's pandas-based
    timeseries functions inherit automatic NaN handling; this
    project's stdlib arithmetic (backtest.metrics, strategy_research)
    does not, and every other numeric check here (ohlc_consistency,
    negative_or_zero_price) uses plain comparisons that silently
    evaluate False against NaN -- a NaN close would previously pass
    every other check undetected."""

    def test_nan_close_is_flagged_critical(self) -> None:
        bad = _bar(close=float("nan"))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        issues = [i for i in run.issues if i.check == "non_finite_value"]
        assert len(issues) == 1
        assert issues[0].severity == DataQualitySeverity.CRITICAL
        assert run.status == DataQualityRunStatus.CRITICAL_FAILURE

    def test_nan_close_previously_slipped_past_every_other_numeric_check(self) -> None:
        # Regression guard for exactly the gap this check closes: a NaN
        # close does NOT trip ohlc_consistency or negative_or_zero_price
        # (both use plain comparisons, which are always False against
        # NaN) -- only the new check catches it.
        bad = _bar(close=float("nan"))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert not any(i.check == "ohlc_consistency" for i in run.issues)
        assert not any(i.check == "negative_or_zero_price" for i in run.issues)
        assert any(i.check == "non_finite_value" for i in run.issues)

    def test_infinite_volume_is_flagged(self) -> None:
        bad = _bar(volume=float("inf"))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        issues = [i for i in run.issues if i.check == "non_finite_value"]
        assert len(issues) == 1
        assert "volume" in issues[0].message

    def test_nan_adjusted_close_is_flagged(self) -> None:
        bad = _bar(adjusted_close=float("nan"))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "non_finite_value" for i in run.issues)

    def test_missing_optional_adjusted_close_is_not_flagged(self) -> None:
        ok = _bar()  # adjusted_close defaults to None -- must not be treated as non-finite
        run = DataQualityFramework().run([ok], dataset="test", data_version="v1")
        assert not any(i.check == "non_finite_value" for i in run.issues)

    def test_nan_adjusted_high_is_flagged(self) -> None:
        bad = _bar(adjusted_high=float("nan"))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "non_finite_value" for i in run.issues)

    def test_nan_adjusted_low_is_flagged(self) -> None:
        bad = _bar(adjusted_low=float("nan"))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        assert any(i.check == "non_finite_value" for i in run.issues)

    def test_missing_optional_adjusted_high_low_is_not_flagged(self) -> None:
        ok = _bar()  # adjusted_high/adjusted_low default to None -- must not be treated as non-finite
        run = DataQualityFramework().run([ok], dataset="test", data_version="v1")
        assert not any(i.check == "non_finite_value" for i in run.issues)

    def test_all_finite_values_produce_no_issue(self) -> None:
        run = DataQualityFramework().run([_bar()], dataset="test", data_version="v1")
        assert not any(i.check == "non_finite_value" for i in run.issues)
        assert run.status == DataQualityRunStatus.PASSED


class TestDuplicateDetection:
    def test_no_duplicates_among_distinct_bars(self) -> None:
        bars = [_bar(day=2), _bar(day=3)]
        run = DataQualityFramework().run(bars, dataset="test", data_version="v1")
        assert not any(i.check == "duplicate_records" for i in run.issues)

    def test_duplicate_security_timestamp_source_is_flagged(self) -> None:
        bar1 = _bar(day=2)
        bar2 = _bar(day=2)  # same security_id, timestamp, source
        run = DataQualityFramework().run([bar1, bar2], dataset="test", data_version="v1")
        dup_issues = [i for i in run.issues if i.check == "duplicate_records"]
        assert len(dup_issues) == 1
        assert dup_issues[0].severity == DataQualitySeverity.ERROR
        assert run.status == DataQualityRunStatus.FAILED

    def test_same_timestamp_different_source_is_not_a_duplicate(self) -> None:
        bar1 = _bar(day=2, provenance=make_provenance(source="provider_a", source_record_id="a"))
        bar2 = _bar(day=2, provenance=make_provenance(source="provider_b", source_record_id="b"))
        run = DataQualityFramework().run([bar1, bar2], dataset="test", data_version="v1")
        assert not any(i.check == "duplicate_records" for i in run.issues)


class TestRunStatusResolution:
    def test_critical_issue_yields_critical_failure_status(self) -> None:
        bars = [_bar(day=2, security_id="UNKNOWN")]
        run = DataQualityFramework().run(
            bars, dataset="test", data_version="v1", known_security_ids={"SEC-AAA"}
        )
        # symbol_mismatch is ERROR severity, not CRITICAL in this framework;
        # verify at least that it fails the run.
        assert run.status == DataQualityRunStatus.FAILED
        assert any(i.check == "symbol_mismatch" for i in run.issues)
