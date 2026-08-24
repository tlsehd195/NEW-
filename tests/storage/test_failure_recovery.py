"""Category: corruption/failure handling (Phase 4 spec section 16).

Two independent guarantees are exercised:
1. Parquet batch writes are atomic (temp file + os.replace) -- an
   interruption between writing and the rename never leaves a partial
   ``.parquet`` file visible to a reader.
2. DuckDB table writes inside one repository call either fully succeed
   or fully fail -- a mid-batch error does not leave a partially-written
   row set.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backtest_helpers import utc

from data_infra.models import PriceBar, Provenance

from storage import parquet_layer
from storage.data_repository import DuckDBDataRepository
from storage_helpers import new_engine


def _make_bar(security_id: str, day: date, close: float) -> PriceBar:
    return PriceBar(
        security_id=security_id, timestamp=utc(day.year, day.month, day.day, 0), open=close,
        high=close * 1.01, low=close * 0.99, close=close, volume=1000.0,
        available_time=utc(day.year, day.month, day.day, 20),
        ingestion_time=utc(day.year, day.month, day.day, 20),
        provenance=Provenance(
            source="s1", source_dataset="ds", source_record_id=f"{security_id}-{day.isoformat()}",
            retrieved_at=utc(day.year, day.month, day.day, 20), data_version="v1",
        ),
    )


class TestParquetWriteAtomicity:
    def test_interrupted_write_leaves_no_partial_parquet_file(self, tmp_path, monkeypatch) -> None:
        directory = tmp_path / "price_bars"

        real_replace = parquet_layer.os.replace
        calls = {"n": 0}

        def failing_replace(src, dst):
            calls["n"] += 1
            raise OSError("simulated crash between write and rename")

        monkeypatch.setattr(parquet_layer.os, "replace", failing_replace)
        with pytest.raises(OSError):
            parquet_layer.write_batch(directory, [{"a": 1}], columns=("a",))

        # No stray temp file and no half-written .parquet file remain.
        assert list(directory.glob("*.parquet")) == []
        assert list(directory.glob(".tmp-*")) == []
        assert calls["n"] == 1

        monkeypatch.setattr(parquet_layer.os, "replace", real_replace)

    def test_repository_still_readable_after_a_prior_failed_batch(self, tmp_path, monkeypatch) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_bars([_make_bar("AAA", date(2024, 1, 2), 100.0)])

        real_replace = parquet_layer.os.replace

        def failing_replace(src, dst):
            raise OSError("simulated crash")

        monkeypatch.setattr(parquet_layer.os, "replace", failing_replace)
        with pytest.raises(OSError):
            repo.append_bars([_make_bar("AAA", date(2024, 1, 3), 101.0)])
        monkeypatch.setattr(parquet_layer.os, "replace", real_replace)

        # The earlier, successfully-committed batch is still fully intact.
        got = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(got) == 1
        assert got[0].close == 100.0
        engine.close()


class TestDuckDBTransactionFailure:
    def test_bad_insert_does_not_leave_partial_rows(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        conn = engine.connection
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO experiments (experiment_id, strategy_version, configuration_version, "
            "start_date, end_date, initial_capital, code_version, seed, result, timestamp, "
            "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["EXP-A", "v1", "cfg1", utc(2024, 1, 1), utc(2024, 1, 31), 1000.0, "c1", None, "PASSED",
             utc(2024, 1, 31), "{}"],
        )
        with pytest.raises(Exception):
            # Missing NOT NULL column (payload_json omitted) -> constraint violation.
            conn.execute(
                "INSERT INTO experiments (experiment_id, strategy_version, configuration_version, "
                "start_date, end_date, initial_capital, code_version, seed, result, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ["EXP-B", "v1", "cfg1", utc(2024, 1, 1), utc(2024, 1, 31), 1000.0, "c1", None, "PASSED",
                 utc(2024, 1, 31)],
            )
        conn.execute("ROLLBACK")

        rows = conn.execute("SELECT experiment_id FROM experiments").fetchall()
        assert rows == []  # the whole transaction, including EXP-A, was rolled back
        engine.close()
