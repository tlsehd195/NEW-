"""StorageEngine: owns the single DuckDB connection/file used by every
persistent repository in this package.

See docs/specifications/PHASE-4-baseline-models-and-storage.md section 3.
Opening the same ``StorageConfig.duckdb_path`` again after a process
restart reopens the existing file and re-runs the (idempotent) schema DDL
-- it never recreates or truncates existing tables (restart safety,
Phase 4 spec section 8).

DuckDB is a single-process embedded engine (ADR-0002's already-accepted
concurrency limitation): only one ``StorageEngine`` should hold a
read/write connection to a given ``duckdb_path`` at a time. Call
``close()`` (or use the context-manager form) before opening a second
engine against the same path, matching how a real deployment would only
ever run one ingestion/backtest process at a time in this phase.
"""

from __future__ import annotations

from typing import Optional

import duckdb

from storage.config import StorageConfig
from storage.schema import init_schema


class StorageEngine:
    def __init__(self, config: StorageConfig, *, read_only: bool = False) -> None:
        self._config = config
        config.ensure_dirs()
        self._connection: Optional[duckdb.DuckDBPyConnection] = duckdb.connect(
            str(config.duckdb_path), read_only=read_only
        )
        if not read_only:
            init_schema(self._connection)

    @property
    def config(self) -> StorageConfig:
        return self._config

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._connection is None:
            raise RuntimeError("StorageEngine is closed")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "StorageEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
