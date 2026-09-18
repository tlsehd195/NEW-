"""Category: real-data quality gating (Session 37).

Regression tests for the gap found while explaining Paper Trading's data
pipeline to the account owner: `DataQualityFramework.run()` (Phase 1 spec
section 13) produced a `DataQualityRun` that nothing ever read back --
CRITICAL-severity findings (data corruption, e.g. a non-finite price)
did not stop the affected bar from being served to Paper Trading,
backtest, strategy_research, or the Learning Cycle, and
`scripts/ingest_real_market_data.py`'s own exit code ignored
`quality_run.status` entirely.

These tests exercise `DuckDBDataRepository.record_quality_issues`/
`get_bars` against `data_infra.quality.DataQualityFramework`'s REAL
output (never a hand-built `DataQualityRun`), implementing Phase 1 spec
section 3.1's QUALITY_REJECTED (CRITICAL -> excluded from the default
Clean view) / QUALITY_FLAGGED (WARNING/ERROR -> recorded, but still
included) states for the first time.
"""

from __future__ import annotations

import math
from datetime import date

from test_data_repository_persistence import make_bar

from backtest_helpers import utc

from data_infra.enums import DataQualitySeverity
from data_infra.quality import DataQualityFramework

from storage.data_repository import DuckDBDataRepository

from storage_helpers import new_engine


def _nan_bar(security_id: str, day: date) -> object:
    bar = make_bar(security_id, day, 100.0)
    # PriceBar is frozen -- construct a fresh one with the same fields but
    # a non-finite close, exactly the kind of corruption
    # non_finite_value's own docstring in data_infra/quality.py describes
    # (nothing at PriceBar construction time guards against it -- that is
    # precisely why the DQ check exists).
    import dataclasses

    return dataclasses.replace(bar, close=math.nan)


class TestCriticalFindingsAreExcludedByDefault:
    def test_a_bar_with_a_critical_finding_is_excluded_from_get_bars_by_default(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        good = make_bar("AAA", date(2024, 1, 2), 100.0)
        bad = _nan_bar("AAA", date(2024, 1, 3))
        repo.append_bars([good, bad])

        quality_run = DataQualityFramework().run(
            [good, bad], dataset="test", data_version="v1", known_security_ids={"AAA"},
        )
        assert quality_run.status.value == "CRITICAL_FAILURE"
        repo.record_quality_issues(quality_run)

        result = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert [b.timestamp.day for b in result] == [2]

        engine.close()

    def test_include_quality_rejected_bypasses_the_exclusion_for_audit(self, tmp_path) -> None:
        """Raw Immutability (Phase 1 spec section 17): the CRITICAL bar is
        never deleted, only excluded from the default view."""
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        bad = _nan_bar("AAA", date(2024, 1, 3))
        repo.append_bars([bad])
        quality_run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        repo.record_quality_issues(quality_run)

        excluded = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert excluded == []

        included = repo.get_bars(
            "AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31),
            include_quality_rejected=True,
        )
        assert len(included) == 1

        engine.close()

    def test_exclusion_survives_engine_restart(self, tmp_path) -> None:
        """`data_quality_flags` round-trips the same on-disk catalog every
        other DuckDB-backed table in this repository does -- a fresh
        process/instance must see the same rejection, not just the one
        that originally computed it."""
        config_path = tmp_path / "store"
        from storage.config import StorageConfig
        from storage.engine import StorageEngine

        engine1 = StorageEngine(StorageConfig(config_path))
        repo1 = DuckDBDataRepository(engine1)
        bad = _nan_bar("AAA", date(2024, 1, 3))
        repo1.append_bars([bad])
        quality_run = DataQualityFramework().run([bad], dataset="test", data_version="v1")
        repo1.record_quality_issues(quality_run)
        engine1.close()

        engine2 = StorageEngine(StorageConfig(config_path))
        repo2 = DuckDBDataRepository(engine2)
        result = repo2.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert result == []
        engine2.close()


class TestNonCriticalFindingsAreRecordedButNotExcluded:
    def test_a_warning_or_error_finding_is_persisted_but_the_bar_stays_included(self, tmp_path) -> None:
        """Phase 1 spec section 3.1: WARNING/ERROR findings are
        QUALITY_FLAGGED (promoted to Clean, carrying a reference a
        consumer can inspect/filter on) -- NOT rejected outright the way
        CRITICAL findings are. Two duplicate-timestamp records for the
        same security, source, but a different data_version is exactly
        ADR-0085's deliberate 7-day ingestion overlap catching a
        provider revision -- a WARNING-severity `duplicate_records`
        finding (external review, 2026-09-18: downgraded from ERROR,
        since this is the expected outcome of a documented feature, not
        an accidental duplicate ingestion), not a non-finite-value
        problem."""
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        dupe_a = make_bar("AAA", date(2024, 1, 3), 100.0, source="s1")
        dupe_b = make_bar("AAA", date(2024, 1, 3), 101.0, source="s1")
        repo.append_bars([dupe_a])
        # append_bars dedupes on (security_id, timestamp, source,
        # data_version) -- give the duplicate a distinct data_version so
        # both rows are actually written, matching how two different real
        # ingestion runs could genuinely both persist a record for the
        # same (security, timestamp, source).
        dupe_b = make_bar("AAA", date(2024, 1, 3), 101.0, source="s1", data_version="v2")
        repo.append_bars([dupe_b])

        quality_run = DataQualityFramework().run([dupe_a, dupe_b], dataset="test", data_version="v1")
        assert quality_run.status.value == "PASSED_WITH_WARNINGS"
        assert any(i.severity == DataQualitySeverity.WARNING for i in quality_run.issues)
        assert not any(i.severity == DataQualitySeverity.ERROR for i in quality_run.issues)
        written = repo.record_quality_issues(quality_run)
        assert written >= 1

        # Every real consumer sees exactly one canonical bar per calendar
        # day -- the most recently ingested revision -- even though both
        # physical rows are immutably persisted (Raw Immutability).
        result = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(result) == 1
        audit = repo.get_bars(
            "AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31), include_quality_rejected=True
        )
        assert len(audit) == 2

        engine.close()

    def test_issues_with_no_timestamp_are_not_persisted_but_do_not_error(self, tmp_path) -> None:
        """A dataset/security-level issue (e.g. insufficient_coverage) has
        no single bar to attach a rejection to -- record_quality_issues
        must silently skip it rather than crash on a NULL primary-key
        column."""
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        bar = make_bar("AAA", date(2024, 1, 3), 100.0)
        repo.append_bars([bar])

        quality_run = DataQualityFramework().run(
            [bar], dataset="test", data_version="v1", min_expected_bars={"AAA": 100},
        )
        assert any(i.check == "insufficient_coverage" and i.timestamp is None for i in quality_run.issues)
        written = repo.record_quality_issues(quality_run)
        assert written == 0

        engine.close()


class TestRecordQualityIssuesIsIdempotent:
    def test_recording_the_same_quality_run_twice_does_not_error_or_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        bad = _nan_bar("AAA", date(2024, 1, 3))
        repo.append_bars([bad])
        quality_run = DataQualityFramework().run([bad], dataset="test", data_version="v1")

        first = repo.record_quality_issues(quality_run)
        second = repo.record_quality_issues(quality_run)
        assert first == second

        rows = engine.connection.execute("SELECT count(*) FROM data_quality_flags").fetchone()
        assert rows[0] == first

        engine.close()
