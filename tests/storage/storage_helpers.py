"""Shared test helpers for the Phase 4 persistent storage test suite."""

from __future__ import annotations

from pathlib import Path

from storage.config import StorageConfig
from storage.engine import StorageEngine


def new_engine(tmp_path: Path, name: str = "store") -> StorageEngine:
    return StorageEngine(StorageConfig(tmp_path / name))
