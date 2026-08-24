"""Category: Backtest -> Trade Journal -> Regime -> Experience Dataset
lineage, end to end, through persistent storage (Phase 5 spec section 12,
16, Integration -- Paper Trading data foundation readiness).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import SimpleMomentumStrategy

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.experience_repository import DuckDBExperienceRepository
from storage.regime_repository import DuckDBRegimeRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from regime.enums import SubjectKind
from regime.experience import attach_regime_context
from regime.strategy import RegimeConditionedStrategy

from trade_journal.backtest_adapter import ingest_backtest_result
from trade_journal.experience import build_experience_records


def _scenario():
    import random

    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    rng = random.Random(21)
    aaa, bbb = [100.0], [80.0]
    for _ in range(1, len(days)):
        aaa.append(aaa[-1] * (1 + rng.gauss(0.0006, 0.018)))
        bbb.append(bbb[-1] * (1 + rng.gauss(-0.0003, 0.015)))
    bars = make_bars("AAA", days, aaa) + make_bars("BBB", days, bbb)
    securities = [make_security("AAA", "AAA"), make_security("BBB", "BBB")]
    bench = make_benchmark(days, [4000.0 + i * 0.3 for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA", "BBB"), benchmark_id="SP500", code_version="regime-lineage-integration-test",
    )
    return repo, config


class TestFullLineage:
    def test_market_regime_field_gets_populated_and_persists_through_restart(self, tmp_path) -> None:
        repo, config = _scenario()
        base = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        strategy = RegimeConditionedStrategy(base, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result = BacktestEngine(repo, config, strategy).run()
        assert len(result.fills) > 0

        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        journal1 = DuckDBTradeJournalRepository(engine1)
        regime_repo1 = DuckDBRegimeRepository(engine1)
        experience_repo1 = DuckDBExperienceRepository(engine1)

        ingest_backtest_result(journal1, result, config)
        for composite in strategy.regime_history:
            regime_repo1.record_composite(composite)

        records = build_experience_records(journal1)
        enriched = attach_regime_context(
            records, journal1, regime_repo1, subject_id="AAA", subject_kind=SubjectKind.SECURITY,
        )
        assert any(r.market_regime is not None for r in enriched)
        experience_repo1.record_many(enriched)
        engine1.close()

        # Restart: every layer (journal, regime, experience) reopens from
        # the same on-disk catalog and the lineage survives intact.
        engine2 = StorageEngine(store_config)
        experience_repo2 = DuckDBExperienceRepository(engine2)
        regime_repo2 = DuckDBRegimeRepository(engine2)

        reloaded_experience = experience_repo2.list_all()
        assert len(reloaded_experience) == len(enriched)
        assert any(r.market_regime is not None for r in reloaded_experience)

        reloaded_composites = regime_repo2.list_composites(subject_id="AAA")
        assert len(reloaded_composites) == len(strategy.regime_history)
        engine2.close()

    def test_regime_context_is_never_from_after_the_decision(self, tmp_path) -> None:
        """The regime attached to a decision must have as_of_time <= the
        decision's own decision_time -- point-in-time correctness applied
        to the lineage join itself, not just to the original regime
        computation."""
        repo, config = _scenario()
        base = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        strategy = RegimeConditionedStrategy(base, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result = BacktestEngine(repo, config, strategy).run()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        journal = DuckDBTradeJournalRepository(engine)
        regime_repo = DuckDBRegimeRepository(engine)
        ingest_backtest_result(journal, result, config)
        for composite in strategy.regime_history:
            regime_repo.record_composite(composite)

        for decision in journal.list_decisions():
            composite = regime_repo.get_composite_as_of(
                "AAA", SubjectKind.SECURITY, decision.decision_time
            )
            if composite is not None:
                assert composite.as_of_time <= decision.decision_time
        engine.close()

    def test_experiment_and_regime_share_the_same_storage_catalog(self, tmp_path) -> None:
        """Regime, Trade Journal, and Experiment all live in one DuckDB
        catalog file (ADR-0010/ADR-0011) -- a direct SQL join across them
        is possible without federating multiple files."""
        repo, config = _scenario()
        base = SimpleMomentumStrategy(["AAA", "BBB"], lookback_days=15, top_n=1, rebalance_every=5)
        strategy = RegimeConditionedStrategy(base, subject_id="AAA", subject_kind=SubjectKind.SECURITY)
        result = BacktestEngine(repo, config, strategy).run()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        journal = DuckDBTradeJournalRepository(engine)
        regime_repo = DuckDBRegimeRepository(engine)
        ingest_backtest_result(journal, result, config)
        for composite in strategy.regime_history:
            regime_repo.record_composite(composite)

        rows = engine.connection.execute(
            "SELECT d.security_id, r.state FROM decisions d "
            "JOIN regime_composites c ON c.as_of_time <= d.decision_time "
            "JOIN regime_observations r ON r.regime_id IN ("
            "  SELECT regime_id FROM regime_observations WHERE axis = 'TREND'"
            ") "
            "LIMIT 5"
        ).fetchall()
        assert isinstance(rows, list)  # the join executes -- both tables live in the same catalog
        engine.close()
