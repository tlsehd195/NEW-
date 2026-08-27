"""Category: Real-Market-Data Quality Checks (Phase 20, instruction
section 12). Extends the Phase 1 `DataQualityFramework`
(`tests/data/test_quality.py` already covers OHLC/duplicate checks) with
the checks specific to ingesting real vendor data: ingestion-precedes-
availability (the exact leak class fixed in TiingoDataProvider during
this phase), missing-timestamp gaps, split/dividend consistency against
registered corporate actions, and explicit insufficient-coverage
flagging instead of a silent PASS.

All new `run()` parameters are optional/None-default (see quality.py's
run() docstring) -- this file only exercises the new, additive behavior;
tests/data/test_quality.py already proves the pre-Phase-20 call sites are
unaffected.
"""

from __future__ import annotations

from helpers import make_provenance, utc

from data_infra.enums import CorporateActionType, DataQualitySeverity
from data_infra.models import CorporateAction, PriceBar
from data_infra.quality import DataQualityFramework


def _bar(security_id="AAPL", day=2, hour=20, close=100.0, **overrides) -> PriceBar:
    fields = dict(
        security_id=security_id,
        timestamp=utc(2024, 1, day),
        open=close, high=close * 1.01, low=close * 0.99, close=close,
        volume=1_000_000.0,
        available_time=utc(2024, 1, day, hour),
        ingestion_time=utc(2024, 1, day, hour),
        provenance=make_provenance(source_record_id=f"rec-{security_id}-{day}"),
    )
    fields.update(overrides)
    return PriceBar(**fields)


def _split(security_id="AAPL", ratio=4.0, effective=None, ingestion=None, available=None) -> CorporateAction:
    effective = effective or utc(2024, 6, 10)
    ingestion = ingestion or effective
    available = available if available is not None else ingestion
    return CorporateAction(
        security_id=security_id,
        action_type=CorporateActionType.SPLIT if ratio > 1.0 else CorporateActionType.REVERSE_SPLIT,
        available_time=available,
        ingestion_time=ingestion,
        provenance=make_provenance(source_record_id=f"{security_id}-split"),
        event_time=effective,
        effective_time=effective,
        details={"ratio": ratio},
    )


def _dividend(security_id="AAPL", amount=0.24, effective=None, ingestion=None, available=None) -> CorporateAction:
    effective = effective or utc(2024, 3, 14)
    ingestion = ingestion or effective
    available = available if available is not None else ingestion
    return CorporateAction(
        security_id=security_id,
        action_type=CorporateActionType.DIVIDEND,
        available_time=available,
        ingestion_time=ingestion,
        provenance=make_provenance(source_record_id=f"{security_id}-div"),
        event_time=effective,
        effective_time=effective,
        details={"amount": amount, "currency": "USD"},
    )


class TestIngestionPrecedesAvailability:
    def test_bar_ingested_before_it_was_available_is_flagged_error(self) -> None:
        bad = _bar(available_time=utc(2024, 1, 5), ingestion_time=utc(2024, 1, 2))
        run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        hits = [i for i in run.issues if i.check == "ingestion_precedes_availability"]
        assert len(hits) == 1
        assert hits[0].severity == DataQualitySeverity.ERROR

    def test_normal_bar_where_ingestion_time_equals_available_time_is_not_flagged(self) -> None:
        run = DataQualityFramework().run([_bar()], dataset="test", data_version="v1")
        assert not any(i.check == "ingestion_precedes_availability" for i in run.issues)

    def test_corporate_action_ingested_before_available_is_flagged_error(self) -> None:
        bad_action = _split(available=utc(2024, 6, 10), ingestion=utc(2024, 6, 5))
        run = DataQualityFramework().run(
            [_bar(day=2), _bar(day=9, timestamp=utc(2024, 6, 9), close=25.0)],
            dataset="test", data_version="v1", corporate_actions=[bad_action],
        )
        hits = [i for i in run.issues if i.check == "ingestion_precedes_availability"]
        assert len(hits) == 1
        assert hits[0].severity == DataQualitySeverity.ERROR


class TestMissingTimestampGaps:
    def test_ordinary_weekend_gap_is_not_flagged(self) -> None:
        friday = _bar(day=5)  # Fri 2024-01-05
        monday = _bar(day=8)  # Mon 2024-01-08 -- a normal 3-day weekend
        run = DataQualityFramework().run([friday, monday], dataset="test", data_version="v1")
        assert not any(i.check == "missing_timestamp_gaps" for i in run.issues)

    def test_multi_day_gap_is_flagged_warning(self) -> None:
        first = _bar(day=2)
        later = _bar(day=15)  # nearly two weeks later -- clearly missing bars
        run = DataQualityFramework().run([first, later], dataset="test", data_version="v1")
        hits = [i for i in run.issues if i.check == "missing_timestamp_gaps"]
        assert len(hits) == 1
        assert hits[0].severity == DataQualitySeverity.WARNING


class TestInsufficientCoverage:
    def test_fewer_bars_than_expected_is_flagged_explicitly_not_silently_passed(self) -> None:
        run = DataQualityFramework().run(
            [_bar(day=2)], dataset="test", data_version="v1",
            min_expected_bars={"AAPL": 20},
        )
        hits = [i for i in run.issues if i.check == "insufficient_coverage"]
        assert len(hits) == 1
        assert "AAPL" in hits[0].message

    def test_meeting_the_expected_minimum_is_not_flagged(self) -> None:
        bars = [_bar(day=d) for d in range(2, 6)]
        run = DataQualityFramework().run(
            bars, dataset="test", data_version="v1", min_expected_bars={"AAPL": 4},
        )
        assert not any(i.check == "insufficient_coverage" for i in run.issues)

    def test_omitting_min_expected_bars_never_adds_the_check(self) -> None:
        """Backward compatibility: pre-Phase-20 callers never pass this
        parameter and must see identical behavior to before."""
        run = DataQualityFramework().run([_bar(day=2)], dataset="test", data_version="v1")
        assert not any(i.check == "insufficient_coverage" for i in run.issues)


class TestSplitConsistency:
    def test_matching_split_ratio_is_not_flagged(self) -> None:
        before = _bar(day=7, timestamp=utc(2024, 6, 7), close=400.0)
        after = _bar(day=10, timestamp=utc(2024, 6, 10), close=100.0)  # 4:1 split, matches ratio
        action = _split(ratio=4.0, effective=utc(2024, 6, 10))
        run = DataQualityFramework().run(
            [before, after], dataset="test", data_version="v1", corporate_actions=[action],
        )
        assert not any(i.check == "split_consistency" for i in run.issues)

    def test_mismatched_split_ratio_is_flagged_warning(self) -> None:
        before = _bar(day=7, timestamp=utc(2024, 6, 7), close=400.0)
        after = _bar(day=10, timestamp=utc(2024, 6, 10), close=395.0)  # barely moved, but a 4:1 split was registered
        action = _split(ratio=4.0, effective=utc(2024, 6, 10))
        run = DataQualityFramework().run(
            [before, after], dataset="test", data_version="v1", corporate_actions=[action],
        )
        hits = [i for i in run.issues if i.check == "split_consistency"]
        assert len(hits) == 1
        assert hits[0].severity == DataQualitySeverity.WARNING


class TestDividendConsistency:
    def test_ordinary_dividend_is_not_flagged(self) -> None:
        bar = _bar(day=14, timestamp=utc(2024, 3, 14), close=180.0)
        action = _dividend(amount=0.24, effective=utc(2024, 3, 14))
        run = DataQualityFramework().run(
            [bar], dataset="test", data_version="v1", corporate_actions=[action],
        )
        assert not any(i.check == "dividend_consistency" for i in run.issues)

    def test_dividend_larger_than_price_is_flagged_error(self) -> None:
        bar = _bar(day=14, timestamp=utc(2024, 3, 14), close=10.0)
        action = _dividend(amount=50.0, effective=utc(2024, 3, 14))  # implausible: dividend > price
        run = DataQualityFramework().run(
            [bar], dataset="test", data_version="v1", corporate_actions=[action],
        )
        hits = [i for i in run.issues if i.check == "dividend_consistency"]
        assert len(hits) == 1
        assert hits[0].severity == DataQualitySeverity.ERROR


class TestBackwardCompatibility:
    def test_bars_only_call_site_produces_identical_check_set_semantics(self) -> None:
        """A pre-Phase-20 call (bars only, no corporate_actions/
        min_expected_bars) must never emit any of the new checks for
        ordinary, well-formed data."""
        run = DataQualityFramework().run([_bar(day=2), _bar(day=3)], dataset="test", data_version="v1")
        new_checks = {
            "ingestion_precedes_availability", "missing_timestamp_gaps",
            "split_consistency", "dividend_consistency", "insufficient_coverage",
        }
        assert not any(i.check in new_checks for i in run.issues)
