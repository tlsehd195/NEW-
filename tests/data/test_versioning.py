"""Category 12: Data version test.

See docs/specifications/PHASE-1-data-infrastructure.md section 9 and
ADR-0003.
"""

from __future__ import annotations

import pytest
from helpers import utc

from data_infra.versioning import DatasetVersion, compute_data_version


class TestDataVersion:
    def test_identical_content_yields_identical_version(self) -> None:
        payload_a = {"security_id": "SEC-AAA", "close": 102.0, "timestamp": utc(2024, 1, 2)}
        payload_b = {"security_id": "SEC-AAA", "close": 102.0, "timestamp": utc(2024, 1, 2)}
        assert compute_data_version(payload_a) == compute_data_version(payload_b)

    def test_key_order_does_not_affect_version(self) -> None:
        payload_a = {"a": 1, "b": 2, "c": 3}
        payload_b = {"c": 3, "a": 1, "b": 2}
        assert compute_data_version(payload_a) == compute_data_version(payload_b)

    def test_changed_content_yields_different_version(self) -> None:
        payload_a = {"security_id": "SEC-AAA", "close": 102.0}
        payload_b = {"security_id": "SEC-AAA", "close": 102.5}  # restated close
        assert compute_data_version(payload_a) != compute_data_version(payload_b)

    def test_dataset_version_requires_timezone_aware_created_at(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError):
            DatasetVersion(
                dataset_id="mock_ohlcv_us_equity",
                dataset_version="v1",
                schema_version=1,
                created_at=datetime(2024, 1, 1),  # naive
                source_version="mock_provider_v1",
            )

    def test_dataset_version_valid_construction(self) -> None:
        version = DatasetVersion(
            dataset_id="mock_ohlcv_us_equity",
            dataset_version=compute_data_version({"n": 1}),
            schema_version=1,
            created_at=utc(2024, 1, 1),
            source_version="mock_provider_v1",
        )
        assert version.dataset_id == "mock_ohlcv_us_equity"
