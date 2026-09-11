"""Session 36 continued tests for
`scripts/run_multi_strategy_paper_trading_cycle.py` (ADR-0110) -- the
multi-strategy paper trading runner the account owner asked for
("멀티 전략 ㄱㄱ"), following up on this session's own earlier future-
work note in `docs/PROJECT_STATUS.md`.

Network-free (reads only a local DuckDB catalog this test populates
itself), mirroring `tests/orchestration/test_run_paper_trading_cycle_cli.py`'s
own precedent for this kind of script."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

from backtest_helpers import make_bars, make_security, trading_days

from data_infra.universe import SymbolMetadata, UniverseDefinition

from storage.config import StorageConfig
from storage.data_repository import DuckDBDataRepository
from storage.engine import StorageEngine
from storage.paper_repository import DuckDBPaperOrderRepository
from storage.prediction_repository import DuckDBPredictionRepository

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_multi_strategy_paper_trading_cycle.py"
_SINGLE_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_paper_trading_cycle.py"


def _load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_long_catalog(db_path: Path) -> None:
    """>100 trading days, same construction `test_run_paper_trading_
    cycle_cli.py`'s own `_seed_long_catalog` uses -- needed so
    `BaselineRuleDecisionAgent` actually BUYs at least once (its own
    TREND axis stays UNKNOWN, never BUY, under 100 days of history)."""
    days = trading_days(date(2024, 1, 2), date(2024, 7, 31))
    prices = [100.0 * (1.006**i) for i in range(len(days))]
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
        _load_module(_SCRIPT_PATH)


class TestUnknownStrategyFailsClean:
    def test_unregistered_strategy_name_fails_with_rc_1_not_a_traceback(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        _seed_long_catalog(db_path)
        module = _load_module(_SCRIPT_PATH)
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store-root", str(tmp_path / "store"),
            "--strategies", "not_a_real_strategy",
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(tmp_path / "report.json"),
        ])
        assert rc == 1


class TestMultiStrategyIsolation:
    def test_default_runs_all_three_registered_strategies_into_isolated_stores(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        store_root = tmp_path / "store"
        out_path = tmp_path / "report.json"
        _seed_long_catalog(db_path)

        module = _load_module(_SCRIPT_PATH)
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store-root", str(store_root),
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(out_path),
        ])
        assert rc == 0

        report = json.loads(out_path.read_text())
        assert set(report["strategies"]) == {"baseline_rule", "random_walk_baseline", "buy_and_hold"}

        # Each strategy really got its own on-disk store, not a shared one.
        for name in ("baseline_rule", "random_walk_baseline", "buy_and_hold"):
            assert (store_root / name).is_dir()

    def test_baseline_rule_and_random_walk_baseline_produce_different_orders(self, tmp_path) -> None:
        """RandomWalkPredictor's expected_return is always 0.0 by
        construction of the null hypothesis -- BaselineRuleDecisionAgent
        fed that prediction must behave differently from being fed
        DriftPredictor's real, non-zero drift estimate over a rising
        synthetic price series, proving the two strategies are not
        secretly running the exact same logic."""
        db_path = tmp_path / "market_data"
        store_root = tmp_path / "store"
        out_path = tmp_path / "report.json"
        _seed_long_catalog(db_path)

        module = _load_module(_SCRIPT_PATH)
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store-root", str(store_root),
            "--strategies", "baseline_rule,random_walk_baseline",
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert (
            report["strategies"]["baseline_rule"]["total_orders_submitted"]
            != report["strategies"]["random_walk_baseline"]["total_orders_submitted"]
        )

    def test_buy_and_hold_buys_exactly_once_and_never_again_on_resume(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        store_root = tmp_path / "store"
        _seed_long_catalog(db_path)

        module = _load_module(_SCRIPT_PATH)
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run(out_name, *, end):
            out_path = tmp_path / out_name
            rc = module.main([
                "--universe", "TEST_UNIVERSE",
                "--db-path", str(db_path),
                "--paper-store-root", str(store_root),
                "--strategies", "buy_and_hold",
                "--start", "2024-06-15", "--end", end,
                "--resume",
                "--out", str(out_path),
            ])
            assert rc == 0
            return json.loads(out_path.read_text())

        first = _run("first.json", end="2024-06-20")
        assert first["strategies"]["buy_and_hold"]["already_bought_before_this_run"] is False

        second = _run("second.json", end="2024-06-25")
        assert second["strategies"]["buy_and_hold"]["already_bought_before_this_run"] is True

        order_repo = DuckDBPaperOrderRepository(StorageEngine(StorageConfig(root_dir=store_root / "buy_and_hold")))
        assert len(order_repo.list_all()) == 1  # exactly one BUY, never a second

    def test_buy_and_hold_defaults_to_paper_capital_usd_not_the_generic_default(self, tmp_path) -> None:
        # ADR-0115: without an explicit --initial-capital, buy_and_hold
        # must be funded from ADR-0028's own PAPER_CAPITAL_USD (10,000)
        # reference figure, never PaperTradingConfig's generic
        # 1,000,000 default -- a single equal-weight buy across this
        # one-symbol universe spends nearly the whole starting cash, so
        # a leftover final_cash anywhere near six figures would mean
        # the wrong (100x too large) capital was actually used.
        from broker.paper.us_longterm_config import PAPER_CAPITAL_USD

        db_path = tmp_path / "market_data"
        store_root = tmp_path / "store"
        out_path = tmp_path / "report.json"
        _seed_long_catalog(db_path)

        module = _load_module(_SCRIPT_PATH)
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        rc = module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store-root", str(store_root),
            "--strategies", "buy_and_hold",
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        final_cash = report["strategies"]["buy_and_hold"]["final_cash"]
        assert final_cash < PAPER_CAPITAL_USD
        assert final_cash < 100_000.0  # far below what a 1,000,000 default would leave behind

    def test_run_cycle_strategy_isolated_by_this_script_matches_the_single_strategy_script(self, tmp_path) -> None:
        """Regression-safety proof: `orchestration.paper_strategies.
        build_run_cycle_components("baseline_rule", ...)` moving the
        component construction out of `run_paper_trading_cycle.py`
        (ADR-0110) must not have changed what that script actually
        computes -- running "baseline_rule" alone through THIS script
        must produce the identical order/fill counts a direct
        single-strategy run does for the exact same inputs."""
        db_path = tmp_path / "market_data"
        _seed_long_catalog(db_path)

        multi_module = _load_module(_SCRIPT_PATH)
        multi_module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()
        single_module = _load_module(_SINGLE_SCRIPT_PATH)
        single_module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        multi_out = tmp_path / "multi_report.json"
        rc = multi_module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store-root", str(tmp_path / "multi_store"),
            "--strategies", "baseline_rule",
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(multi_out),
        ])
        assert rc == 0

        single_out = tmp_path / "single_report.json"
        rc = single_module.main([
            "--universe", "TEST_UNIVERSE",
            "--db-path", str(db_path),
            "--paper-store", str(tmp_path / "single_store"),
            "--start", "2024-06-15", "--end", "2024-06-25",
            "--out", str(single_out),
        ])
        assert rc == 0

        multi_report = json.loads(multi_out.read_text())["strategies"]["baseline_rule"]
        single_report = json.loads(single_out.read_text())

        assert multi_report["checkpoints_run"] == single_report["checkpoints_run"]
        assert multi_report["total_orders_submitted"] == single_report["total_orders_submitted"]
        assert multi_report["total_orders_with_a_fill"] == single_report["total_orders_with_a_fill"]
        assert multi_report["final_cash"] == single_report["final_cash"]
        assert multi_report["final_positions"] == single_report["final_positions"]

    def test_resume_skips_already_processed_checkpoints_for_run_cycle_strategies(self, tmp_path) -> None:
        db_path = tmp_path / "market_data"
        store_root = tmp_path / "store"
        _seed_long_catalog(db_path)
        module = _load_module(_SCRIPT_PATH)
        module._UNIVERSES["TEST_UNIVERSE"] = _tiny_universe()

        def _run(out_name, *, resume, end):
            out_path = tmp_path / out_name
            argv = [
                "--universe", "TEST_UNIVERSE",
                "--db-path", str(db_path),
                "--paper-store-root", str(store_root),
                "--strategies", "baseline_rule",
                "--start", "2024-06-15", "--end", end,
                "--out", str(out_path),
            ]
            if resume:
                argv.append("--resume")
            assert module.main(argv) == 0
            return json.loads(out_path.read_text())["strategies"]["baseline_rule"]

        first = _run("first.json", resume=False, end="2024-06-20")
        second = _run("second.json", resume=True, end="2024-06-25")

        store_engine = StorageEngine(StorageConfig(root_dir=store_root / "baseline_rule"))
        prediction_repo = DuckDBPredictionRepository(store_engine)
        total_predictions = len(prediction_repo.list_all(security_id="AAA"))
        store_engine.close()
        assert total_predictions == first["checkpoints_run"] + second["checkpoints_run"]
