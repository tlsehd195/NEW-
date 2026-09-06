"""Tests for `data_infra.providers.file_import.LocalFileDataProvider`
(Phase 31, instruction section 21: external dataset import workflow).

Unlike the Tiingo/Stooq providers, this provider never makes a network
call -- it reads local CSV files -- so these are REAL, executable
integration tests (not AST-only wiring tests): they write real CSV
fixtures to a temp directory and run them through the actual
`IngestionRunner`/`DuckDBDataRepository`/`DataQualityFramework`
pipeline, on a real on-disk DuckDB catalog. This is a synthetic
pipeline test (the CSV content is fabricated by the test itself for
determinism) -- it proves the *mechanism* works, not that any real
external dataset has been acquired (none has; see
docs/decisions/ADR-0034-real-data-acquisition-strategy.md).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data_infra.enums import IngestionStatus
from data_infra.provider import IngestionRunner, PermanentProviderError
from data_infra.providers.file_import import FileImportConfig, LocalFileDataProvider
from data_infra.quality import DataQualityFramework
from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _write_csv(path, rows, *, columns=("date", "open", "high", "low", "close", "volume", "adj_close")):
    import csv

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestFileImportConfig:
    def test_empty_source_name_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="source_name"):
            FileImportConfig(source_name="", data_dir=tmp_path)

    def test_configuration_version_includes_source_name(self, tmp_path) -> None:
        config = FileImportConfig(source_name="nasdaq_data_link_sharadar", data_dir=tmp_path)
        assert "nasdaq_data_link_sharadar" in config.configuration_version()


class TestLocalFileDataProviderFetch:
    def test_missing_file_raises_permanent_error(self, tmp_path) -> None:
        config = FileImportConfig(source_name="test_source", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        with pytest.raises(PermanentProviderError, match="no local file"):
            provider.fetch("NOSUCHFILE", utc(2010, 1, 1), utc(2010, 12, 31))

    def test_missing_required_column_raises_permanent_error(self, tmp_path) -> None:
        _write_csv(
            tmp_path / "BADCOLS.csv",
            [{"date": "2010-01-04", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "adj_close": "1.5"}],
            columns=("date", "open", "high", "low", "close", "adj_close"),  # missing "volume"
        )
        config = FileImportConfig(source_name="test_source", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        with pytest.raises(PermanentProviderError, match="missing required column"):
            provider.fetch("BADCOLS", utc(2010, 1, 1), utc(2010, 12, 31))

    def test_rows_outside_requested_range_are_excluded(self, tmp_path) -> None:
        _write_csv(
            tmp_path / "AAA.csv",
            [
                {"date": "2009-12-31", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "10", "adj_close": "1"},
                {"date": "2010-06-15", "open": "2", "high": "2", "low": "2", "close": "2", "volume": "20", "adj_close": "2"},
                {"date": "2011-01-01", "open": "3", "high": "3", "low": "3", "close": "3", "volume": "30", "adj_close": "3"},
            ],
        )
        config = FileImportConfig(source_name="test_source", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        rows = provider.fetch("AAA", utc(2010, 1, 1), utc(2010, 12, 31))
        assert [r["date"] for r in rows] == ["2010-06-15"]


class TestLocalFileDataProviderNormalize:
    def test_normalized_bar_carries_caller_supplied_source_name_not_a_hardcoded_provider(self, tmp_path) -> None:
        _write_csv(
            tmp_path / "AAA.csv",
            [{"date": "2010-06-15", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100", "adj_close": "1.4"}],
        )
        config = FileImportConfig(source_name="nasdaq_data_link_sharadar", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        raw = provider.fetch("AAA", utc(2010, 1, 1), utc(2010, 12, 31))
        [bar] = provider.normalize("AAA", raw)
        assert bar.provenance.source == "nasdaq_data_link_sharadar"
        assert bar.adjusted_close == pytest.approx(1.4)
        assert bar.close == pytest.approx(1.5)

    def test_normalize_parses_adj_high_and_adj_low_columns(self, tmp_path) -> None:
        _write_csv(
            tmp_path / "AAA.csv",
            [{"date": "2010-06-15", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100",
              "adj_close": "1.4", "adj_high": "1.9", "adj_low": "0.45"}],
            columns=("date", "open", "high", "low", "close", "volume", "adj_close", "adj_high", "adj_low"),
        )
        config = FileImportConfig(source_name="test_source", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        raw = provider.fetch("AAA", utc(2010, 1, 1), utc(2010, 12, 31))
        [bar] = provider.normalize("AAA", raw)
        assert bar.high == pytest.approx(2.0)  # raw, unadjusted -- never overwritten
        assert bar.adjusted_high == pytest.approx(1.9)
        assert bar.adjusted_low == pytest.approx(0.45)

    def test_missing_adj_close_leaves_adjusted_close_none_not_fabricated(self, tmp_path) -> None:
        _write_csv(
            tmp_path / "AAA.csv",
            [{"date": "2010-06-15", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "100", "adj_close": ""}],
        )
        config = FileImportConfig(source_name="test_source", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        raw = provider.fetch("AAA", utc(2010, 1, 1), utc(2010, 12, 31))
        [bar] = provider.normalize("AAA", raw)
        assert bar.adjusted_close is None

    def test_metadata_declares_local_file_import_honestly(self, tmp_path) -> None:
        config = FileImportConfig(source_name="crsp", data_dir=tmp_path)
        provider = LocalFileDataProvider(config)
        meta = provider.metadata()
        assert meta["provider_name"] == "crsp"
        assert meta["is_local_file_import"] is True
        assert meta["is_real_external_provider"] is True
        assert meta["rate_limit_per_minute"] is None


class TestFileImportEndToEndPipeline:
    """Real integration test: real CSV files -> real IngestionRunner ->
    real DataQualityFramework -> real on-disk DuckDB -> real
    point-in-time query. No network call anywhere in this class."""

    def test_full_pipeline_ingests_and_persists_real_bars_from_local_csv(self, tmp_path) -> None:
        data_dir = tmp_path / "external_data"
        data_dir.mkdir()
        _write_csv(
            data_dir / "AAA.csv",
            [
                {"date": "2010-01-04", "open": "10", "high": "11", "low": "9.5", "close": "10.5", "volume": "1000", "adj_close": "10.5"},
                {"date": "2010-01-05", "open": "10.5", "high": "11.5", "low": "10", "close": "11", "volume": "1100", "adj_close": "11"},
            ],
        )
        _write_csv(
            data_dir / "BBB.csv",
            [
                {"date": "2010-01-04", "open": "50", "high": "51", "low": "49", "close": "50.5", "volume": "500", "adj_close": "50.5"},
            ],
        )

        config = FileImportConfig(source_name="test_external_source", data_dir=data_dir)
        provider = LocalFileDataProvider(config)

        engine = StorageEngine(StorageConfig(root_dir=tmp_path / "store"))
        try:
            repository = DuckDBDataRepository(engine)
            runner = IngestionRunner(provider, repository)
            result = runner.run(["AAA", "BBB"], utc(2010, 1, 1), utc(2010, 1, 31))

            assert result.status == IngestionStatus.SUCCESS
            assert {r.security_id: r.status for r in result.results} == {
                "AAA": IngestionStatus.SUCCESS,
                "BBB": IngestionStatus.SUCCESS,
            }

            aaa_bars = repository.get_bars("AAA", utc(2010, 1, 1), utc(2010, 1, 31), as_of_time=utc(2010, 1, 31))
            bbb_bars = repository.get_bars("BBB", utc(2010, 1, 1), utc(2010, 1, 31), as_of_time=utc(2010, 1, 31))
            assert len(aaa_bars) == 2
            assert len(bbb_bars) == 1
            assert all(b.provenance.source == "test_external_source" for b in aaa_bars + bbb_bars)

            quality = DataQualityFramework()
            run = quality.run(aaa_bars + bbb_bars, dataset="phase31_file_import_test", data_version="test-run")
            assert run.status.value in ("PASSED", "PASSED_WITH_WARNINGS")
        finally:
            engine.close()

    def test_missing_symbol_is_reported_failed_not_silently_skipped(self, tmp_path) -> None:
        data_dir = tmp_path / "external_data"
        data_dir.mkdir()
        _write_csv(
            data_dir / "AAA.csv",
            [{"date": "2010-01-04", "open": "10", "high": "11", "low": "9.5", "close": "10.5", "volume": "1000", "adj_close": "10.5"}],
        )
        config = FileImportConfig(source_name="test_external_source", data_dir=data_dir)
        provider = LocalFileDataProvider(config)

        engine = StorageEngine(StorageConfig(root_dir=tmp_path / "store"))
        try:
            repository = DuckDBDataRepository(engine)
            runner = IngestionRunner(provider, repository)
            result = runner.run(["AAA", "MISSING_SYMBOL"], utc(2010, 1, 1), utc(2010, 1, 31))

            statuses = {r.security_id: r.status for r in result.results}
            assert statuses["AAA"] == IngestionStatus.SUCCESS
            assert statuses["MISSING_SYMBOL"] == IngestionStatus.FAILED
            assert result.status == IngestionStatus.PARTIAL_SUCCESS
        finally:
            engine.close()

    def test_reingesting_the_identical_file_is_idempotent(self, tmp_path) -> None:
        data_dir = tmp_path / "external_data"
        data_dir.mkdir()
        _write_csv(
            data_dir / "AAA.csv",
            [{"date": "2010-01-04", "open": "10", "high": "11", "low": "9.5", "close": "10.5", "volume": "1000", "adj_close": "10.5"}],
        )
        config = FileImportConfig(source_name="test_external_source", data_dir=data_dir)
        provider = LocalFileDataProvider(config)

        engine = StorageEngine(StorageConfig(root_dir=tmp_path / "store"))
        try:
            repository = DuckDBDataRepository(engine)
            IngestionRunner(provider, repository).run(["AAA"], utc(2010, 1, 1), utc(2010, 1, 31))
            # A second, independent IngestionRunner instance against the
            # SAME repository (Phase 1 spec section 25 idempotency).
            IngestionRunner(provider, repository).run(["AAA"], utc(2010, 1, 1), utc(2010, 1, 31))

            bars = repository.get_bars("AAA", utc(2010, 1, 1), utc(2010, 1, 31), as_of_time=utc(2010, 1, 31))
            assert len(bars) == 1  # not duplicated
        finally:
            engine.close()
