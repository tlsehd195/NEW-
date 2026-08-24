"""Data versioning: content-hash based data_version computation and the
DatasetVersion record.

See docs/specifications/PHASE-1-data-infrastructure.md section 9 and
ADR-0003.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


def compute_data_version(payload: Mapping[str, Any]) -> str:
    """Deterministic content hash for a record payload.

    Two ingestion runs that fetch identical content must produce an
    identical data_version, and any real content change must produce a
    different one — this holds regardless of whether the upstream
    provider exposes its own versioning (Phase 1 spec section 9).
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DatasetVersion:
    dataset_id: str
    dataset_version: str
    schema_version: int
    created_at: datetime
    source_version: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("DatasetVersion.created_at must be timezone-aware")
        if not self.dataset_id or not self.dataset_version:
            raise ValueError("DatasetVersion requires non-empty dataset_id and dataset_version")
