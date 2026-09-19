"""Real, executable tests for
`scripts/merge_insider_transaction_catalogs.py` -- makes no network
call (pure local DuckDB catalog merging via ATTACH), so unlike
`ingest_insider_transactions.py` this is imported and `main()` is
called directly against real, seeded catalogs (same pattern
`test_repair_ingestion_time_inversions.py` already established for a
different real-catalog-mutating script)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from helpers import utc

from data_infra.insider_models import InsiderTransaction
from data_infra.models import Provenance

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.insider_repository import DuckDBInsiderRepository


def new_engine(root_dir: Path) -> StorageEngine:
    """Constructs directly against `root_dir` itself (unlike the
    shared `storage_helpers.new_engine`, which nests under a `store/`
    subdirectory) -- this script's own `--db-path`/`--target-db-path`
    args are used as the literal catalog root, matching
    `ingest_insider_transactions.py --db-path`'s own convention."""
    return StorageEngine(StorageConfig(root_dir))

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "merge_insider_transaction_catalogs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("merge_insider_transaction_catalogs", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _txn(*, record_id: str, security_id: str) -> InsiderTransaction:
    provenance = Provenance(
        source="sec_edgar", source_dataset=f"sec_edgar_form4_{security_id}",
        source_record_id=record_id, retrieved_at=utc(2026, 9, 3), data_version="v1",
    )
    return InsiderTransaction(
        security_id=security_id, reporting_owner_cik="0001780525",
        reporting_owner_name="Test Owner", is_officer=True, is_director=False,
        is_ten_percent_owner=False, officer_title="SVP",
        transaction_date=utc(2026, 9, 1), transaction_code="S",
        acquired_disposed_code="D", shares=100.0, price_per_share=50.0,
        is_10b5_1_plan=True, accession_number=record_id.split(":")[0],
        available_time=utc(2026, 9, 3), ingestion_time=utc(2026, 9, 3), provenance=provenance,
    )


def _seed(db_path: Path, transactions: list[InsiderTransaction]) -> None:
    engine = new_engine(db_path)
    DuckDBInsiderRepository(engine).add_insider_transactions(transactions)
    engine.close()


class TestMergeInsiderTransactionCatalogs:
    def test_merges_two_shards_with_disjoint_symbols(self, tmp_path, capsys) -> None:
        shard0 = tmp_path / "shard0"
        shard1 = tmp_path / "shard1"
        _seed(shard0, [_txn(record_id="0001:0", security_id="AAPL")])
        _seed(shard1, [_txn(record_id="0002:0", security_id="MSFT")])

        module = _load_module()
        target = tmp_path / "combined"
        exit_code = module.main([
            "--target-db-path", str(target),
            "--shard-db-path", str(shard0),
            "--shard-db-path", str(shard1),
        ])
        assert exit_code == 0
        assert "2 row(s) after (2 new)" in capsys.readouterr().out

        engine = new_engine(target)
        repo = DuckDBInsiderRepository(engine)
        aapl = repo.get_insider_transactions("AAPL", utc(2026, 12, 31))
        msft = repo.get_insider_transactions("MSFT", utc(2026, 12, 31))
        assert len(aapl) == 1
        assert len(msft) == 1
        engine.close()

    def test_running_twice_is_idempotent(self, tmp_path) -> None:
        shard0 = tmp_path / "shard0"
        _seed(shard0, [_txn(record_id="0001:0", security_id="AAPL")])

        module = _load_module()
        target = tmp_path / "combined"
        module.main(["--target-db-path", str(target), "--shard-db-path", str(shard0)])
        exit_code = module.main(["--target-db-path", str(target), "--shard-db-path", str(shard0)])
        assert exit_code == 0

        engine = new_engine(target)
        total = engine.connection.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0]
        assert total == 1  # not duplicated
        engine.close()

    def test_a_missing_shard_catalog_is_skipped_not_fatal(self, tmp_path, capsys) -> None:
        shard0 = tmp_path / "shard0"
        _seed(shard0, [_txn(record_id="0001:0", security_id="AAPL")])
        missing_shard = tmp_path / "does_not_exist"

        module = _load_module()
        target = tmp_path / "combined"
        exit_code = module.main([
            "--target-db-path", str(target),
            "--shard-db-path", str(shard0),
            "--shard-db-path", str(missing_shard),
        ])
        assert exit_code == 0
        assert "no catalog.duckdb found, skipping" in capsys.readouterr().out

        engine = new_engine(target)
        total = engine.connection.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0]
        assert total == 1
        engine.close()

    def test_merging_into_an_already_populated_target_preserves_existing_rows(self, tmp_path) -> None:
        target = tmp_path / "combined"
        _seed(target, [_txn(record_id="0000:0", security_id="GOOGL")])
        shard0 = tmp_path / "shard0"
        _seed(shard0, [_txn(record_id="0001:0", security_id="AAPL")])

        module = _load_module()
        exit_code = module.main(["--target-db-path", str(target), "--shard-db-path", str(shard0)])
        assert exit_code == 0

        engine = new_engine(target)
        total = engine.connection.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0]
        assert total == 2
        engine.close()
