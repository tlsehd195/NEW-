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

    def test_append_after_a_read_is_not_served_stale_from_cache(self, tmp_path) -> None:
        """Regression guard for the per-security in-memory cache in
        `_bars_for_security`: a `get_bars` call must not permanently
        pin a security's cached bar list -- a later `append_bars` for
        that same security, on the same repository instance, has to
        invalidate the cache so the next `get_bars` sees the new bar."""
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_bars([make_bar("AAA", date(2024, 1, 2), 100.0)])
        first = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(first) == 1  # populates the cache

        repo.append_bars([make_bar("AAA", date(2024, 1, 3), 101.0)])
        second = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(second) == 2  # must reflect the append, not the stale cached pair
        engine.close()

    def test_corporate_action_after_a_read_is_not_served_stale_from_cache(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        first = repo.get_corporate_actions("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert first == []  # populates the (empty) cache

        repo.add_corporate_action(make_split("AAA", date(2024, 1, 5)))
        second = repo.get_corporate_actions("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(second) == 1
        engine.close()

    def test_cache_is_scoped_per_security_not_shared(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_bars([make_bar("AAA", date(2024, 1, 2), 100.0)])
        repo.append_bars([make_bar("BBB", date(2024, 1, 2), 200.0)])

        aaa = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        bbb = repo.get_bars("BBB", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert [b.security_id for b in aaa] == ["AAA"]
        assert [b.security_id for b in bbb] == ["BBB"]

        # Appending only to AAA must not invalidate or otherwise affect
        # BBB's already-cached (and still correct) result.
        repo.append_bars([make_bar("AAA", date(2024, 1, 3), 101.0)])
        bbb_again = repo.get_bars("BBB", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(bbb_again) == 1
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


class TestPriceBarSchemaEvolution:
    """Session 36 continued -- `adjusted_high`/`adjusted_low` were added
    to `PriceBar`/`PRICE_BAR_COLUMNS` this session. A Parquet file
    written by an EARLIER version of this code (before those two
    columns existed) has a genuinely different Arrow schema, not just
    NULLs in those columns -- proves `union_by_name=true` (added to
    every `read_parquet(...)` call in `data_repository.py` alongside
    this column addition) lets that old file and a newly-written one
    coexist in the same glob without error, so an account owner's
    already-ingested real data is never broken by this additive schema
    change."""

    @staticmethod
    def _write_old_schema_parquet_file(price_bars_dir, bar: PriceBar) -> None:
        """Writes one bar using the OLD (pre-this-session) column set --
        `PRICE_BAR_COLUMNS` minus `adjusted_high`/`adjusted_low` --
        simulating a real file already on disk from before this
        session's schema change."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        from storage.serialization import PRICE_BAR_COLUMNS, price_bar_to_row

        old_columns = tuple(c for c in PRICE_BAR_COLUMNS if c not in ("adjusted_high", "adjusted_low"))
        row = price_bar_to_row(bar)
        table = pa.Table.from_pylist([{c: row.get(c) for c in old_columns}])
        price_bars_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, price_bars_dir / "part-old-schema.parquet")

    def test_old_schema_file_and_new_schema_file_coexist_via_union_by_name(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        price_bars_dir = engine.config.parquet_dir / "price_bars"

        old_bar = make_bar("AAA", date(2024, 1, 2), 100.0)
        self._write_old_schema_parquet_file(price_bars_dir, old_bar)

        new_bar = PriceBar(
            security_id="AAA", timestamp=utc(2024, 1, 3), open=101.0, high=102.0, low=100.0, close=101.5,
            volume=1_000.0, available_time=utc(2024, 1, 3, 20), ingestion_time=utc(2024, 1, 3, 20),
            provenance=Provenance(
                source="s1", source_dataset="ds", source_record_id="AAA-2024-01-03",
                retrieved_at=utc(2024, 1, 3, 20), data_version="v1",
            ),
            adjusted_high=51.0, adjusted_low=50.0,
        )
        assert repo.append_bars([new_bar]) == 1

        got = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert [b.close for b in got] == [100.0, 101.5]
        # The old file's bar never had these columns at all -- reads back None, not an error.
        assert got[0].adjusted_high is None
        assert got[0].adjusted_low is None
        # The new file's bar keeps its real values.
        assert got[1].adjusted_high == 51.0
        assert got[1].adjusted_low == 50.0

        all_bars = repo.all_bars()
        assert len(all_bars) == 2
        engine.close()


class TestRawBatchIdRestartSafety:
    """Session 37 (ADR-0115, external review, previously-remaining
    MEDIUM): `raw_ingestion_batches.batch_id` is a PRIMARY KEY with no
    `ON CONFLICT` handling -- before this fix, `_next_raw_batch_id`
    always restarted at 1 for a fresh `DuckDBDataRepository` instance,
    so the first `append_raw_payloads()` call after a restart collided
    with an already-persisted "RAW-000001" and crashed outright (a real
    PK violation), rather than merely losing data silently. Mirrors the
    `advance_past`/`starting_id` restart-safe pattern (ADR-0073) already
    established for every other id allocator in this codebase."""

    def test_append_raw_payloads_after_restart_does_not_crash_on_a_pk_collision(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        repo1 = DuckDBDataRepository(engine1)
        path1 = repo1.append_raw_payloads("AAA", "s1", [{"a": 1}], ingestion_time=utc(2024, 1, 2, 20))
        assert path1 is not None
        engine1.close()

        engine2 = new_engine(tmp_path)
        repo2 = DuckDBDataRepository(engine2)
        # The bug: without the fix, this raises a PRIMARY KEY violation
        # (both processes' first batch_id is "RAW-000001").
        path2 = repo2.append_raw_payloads("BBB", "s1", [{"b": 2}], ingestion_time=utc(2024, 1, 3, 20))
        assert path2 is not None

        aaa_payloads = repo2.get_raw_payloads("AAA")
        bbb_payloads = repo2.get_raw_payloads("BBB")
        assert len(aaa_payloads) == 1
        assert len(bbb_payloads) == 1
        assert aaa_payloads[0]["batch_id"] != bbb_payloads[0]["batch_id"]
        engine2.close()

    def test_next_batch_id_is_seeded_past_the_highest_persisted_one(self, tmp_path) -> None:
        engine1 = new_engine(tmp_path)
        repo1 = DuckDBDataRepository(engine1)
        for i in range(3):
            repo1.append_raw_payloads(f"SEC{i}", "s1", [{"i": i}], ingestion_time=utc(2024, 1, 2, 20))
        engine1.close()

        engine2 = new_engine(tmp_path)
        repo2 = DuckDBDataRepository(engine2)
        assert repo2._next_raw_batch_id == 4
        engine2.close()
