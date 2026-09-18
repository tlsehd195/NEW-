"""Real, executable tests for
`scripts/repair_ingestion_time_inversions.py` (ADR-0168 -- the confirmed
root cause of the real `ingestion_precedes_availability` ERROR backlog:
bars ingested before ADR-0115's `clamp_ingestion_time` fix existed).
Makes no network call -- seeds a real catalog via
`DuckDBDataRepository.append_bars` and runs `main()` end to end,
mirroring `tests/scripts/test_diagnose_data_quality_flags.py`'s own
precedent for a network-free script."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

from backtest_helpers import utc

from data_infra.models import PriceBar, Provenance

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_ingestion_time_inversions.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("repair_ingestion_time_inversions", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _inverted_bar(security_id: str) -> PriceBar:
    """A bar with ingestion_time BEFORE its own available_time -- the
    exact, structurally-impossible-going-forward defect ADR-0115's
    clamp_ingestion_time prevents for any new ingestion, but which
    already-persisted pre-fix bars can still carry."""
    timestamp = utc(2024, 1, 2)
    available_time = utc(2024, 1, 2, 20)
    return PriceBar(
        security_id=security_id, timestamp=timestamp, open=100.0, high=101.0, low=99.0, close=100.5,
        volume=1_000.0, available_time=available_time,
        ingestion_time=utc(2024, 1, 2, 0),  # midnight -- before the 20:00 available_time
        provenance=Provenance(
            source="tiingo", source_dataset="ds", source_record_id=f"{security_id}-2024-01-02",
            retrieved_at=utc(2024, 1, 2, 0), data_version="v1",
        ),
    )


def _seed(db_path: Path, bars: list[PriceBar]) -> None:
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    DuckDBDataRepository(engine).append_bars(bars)
    engine.close()


class TestRepairIngestionTimeInversions:
    def test_dry_run_reports_but_does_not_write(self, tmp_path, capsys) -> None:
        db_path = tmp_path / "market_data"
        _seed(db_path, [_inverted_bar("AAA")])
        module = _load_module()

        exit_code = module.main(["--db-path", str(db_path)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Found 1 bar(s)" in out
        assert "Dry run only" in out

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repo = DuckDBDataRepository(engine)
        assert len(repo.all_bars()) == 1  # nothing written
        engine.close()

    def test_apply_appends_a_corrected_bar_that_get_bars_now_returns(self, tmp_path, capsys) -> None:
        db_path = tmp_path / "market_data"
        _seed(db_path, [_inverted_bar("AAA")])
        module = _load_module()

        exit_code = module.main(["--db-path", str(db_path), "--apply"])
        assert exit_code == 0
        assert "Appended 1 corrected bar(s)" in capsys.readouterr().out

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repo = DuckDBDataRepository(engine)
        assert len(repo.all_bars()) == 2  # original bad row kept immutably, plus the correction

        result = repo.get_bars("AAA", utc(2024, 1, 1), utc(2024, 1, 31), as_of_time=utc(2024, 1, 31))
        assert len(result) == 1  # get_bars's dedup (ADR-0168) serves only the corrected bar
        assert result[0].ingestion_time == utc(2024, 1, 2, 20)  # clamped up to available_time
        assert not (result[0].ingestion_time < result[0].available_time)
        engine.close()

    def test_running_twice_is_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        _seed(db_path, [_inverted_bar("AAA")])
        module = _load_module()

        module.main(["--db-path", str(db_path), "--apply"])
        # Second run: the corrected bar no longer inverts, so only the
        # original bad bar (immutably kept) still does -- but appending
        # the same correction again is a no-op via append_bars's own
        # dedup (identical natural key: same data_version this time,
        # since it is deterministic from the same inputs).
        exit_code = module.main(["--db-path", str(db_path), "--apply"])
        assert exit_code == 0

        engine = StorageEngine(StorageConfig(root_dir=db_path))
        repo = DuckDBDataRepository(engine)
        assert len(repo.all_bars()) == 2  # still just the one correction, not a third row
        engine.close()

    def test_no_inversions_found_is_a_clean_no_op(self, tmp_path, capsys) -> None:
        db_path = tmp_path / "market_data"
        clean_bar = dataclasses.replace(
            _inverted_bar("AAA"), ingestion_time=utc(2024, 1, 2, 20)
        )
        _seed(db_path, [clean_bar])
        module = _load_module()

        assert module.main(["--db-path", str(db_path)]) == 0
        assert "nothing to repair" in capsys.readouterr().out

    def test_missing_db_path_fails_cleanly(self, tmp_path) -> None:
        module = _load_module()
        missing = tmp_path / "does_not_exist"
        assert module.main(["--db-path", str(missing)]) == 1
