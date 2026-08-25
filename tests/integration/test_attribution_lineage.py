"""Category: Integration Test -- a real baseline backtest's
ExperimentRecord, persisted by Phase 4's ExperimentRepository, feeding
Phase 10's build_attribution_result, persisted through the new
attribution_results table, joined back to `experiments` by
`experiment_id` on a live DuckDB catalog (Phase 10 spec sections 9, 11).
"""

from __future__ import annotations

from datetime import date

import pytest
from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig
from backtest.strategy import BuyAndHoldStrategy

from storage_helpers import new_engine
from storage.counterfactual_repository import DuckDBAttributionRepository
from storage.experiment_repository import DuckDBExperimentRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from baseline.runner import run_baseline

from counterfactual.attribution import build_attribution_result


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 3, 29))
    aaa = [100.0 * (1.001**i) for i in range(len(days))]
    bars = make_bars("AAA", days, aaa)
    securities = [make_security("AAA", "AAA")]
    bench = make_benchmark(days, [4000.0 * (1.0004**i) for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), benchmark_id="SP500", code_version="phase10-attribution-test", seed=1,
    )
    return repo, config


class TestAttributionLineage:
    def test_attribution_joins_back_to_its_experiment_on_a_live_catalog(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        experiment_repo = DuckDBExperimentRepository(engine)
        attribution_repo = DuckDBAttributionRepository(engine)

        run_result = run_baseline(
            BuyAndHoldStrategy(["AAA"]), "buy_and_hold", repo, config,
            journal=journal, experiment_repo=experiment_repo,
        )
        experiment_id = run_result.backtest_result.experiment.experiment_id

        stored_experiment = experiment_repo.get(experiment_id)
        assert stored_experiment is not None

        result = build_attribution_result(stored_experiment)
        attribution_repo.record(result)

        # The reconciliation identity holds for a real, engine-computed
        # PerformanceReport, not just the hand-built fixtures in
        # tests/counterfactual/test_attribution.py.
        assert result.market is not None
        assert result.market + result.selection + result.execution == pytest.approx(
            stored_experiment.metrics.cumulative_return
        )

        joined = engine.connection.execute(
            "SELECT a.experiment_id, e.strategy_version, a.payload_json "
            "FROM attribution_results a JOIN experiments e ON a.experiment_id = e.experiment_id "
            "WHERE a.experiment_id = ?",
            [experiment_id],
        ).fetchone()
        assert joined is not None
        assert joined[0] == experiment_id
        assert joined[1] == stored_experiment.strategy_version

        engine.close()
