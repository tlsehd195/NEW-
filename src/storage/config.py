"""Storage location configuration.

See docs/specifications/PHASE-4-baseline-models-and-storage.md section 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageConfig:
    """Where the persistent storage layer keeps its files.

    ``root_dir`` is created (including parents) on first use if it does
    not already exist. A single DuckDB catalog file holds every
    relational/metadata table (Phase 4 spec section 4); a ``parquet/``
    subdirectory holds the append-only Raw/Clean market data batches.
    """

    root_dir: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_dir", Path(self.root_dir))

    @property
    def duckdb_path(self) -> Path:
        return self.root_dir / "catalog.duckdb"

    @property
    def parquet_dir(self) -> Path:
        return self.root_dir / "parquet"

    def ensure_dirs(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
