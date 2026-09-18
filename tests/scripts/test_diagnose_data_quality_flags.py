"""Real, executable tests for `scripts/diagnose_data_quality_flags.py`
(external review, account owner, 2026-09-18: a real run reported 866
ERROR-severity data quality issues with only the aggregate count
visible). Makes no network call -- seeds real `data_quality_flags` rows
via `DuckDBDataRepository.record_quality_issues` and runs `main()` end
to end, mirroring `tests/scripts/test_export_paper_store_backup.py`'s
own precedent for a network-free script."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

from data_infra.enums import DataQualityRunStatus, DataQualitySeverity
from data_infra.quality import DataQualityIssue, DataQualityRun

from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "diagnose_data_quality_flags.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("diagnose_data_quality_flags", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _utc(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _seed_flags(db_path: Path) -> None:
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    repository = DuckDBDataRepository(engine)
    quality_run = DataQualityRun(
        validation_id="TEST-VALIDATION-1",
        dataset="test_dataset",
        data_version="v1",
        timestamp=_utc(2024, 1, 1),
        status=DataQualityRunStatus.FAILED,
        checks=("ohlc_consistency", "negative_or_zero_price"),
        issues=(
            DataQualityIssue(
                check="ohlc_consistency", severity=DataQualitySeverity.ERROR,
                message="OHLC invariant violated for AAA", security_id="AAA", timestamp=_utc(2024, 1, 2),
            ),
            DataQualityIssue(
                check="ohlc_consistency", severity=DataQualitySeverity.ERROR,
                message="OHLC invariant violated for AAA", security_id="AAA", timestamp=_utc(2024, 1, 3),
            ),
            DataQualityIssue(
                check="negative_or_zero_price", severity=DataQualitySeverity.ERROR,
                message="Non-positive price for BBB", security_id="BBB", timestamp=_utc(2024, 1, 2),
            ),
            DataQualityIssue(
                check="stale_data", severity=DataQualitySeverity.WARNING,
                message="Stale data for CCC", security_id="CCC", timestamp=_utc(2024, 1, 2),
            ),
        ),
    )
    repository.record_quality_issues(quality_run)
    engine.close()


class TestDiagnoseDataQualityFlags:
    def test_reports_per_check_and_per_security_breakdown(self, tmp_path, capsys) -> None:
        db_path = tmp_path / "market_data"
        _seed_flags(db_path)
        module = _load_module()

        exit_code = module.main(["--db-path", str(db_path)])
        assert exit_code == 0

        out = capsys.readouterr().out
        assert "Total data_quality_flags rows in this catalog: 4" in out
        assert "ERROR: 3" in out
        assert "WARNING: 1" in out
        assert "ohlc_consistency [ERROR]: 2" in out
        assert "negative_or_zero_price [ERROR]: 1" in out
        assert "AAA: 2" in out  # the security with the most ERROR flags
        assert "OHLC invariant violated for AAA" in out  # a real sample message

    def test_missing_db_path_fails_cleanly(self, tmp_path) -> None:
        module = _load_module()
        missing = tmp_path / "does_not_exist"
        assert module.main(["--db-path", str(missing)]) == 1

    def test_empty_catalog_does_not_crash(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        engine = StorageEngine(StorageConfig(root_dir=db_path))
        engine.close()
        module = _load_module()
        assert module.main(["--db-path", str(db_path)]) == 0
