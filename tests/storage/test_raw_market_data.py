"""Category: Raw Market Data persistence, provenance, immutability
(Phase 4 spec section 5, 7 -- Raw Data is kept distinct from Clean Data
and is never rewritten in place, mirroring Phase 1 spec section 17
applied to the persistent backend)."""

from __future__ import annotations

from datetime import date

from backtest_helpers import utc

from storage.data_repository import DuckDBDataRepository
from storage_helpers import new_engine


class TestRawMarketData:
    def test_raw_payloads_persist_verbatim(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        raw = [
            {"security_id": "AAA", "timestamp": "2024-01-02", "close": 100.0, "vendor_field": "xyz"},
            {"security_id": "AAA", "timestamp": "2024-01-03", "close": 101.0, "vendor_field": "abc"},
        ]
        path = repo.append_raw_payloads("AAA", "mock_provider_v1", raw, ingestion_time=utc(2024, 1, 3, 20))
        assert path is not None and path.exists()

        got = repo.get_raw_payloads("AAA")
        assert len(got) == 2
        assert got[0]["payload"]["vendor_field"] == "xyz"
        assert got[1]["payload"]["vendor_field"] == "abc"
        assert all(r["source"] == "mock_provider_v1" for r in got)
        engine.close()

    def test_raw_payloads_survive_restart(self, tmp_path) -> None:
        from storage.config import StorageConfig
        from storage.engine import StorageEngine

        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        repo1 = DuckDBDataRepository(engine1)
        repo1.append_raw_payloads("AAA", "src1", [{"a": 1}], ingestion_time=utc(2024, 1, 2, 20))
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBDataRepository(engine2)
        assert len(repo2.get_raw_payloads("AAA")) == 1
        engine2.close()

    def test_two_ingestion_runs_of_identical_content_both_retained(self, tmp_path) -> None:
        """Raw is a record of what was received and when -- re-ingesting
        identical content is not deduplicated the way Clean-layer bars
        are (Phase 4 spec section 5); each ingestion run is its own,
        separately timestamped, immutable batch."""
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        raw = [{"security_id": "AAA", "close": 100.0}]
        repo.append_raw_payloads("AAA", "src1", raw, ingestion_time=utc(2024, 1, 2, 20))
        repo.append_raw_payloads("AAA", "src1", raw, ingestion_time=utc(2024, 1, 3, 20))
        got = repo.get_raw_payloads("AAA")
        assert len(got) == 2
        assert {r["ingestion_time"] for r in got} == {utc(2024, 1, 2, 20), utc(2024, 1, 3, 20)}
        engine.close()

    def test_raw_ingestion_batches_manifest_is_queryable(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_raw_payloads("AAA", "src1", [{"a": 1}, {"a": 2}], ingestion_time=utc(2024, 1, 2, 20))
        rows = engine.connection.execute(
            "SELECT security_id, source, record_count FROM raw_ingestion_batches"
        ).fetchall()
        assert rows == [("AAA", "src1", 2)]
        engine.close()

    def test_raw_and_clean_are_kept_in_separate_datasets(self, tmp_path) -> None:
        """Appending Clean-layer bars must never touch the Raw parquet
        directory, and vice versa -- the two layers are structurally
        distinct storage locations, not merely a logical label on one
        dataset."""
        from data_infra.models import PriceBar, Provenance

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_raw_payloads("AAA", "src1", [{"a": 1}], ingestion_time=utc(2024, 1, 2, 20))

        bar = PriceBar(
            security_id="AAA", timestamp=utc(2024, 1, 2, 0), open=100, high=101, low=99, close=100,
            volume=1000.0, available_time=utc(2024, 1, 2, 20), ingestion_time=utc(2024, 1, 2, 20),
            provenance=Provenance(
                source="src1", source_dataset="ds", source_record_id="AAA-2024-01-02",
                retrieved_at=utc(2024, 1, 2, 20), data_version="v1",
            ),
        )
        repo.append_bars([bar])

        assert (engine.config.parquet_dir / "raw_market_data").exists()
        assert (engine.config.parquet_dir / "price_bars").exists()
        raw_files = list((engine.config.parquet_dir / "raw_market_data").glob("*.parquet"))
        clean_files = list((engine.config.parquet_dir / "price_bars").glob("*.parquet"))
        assert len(raw_files) == 1
        assert len(clean_files) == 1
        engine.close()
