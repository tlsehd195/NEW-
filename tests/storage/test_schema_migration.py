"""Category: restart safety across a schema change (additive migration).

Reproduces the 2026-09-26 paper_trading_cycle failure: a DuckDB file
created before ADR-0203 added the ``provenance_*`` columns to
``security_master``/``universe_membership`` kept its old tables (``CREATE
TABLE IF NOT EXISTS`` never alters an existing table), so the first
``add_security`` on the next run failed with ``Binder Error: Table
"security_master" does not have a column with name "provenance_source"``.
"""

from __future__ import annotations

import duckdb
import pytest

from backtest_helpers import make_membership, make_security, utc

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine

# The two tables exactly as src/storage/schema.py defined them before ADR-0203.
PRE_ADR_0203_DDL = (
    """
    CREATE TABLE security_master (
        security_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        exchange TEXT NOT NULL,
        currency TEXT NOT NULL,
        company_id TEXT NOT NULL,
        instrument_type TEXT NOT NULL,
        valid_from TIMESTAMP NOT NULL,
        valid_to TIMESTAMP,
        status TEXT NOT NULL,
        PRIMARY KEY (security_id, valid_from)
    )
    """,
    """
    CREATE TABLE universe_membership (
        security_id TEXT NOT NULL,
        universe TEXT NOT NULL,
        valid_from TIMESTAMP NOT NULL,
        valid_to TIMESTAMP,
        PRIMARY KEY (security_id, universe, valid_from)
    )
    """,
)


def _create_pre_adr_0203_store(config: StorageConfig) -> None:
    config.ensure_dirs()
    conn = duckdb.connect(str(config.duckdb_path))
    for statement in PRE_ADR_0203_DDL:
        conn.execute(statement)
    conn.execute(
        "INSERT INTO security_master VALUES "
        "('OLD', 'OLD', 'NASDAQ', 'USD', 'COMPANY-OLD', 'EQUITY', '2020-01-01', NULL, 'ACTIVE')"
    )
    conn.close()


class TestAdditiveSchemaMigration:
    def test_old_store_accepts_writes_after_reopen(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        _create_pre_adr_0203_store(config)

        engine = StorageEngine(config)
        repo = DuckDBDataRepository(engine)
        repo.add_security(make_security("AAA", "AAA"))
        repo.add_universe_membership(make_membership("AAA", utc(2020, 1, 1)))

        assert repo.get_security("AAA", utc(2024, 6, 1)) is not None
        assert "AAA" in repo.get_universe("US", "SP500", utc(2024, 6, 1))
        # The pre-existing row survives and reads back with no provenance.
        old = repo.get_security("OLD", utc(2024, 6, 1))
        assert old is not None and old.provenance is None
        engine.close()

    def test_migration_is_idempotent_across_reopens(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        _create_pre_adr_0203_store(config)
        StorageEngine(config).close()
        engine = StorageEngine(config)
        columns = [r[0] for r in engine.connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'security_master'"
        ).fetchall()]
        assert columns.count("provenance_source") == 1
        engine.close()

    def test_missing_not_null_column_fails_loudly(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        config.ensure_dirs()
        conn = duckdb.connect(str(config.duckdb_path))
        conn.execute("CREATE TABLE security_master (security_id TEXT NOT NULL, valid_from TIMESTAMP NOT NULL)")
        conn.close()

        with pytest.raises(RuntimeError, match="NOT NULL column 'ticker'"):
            StorageEngine(config)
