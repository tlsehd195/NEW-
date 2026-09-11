"""Category: Unit Test -- storage.parquet_layer.write_batch's actual
empty-batch behavior (ADR-0117: the module's own docstring previously,
incorrectly, claimed an empty batch is a no-op; it is not)."""

from __future__ import annotations

from storage.parquet_layer import write_batch


class TestEmptyBatchBehavior:
    def test_an_empty_batch_still_writes_a_real_empty_parquet_file(self, tmp_path) -> None:
        path = write_batch(tmp_path, [], columns=["a", "b"])
        assert path.exists()
        assert path.suffix == ".parquet"

    def test_a_nonempty_batch_writes_the_real_rows(self, tmp_path) -> None:
        import pyarrow.parquet as pq

        path = write_batch(tmp_path, [{"a": 1, "b": 2}], columns=["a", "b"])
        table = pq.read_table(path)
        assert table.num_rows == 1
