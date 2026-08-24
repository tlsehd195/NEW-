"""Category: persistence, restart recovery, append, duplicate/idempotency
(Phase 4 spec section 16, Storage).

Exercises DuckDBDataRepository against the same look-ahead-guard /
as-of-query / survivorship invariants Phase 1's InMemoryDataRepository
already guarantees (ADR-0002: "must satisfy the exact same Protocol"),
plus restart-safety, which InMemoryDataRepository cannot have by
definition.
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import (
    make_benchmark,
    make_membership,
    make_security,
    make_split,
    trading_days,
    utc,
)

from data_infra.models import PriceBar, Provenance

from storage.data_repository import DuckDBDataRepository
from storage.config import StorageConfig
from storage.engine import StorageEngine

from storage_helpers import new_engine


def make_bar(security_id: str, day: date, close: float, *, source: str = "s1", data_version: str = "v1") -> PriceBar:
    return PriceBar(
        security_id=security_id,
        timestamp=utc(day.year, day.month, day.day, 0),
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=1_000.0,
        available_time=utc(day.year, day.month, day.day, 20),
        ingestion_time=utc(day.year, day.month, day.day, 20),
        provenance=Provenance(
            source=source, source_dataset="ds", source_record_id=f"{security_id}-{day.isoformat()}",
            retrieved_at=utc(day.year, day.month, day.day, 20), data_version=data_version,
        ),
    )


class TestPersistenceAndRestart:
    def test_bars_survive_engine_restart(self, tmp_path) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 10))
        config = StorageConfig(tmp_path / "store")

        engine1 = StorageEngine(config)
        repo1 = DuckDBDataRepository(engine1)
        bars = [make_bar("AAA", d, 100.0 + i) for i, d in enumerate(days)]
        written = repo1.append_bars(bars)
        assert written == len(bars)
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBDataRepository(engine2)
        got = repo2.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(got) == len(bars)
        assert [b.close for b in got] == [100.0 + i for i in range(len(days))]
        engine2.close()

    def test_metadata_tables_survive_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        repo1 = DuckDBDataRepository(engine1)
        repo1.add_security(make_security("AAA", "AAA"))
        repo1.add_universe_membership(make_membership("AAA", utc(2020, 1, 1)))
        for point in make_benchmark([date(2024, 1, 2)], [4000.0]):
            repo1.add_benchmark_point(point)
        repo1.add_corporate_action(make_split("AAA", date(2024, 1, 5)))
        engine1.close()

        engine2 = StorageEngine(config)
        repo2 = DuckDBDataRepository(engine2)
        assert repo2.get_security("AAA", utc(2024, 6, 1)) is not None
        assert "AAA" in repo2.get_universe("US", "SP500", utc(2024, 6, 1))
        assert len(repo2.get_benchmark("SP500", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))) == 1
        actions = repo2.get_corporate_actions("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(actions) == 1
        engine2.close()

    def test_append_is_idempotent_on_natural_key(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        bars = [make_bar("AAA", date(2024, 1, 2), 100.0)]
        assert repo.append_bars(bars) == 1
        assert repo.append_bars(bars) == 0  # duplicate ingestion -> no new rows
        assert len(repo.all_bars()) == 1
        engine.close()

    def test_duplicate_ingestion_across_two_batches_still_deduplicates(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        bar = make_bar("AAA", date(2024, 1, 2), 100.0)
        repo.append_bars([bar])
        # A second batch containing the same bar plus a genuinely new one.
        bar2 = make_bar("AAA", date(2024, 1, 3), 101.0)
        written = repo.append_bars([bar, bar2])
        assert written == 1  # only the new bar was written
        assert len(repo.all_bars()) == 2
        engine.close()

    def test_append_creates_new_immutable_file_never_rewrites(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_bars([make_bar("AAA", date(2024, 1, 2), 100.0)])
        files_after_first = set((engine.config.parquet_dir / "price_bars").glob("*.parquet"))
        repo.append_bars([make_bar("AAA", date(2024, 1, 3), 101.0)])
        files_after_second = set((engine.config.parquet_dir / "price_bars").glob("*.parquet"))
        assert files_after_first.issubset(files_after_second)
        assert len(files_after_second) == len(files_after_first) + 1
        engine.close()

    def test_lookahead_guard_excludes_future_available_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        bar = make_bar("AAA", date(2024, 1, 5), 100.0)
        repo.append_bars([bar])
        as_of_before_available = utc(2024, 1, 5, 10)  # before the 20:00 available_time
        got = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=as_of_before_available)
        assert got == []
        as_of_after_available = utc(2024, 1, 5, 21)
        got2 = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=as_of_after_available)
        assert len(got2) == 1
        engine.close()

    def test_survivorship_query_differs_by_as_of_time(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.add_universe_membership(make_membership("AAA", utc(2020, 1, 1), utc(2024, 6, 1)))
        repo.add_universe_membership(make_membership("BBB", utc(2024, 6, 1)))
        before = repo.get_universe("US", "SP500", utc(2024, 1, 1))
        after = repo.get_universe("US", "SP500", utc(2024, 7, 1))
        assert before == ["AAA"]
        assert after == ["BBB"]
        engine.close()
