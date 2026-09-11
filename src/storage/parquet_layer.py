"""Append-only Parquet storage for high-volume time-series data (Raw and
Clean market data -- PriceBar).

See docs/specifications/PHASE-4-baseline-models-and-storage.md section 4
and ADR-0010. Every batch is written to its own file, named with a
monotonically increasing sequence + uuid so concurrent-looking names never
collide; no file is ever opened for append or rewritten in place --
"new data" always means "a new file" (Raw Data Immutability, Phase 1 spec
section 17, applied here to the persistent backend).

Failure handling: each batch is written to a temporary file in the same
directory and then atomically renamed (``os.replace``) into place. A
crash/exception between the write and the rename leaves at most a stray
``*.tmp-*`` file that no reader ever globs (readers only glob
``*.parquet``) -- never a half-written ``.parquet`` file that a query
could pick up mid-write (Phase 4 spec section 8, "corruption/failure
handling").
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq


def write_batch(directory: Path, rows: Sequence[dict], *, columns: Sequence[str]) -> Path:
    """Writes ``rows`` (each a flat dict keyed by ``columns``) as one new,
    immutable Parquet file under ``directory``. Returns the final path.
    An empty ``rows`` is NOT a no-op here -- it still writes a real,
    empty Parquet file and returns its path (ADR-0117 correction; this
    docstring previously, incorrectly, claimed it skips). Every real
    caller in this codebase (``storage.data_repository.append_bars``/
    ``append_raw_payloads``) already guards against calling this with
    an empty ``rows`` itself, so the discrepancy has never actually
    been reachable in production -- but a future caller relying on
    this docstring's old claim would get a spurious empty file on
    disk, not the no-op it expected."""
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([{c: row.get(c) for c in columns} for row in rows])

    final_name = f"part-{uuid.uuid4().hex}.parquet"
    final_path = directory / final_name

    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".parquet", dir=str(directory))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, final_path)  # atomic on the same filesystem
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return final_path


def existing_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.parquet"))


def glob_pattern(directory: Path) -> str:
    return str(directory / "*.parquet")
