"""Category: Integration Test -- a real baseline backtest run through the
Trade Journal, with Phase 10 Counterfactual analysis computed per trade
and persisted through Phase 3's *existing*, unmodified
`TradeJournalRepository.record_counterfactual`, then observed flowing
automatically into the Learning Engine's Experience Dataset via Phase 3's
*existing*, unmodified `build_experience_records`.

See docs/specifications/PHASE-10-counterfactual-attribution.md sections
3.5, 11.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig
from backtest.strategy import BuyAndHoldStrategy

from storage_helpers import new_engine
from storage.experiment_repository import DuckDBExperimentRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from trade_journal.enums import TradeProvenance
from trade_journal.experience import build_experience_records

from baseline.runner import run_baseline

from counterfactual.pipeline import run_counterfactual_analysis_for_provenance


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 3, 29))
    aaa = [100.0 * (1.001**i) for i in range(len(days))]
    bars = make_bars("AAA", days, aaa)
    securities = [make_security("AAA", "AAA")]
    bench = make_benchmark(days, [4000.0 * (1.0004**i) for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), benchmark_id="SP500", code_version="phase10-counterfactual-test", seed=1,
    )
    return repo, config


class TestCounterfactualFlowsIntoExperienceDataset:
    def test_richer_counterfactual_is_visible_through_unmodified_experience_builder(self, tmp_path) -> None:
        repo, config = _scenario()
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        experiment_repo = DuckDBExperimentRepository(engine)

        run_result = run_baseline(
            BuyAndHoldStrategy(["AAA"]), "buy_and_hold", repo, config,
            journal=journal, experiment_repo=experiment_repo,
        )
        assert len(run_result.backtest_result.fills) > 0

        # Before Phase 10 runs: no counterfactual has been recorded, so
        # the Experience Dataset's counterfactual_results field is None
        # for every record (Phase 3's existing, documented behavior).
        before = build_experience_records(journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert all(r.counterfactual_results is None for r in before)

        evaluation_time = datetime(
            config.end_date.year, config.end_date.month, config.end_date.day, 20, tzinfo=timezone.utc
        )
        records = run_counterfactual_analysis_for_provenance(
            repo, journal, TradeProvenance.HISTORICAL_SIMULATION, evaluation_time,
        )
        assert len(records) > 0
        for record in records:
            journal.record_counterfactual(
                record.trade_id, selected_action=record.selected_action, alternatives=record.alternatives,
            )

        # Zero changes to trade_journal.experience -- it already reads
        # journal.get_counterfactual(trade_id).alternatives.
        after = build_experience_records(journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        with_counterfactual = [r for r in after if r.counterfactual_results is not None]
        assert len(with_counterfactual) == len(records)
        for record in with_counterfactual:
            assert len(record.counterfactual_results) == 2
            actions = {a.action for a in record.counterfactual_results}
            assert actions == {"HOLD", "CASH"}

        engine.close()
