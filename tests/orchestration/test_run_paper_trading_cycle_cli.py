"""Session 36 tests for `scripts/run_paper_trading_cycle.py` (ADR-0068).

Makes no network call (reads only a local DuckDB catalog this test
populates itself), so -- unlike the SEC EDGAR/network-dependent
scripts this project tests at the AST/source level only -- this one is
run end to end via `main()`, mirroring `tests/strategy_research/
test_compute_fundamentals_ic_from_catalog_cli.py`'s own precedent for
a network-free catalog-reading script. `_UNIVERSES` is monkeypatched to
a tiny one-symbol universe so the test does not need bars for every
real symbol in `PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE4`."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from backtest_helpers import make_bars, make_security, trading_days

from data_infra.universe import SymbolMetadata, UniverseDefinition

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository
from storage.prediction_repository import DuckDBPredictionRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_paper_trading_cycle.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_paper_trading_cycle", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_catalog(db_path: Path) -> None:
    days = trading_days(date(2024, 1, 2), date(2024, 4, 30))
    prices = [100.0 * (1.006 ** i) for i in range(len(days))]
    bars = make_bars("AAA", days, prices)
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    repository = DuckDBDataRepository(engine)
    repository.add_security(make_security("AAA", "AAA"))
    repository.append_bars(bars)
    engine.close()


def _seed_long_catalog(db_path: Path) -> None:
    """Session 36 continued -- ADR-0096's own trade-journal-write test
    needs a REAL fill, unlike every pre-existing test in this file
    (none of which assert one happens at all). `_seed_catalog`'s own
    ~85 trading days is never enough on its own: `RegimeDetector`'s
    default `RegimeConfig.trend_long_window=100` keeps TREND
    permanently `UNKNOWN` (and `BaselineRuleDecisionAgent` never BUYs
    on an unknown trend) until more than 100 real trading days of
    history exist before the requested `--start` -- confirmed by
    directly instrumenting `run_cycle` against `_seed_catalog`'s own
    fixture, which produces `NO_TRADE`/`regime_trend_unknown` for
    every single checkpoint, never a BUY."""
    days = trading_days(date(2024, 1, 2), date(2024, 7, 31))
    prices = [100.0 * (1.006 ** i) for i in range(len(days))]
    bars = make_bars("AAA", days, prices)
    engine = StorageEngine(StorageConfig(root_dir=db_path))
    repository = DuckDBDataRepository(engine)
    repository.add_security(make_security("AAA", "AAA"))
    repository.append_bars(bars)
    engine.close()


def _tiny_universe() -> UniverseDefinition:
    return UniverseDefinition(
        name="TEST_UNIVERSE", version="v1", role="RESEARCH", description="d",
        symbols=(SymbolMetadata(symbol="AAA", sector="Technology"),),
    )


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module()  # raises on any import/syntax error


class TestEndToEndAgainstASeededCatalog:
    def test_a_short_run_persists_real_lineage_and_writes_a_report(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"
        _seed_catalog(db_path)

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-15",
            "--out", str(out_path),
        ])
        assert rc == 0

        report = json.loads(out_path.read_text())
        assert report["universe"] == "TEST_UNIVERSE"
        assert report["checkpoints_run"] > 0
        assert "content_checksum" in report

        # Real persistence -- not just an in-memory result thrown away.
        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        prediction_repo = DuckDBPredictionRepository(store_engine)
        assert len(prediction_repo.list_all(security_id="AAA")) == report["checkpoints_run"]
        store_engine.close()

    def test_a_run_populates_the_real_trade_journal(self, tmp_path) -> None:
        """Session 36 continued -- ADR-0096: before this, this script
        never populated the Trade Journal at all."""
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"
        _seed_long_catalog(db_path)

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            # Past both DriftPredictor's 20-day lookback AND
            # RegimeDetector's default 100-trading-day trend_long_window
            # -- see _seed_long_catalog's own docstring for why anything
            # earlier never produces a real BUY at all (TREND stays
            # UNKNOWN, confirmed by directly instrumenting run_cycle).
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert report["total_orders_with_a_fill"] > 0

        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        trade_journal = DuckDBTradeJournalRepository(store_engine)
        trades = trade_journal.list_trades(security_id="AAA")
        assert len(trades) == report["total_orders_with_a_fill"]
        store_engine.close()

    def test_reentry_cooldown_days_is_reflected_in_the_report_and_defaults_to_disabled(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"
        _seed_catalog(db_path)

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-10",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert report["risk_config"]["reentry_cooldown_days"] is None

    def test_a_run_with_sector_limit_configured_uses_the_universes_real_sector_data(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"
        _seed_catalog(db_path)

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-10",
            "--max-sector-weight", "1.0",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert report["risk_config"]["max_sector_weight"] == 1.0

    def test_different_risk_config_produces_a_different_checksum(self, tmp_path) -> None:
        """Found via a real user run: two runs over the identical universe/
        window/capital but different --max-sector-weight/--max-order-notional
        produced materially different orders/fills/positions yet an
        IDENTICAL content_checksum, because the checksum payload omitted
        risk_config entirely -- the same reproducibility gap Phase 30/31
        already fixed for the ingestion manifest."""
        db_path = tmp_path / "market_data"
        _seed_catalog(db_path)
        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run(paper_store_name, **risk_kwargs):
            out_path = tmp_path / f"{paper_store_name}.json"
            argv = [
                "--universe", "TEST_UNIVERSE",
                "--db-path", str(db_path),
                "--paper-store", str(tmp_path / paper_store_name),
                "--start", "2024-02-01", "--end", "2024-02-15",
                "--out", str(out_path),
            ]
            for flag, value in risk_kwargs.items():
                argv += [flag, str(value)]
            assert module.main(argv) == 0
            return json.loads(out_path.read_text())

        unrestricted = _run("store_a")
        restricted = _run("store_b", **{"--max-sector-weight": 0.25, "--max-order-notional": 1000.0})
        assert unrestricted["content_checksum"] != restricted["content_checksum"]

    def test_missing_bars_fails_cleanly_not_with_a_traceback(self, tmp_path) -> None:
        db_path = tmp_path / "empty_market_data"
        StorageEngine(StorageConfig(root_dir=db_path)).close()
        paper_store = tmp_path / "paper_store"
        out_path = tmp_path / "report.json"

        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(paper_store),
            "--start", "2024-02-01", "--end", "2024-02-10",
            "--out", str(out_path),
        ])
        assert rc == 1


class TestResume:
    """ADR-0073: `--resume` is what makes it safe to invoke this script
    repeatedly (e.g. from a real external cron) over an overlapping
    range -- without it, a second invocation re-derives fresh decision/
    sizing/risk lineage IDs for checkpoints it already processed and
    genuinely double-submits every order (client_order_id's own
    idempotency only protects a single process's retry, not two
    separate invocations)."""

    def test_resume_skips_already_processed_checkpoints_not_reprocessing_them(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run(out_name, *, resume, end):
            out_path = tmp_path / out_name
            argv = [
                "--universe", "TEST_UNIVERSE",
                "--db-path", str(db_path),
                "--paper-store", str(paper_store),
                "--start", "2024-02-01", "--end", end,
                "--out", str(out_path),
            ]
            if resume:
                argv.append("--resume")
            assert module.main(argv) == 0
            return json.loads(out_path.read_text())

        first = _run("first.json", resume=False, end="2024-02-15")
        second = _run("second.json", resume=True, end="2024-02-29")

        # The second run's own [--start, --end] spans the whole month,
        # but it must only have actually RUN the checkpoints the first
        # run had not already recorded -- i.e. exactly (full-month
        # trading days) minus (however many the first run already did),
        # never the full month over again.
        full_month_days = len(trading_days(date(2024, 2, 1), date(2024, 2, 29)))
        assert second["checkpoints_run"] > 0
        assert second["checkpoints_run"] == full_month_days - first["checkpoints_run"]

        store_engine = StorageEngine(StorageConfig(root_dir=paper_store))
        prediction_repo = DuckDBPredictionRepository(store_engine)
        total_predictions = len(prediction_repo.list_all(security_id="AAA"))
        store_engine.close()
        # Never double-counted: total persisted predictions equals
        # exactly the sum of the two runs' own checkpoint counts, never
        # more (which would mean the overlapping days got reprocessed).
        assert total_predictions == first["checkpoints_run"] + second["checkpoints_run"]

    def test_resume_with_nothing_new_reports_zero_checkpoints_and_does_not_crash(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run(out_name, *, resume):
            out_path = tmp_path / out_name
            argv = [
                "--universe", "TEST_UNIVERSE",
                "--db-path", str(db_path),
                "--paper-store", str(paper_store),
                "--start", "2024-02-01", "--end", "2024-02-15",
                "--out", str(out_path),
            ]
            if resume:
                argv.append("--resume")
            assert module.main(argv) == 0
            return json.loads(out_path.read_text())

        first = _run("first.json", resume=False)
        second = _run("second.json", resume=True)  # identical range, already fully done

        assert first["checkpoints_run"] > 0
        assert second["checkpoints_run"] == 0

    def test_resume_reconstructs_value_history_across_invocations(self, tmp_path) -> None:
        """`state.value_history` must reflect the FULL real history
        across both invocations, not just the second one's own new
        checkpoints -- otherwise a resumed run's max_drawdown/
        max_portfolio_volatility checks would incorrectly reset to
        "insufficient history" every time the scheduler happens to
        restart the process."""
        db_path = tmp_path / "market_data"
        paper_store = tmp_path / "paper_store"
        _seed_catalog(db_path)
        module = _load_module()
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run(out_name, *, resume, end):
            out_path = tmp_path / out_name
            argv = [
                "--universe", "TEST_UNIVERSE",
                "--db-path", str(db_path),
                "--paper-store", str(paper_store),
                "--start", "2024-02-01", "--end", end,
                "--out", str(out_path),
            ]
            if resume:
                argv.append("--resume")
            assert module.main(argv) == 0
            return json.loads(out_path.read_text())

        first = _run("first.json", resume=False, end="2024-02-08")
        second = _run("second.json", resume=True, end="2024-02-15")

        assert first["value_history_length"] > 0
        # The second run's in-process value_history starts seeded with
        # every real prior point PLUS this run's own new checkpoints --
        # never reset to only the new ones.
        assert second["value_history_length"] == first["value_history_length"] + second["checkpoints_run"]
