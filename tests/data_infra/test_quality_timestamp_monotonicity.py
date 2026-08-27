"""Category: Data Quality Check (Phase 22 instruction section 10) --
timestamp monotonicity. `DataQualityFramework` internally re-sorts by
timestamp before every other check does its own analysis (duplicate
detection, gap detection, extreme-move detection), which means a
provider response returning records out of chronological order was
previously silently tolerated with no signal at all. This check closes
that gap: it inspects the exact order the caller supplied `bars` in
(before any internal re-sort) and flags a genuine reversal."""

from __future__ import annotations

from helpers import make_provenance, utc

from data_infra.enums import DataQualitySeverity
from data_infra.models import PriceBar
from data_infra.quality import DataQualityFramework


def _bar(security_id="AAPL", day=2, close=100.0) -> PriceBar:
    return PriceBar(
        security_id=security_id,
        timestamp=utc(2024, 1, day),
        open=close, high=close * 1.01, low=close * 0.99, close=close,
        volume=1_000_000.0,
        available_time=utc(2024, 1, day, 20),
        ingestion_time=utc(2024, 1, day, 20),
        provenance=make_provenance(source_record_id=f"rec-{security_id}-{day}"),
    )


class TestTimestampMonotonicity:
    def test_ascending_order_produces_no_issue(self) -> None:
        bars = [_bar(day=2), _bar(day=3), _bar(day=4)]
        run = DataQualityFramework().run(bars, dataset="test", data_version="v1")
        assert not any(i.check == "timestamp_monotonicity" for i in run.issues)

    def test_reversed_pair_is_flagged_warning(self) -> None:
        bars = [_bar(day=4), _bar(day=2)]  # day 2 arrives after day 4 -- out of order
        run = DataQualityFramework().run(bars, dataset="test", data_version="v1")
        matches = [i for i in run.issues if i.check == "timestamp_monotonicity"]
        assert len(matches) == 1
        assert matches[0].severity == DataQualitySeverity.WARNING
        assert matches[0].security_id == "AAPL"

    def test_exact_duplicate_timestamp_is_not_double_counted_here(self) -> None:
        """An exact repeat is `_check_duplicates`'s ERROR-severity job,
        not this check's -- this check only fires on a genuine
        chronological reversal (strictly earlier), not an exact repeat."""
        bars = [_bar(day=2), _bar(day=2)]
        run = DataQualityFramework().run(bars, dataset="test", data_version="v1")
        assert not any(i.check == "timestamp_monotonicity" for i in run.issues)
        assert any(i.check == "duplicate_records" for i in run.issues)

    def test_out_of_order_across_different_securities_is_independent(self) -> None:
        """Each security_id's own chronological order is tracked
        separately -- interleaving AAPL and MSFT bars in the input does
        not, by itself, count as either one being out of order."""
        bars = [_bar(security_id="AAPL", day=2), _bar(security_id="MSFT", day=2),
                _bar(security_id="AAPL", day=3), _bar(security_id="MSFT", day=3)]
        run = DataQualityFramework().run(bars, dataset="test", data_version="v1")
        assert not any(i.check == "timestamp_monotonicity" for i in run.issues)

    def test_check_name_is_listed_in_checks_performed(self) -> None:
        run = DataQualityFramework().run([_bar()], dataset="test", data_version="v1")
        assert "timestamp_monotonicity" in run.checks
