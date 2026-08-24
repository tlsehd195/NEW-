"""Category: Backtest -> Trade Journal -> Prediction -> Experience Dataset
lineage, end to end, through persistent storage (Phase 6 spec section 12,
13, Integration).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_benchmark, make_security, trading_days

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import SimpleMomentumStrategy

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.prediction_repository import DuckDBPredictionRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from predict.config import PredictionConfig
from predict.experience import attach_prediction_context
from predict.predictor import DriftPredictor

from trade_journal.backtest_adapter import ingest_backtest_result
from trade_journal.experience import build_experience_records


def _scenario():
    import random

    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    rng = random.Random(31)
    closes = [100.0]
    for _ in range(1, len(days)):
        closes.append(closes[-1] * (1 + rng.gauss(0.0006, 0.015)))
    bars = make_bars("AAA", days, closes)
    securities = [make_security("AAA", "AAA")]
    bench = make_benchmark(days, [4000.0 + i * 0.3 for i in range(len(days))])
    repo = build_repository(bars=bars, securities=securities, benchmarks=bench)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), benchmark_id="SP500", code_version="predict-lineage-integration-test",
    )
    return repo, days, config


class TestFullLineage:
    def test_expected_outcome_field_gets_populated_and_persists_through_restart(self, tmp_path) -> None:
        repo, days, config = _scenario()
        strategy = SimpleMomentumStrategy(["AAA"], lookback_days=15, top_n=1, rebalance_every=5)
        result = BacktestEngine(repo, config, strategy).run()
        assert len(result.fills) > 0

        # Compute predictions at every checkpoint, mirroring how a real
        # deployment would run Prediction alongside (not inside) the
        # decision loop (Phase 6 spec section 8).
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)
        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        predictions = []
        for i in range(len(checkpoints)):
            clock.index = i
            predictions.append(predictor.predict(view, "AAA"))

        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        journal1 = DuckDBTradeJournalRepository(engine1)
        prediction_repo1 = DuckDBPredictionRepository(engine1)

        ingest_backtest_result(journal1, result, config)
        for p in predictions:
            prediction_repo1.record(p)

        records = build_experience_records(journal1)
        enriched = attach_prediction_context(records, journal1, prediction_repo1, security_id="AAA")
        assert any(r.expected_outcome is not None for r in enriched)
        engine1.close()

        # Restart: predictions and the enrichment inputs both survive.
        engine2 = StorageEngine(store_config)
        prediction_repo2 = DuckDBPredictionRepository(engine2)
        reloaded_predictions = prediction_repo2.list_all(security_id="AAA")
        assert len(reloaded_predictions) == len(predictions)
        engine2.close()

    def test_prediction_context_is_never_from_after_the_decision(self, tmp_path) -> None:
        repo, days, config = _scenario()
        strategy = SimpleMomentumStrategy(["AAA"], lookback_days=15, top_n=1, rebalance_every=5)
        result = BacktestEngine(repo, config, strategy).run()

        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)
        predictor = DriftPredictor(PredictionConfig(lookback_days=20))

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        journal = DuckDBTradeJournalRepository(engine)
        prediction_repo = DuckDBPredictionRepository(engine)
        ingest_backtest_result(journal, result, config)
        for i in range(len(checkpoints)):
            clock.index = i
            prediction_repo.record(predictor.predict(view, "AAA"))

        for decision in journal.list_decisions():
            prediction = prediction_repo.get_as_of("AAA", decision.decision_time)
            if prediction is not None:
                assert prediction.as_of_time <= decision.decision_time
        engine.close()

    def test_prediction_and_trade_journal_share_the_same_storage_catalog(self, tmp_path) -> None:
        repo, days, config = _scenario()
        strategy = SimpleMomentumStrategy(["AAA"], lookback_days=15, top_n=1, rebalance_every=5)
        result = BacktestEngine(repo, config, strategy).run()

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        journal = DuckDBTradeJournalRepository(engine)
        prediction_repo = DuckDBPredictionRepository(engine)
        ingest_backtest_result(journal, result, config)

        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)
        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        for i in range(len(checkpoints)):
            clock.index = i
            prediction_repo.record(predictor.predict(view, "AAA"))

        rows = engine.connection.execute(
            "SELECT d.security_id, p.expected_return FROM decisions d "
            "JOIN predictions p ON p.security_id = d.security_id AND p.as_of_time <= d.decision_time "
            "LIMIT 5"
        ).fetchall()
        assert isinstance(rows, list)  # the join executes -- both tables live in the same catalog
        engine.close()
