"""Category: Persistence / Paper Trading connection (instruction
sections 29, 35-F/R). Proves the strategy_research runner is not
InMemoryDataRepository-specific: it runs identically against a real,
on-disk `DuckDBDataRepository` (Phase 4, unmodified), including a full
engine close/reopen restart -- the same DataRepository Protocol
`PaperMarketDataSource`/`PaperTradingSession` (Phase 15/22) already
consume, so a strategy proven here is structurally connectable to Paper
Trading without any strategy_research-specific plumbing."""

from __future__ import annotations

from datetime import date, datetime, timezone

from research_helpers import days_to_utc
from storage_helpers import new_engine

from data_infra.calendar import US_EQUITY

from backtest.engine import BacktestConfig, BacktestEngine

from storage.data_repository import DuckDBDataRepository

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy


def _make_bars(security_id, days, closes):
    from backtest_helpers import make_bars

    return make_bars(security_id, days, closes)


class TestDuckDBBackedResearchPipeline:
    def test_backtest_engine_runs_against_duckdb_repository_and_survives_restart(self, tmp_path) -> None:
        from backtest_helpers import make_security, trading_days

        days = trading_days(date(2020, 1, 2), date(2021, 6, 1))
        trendup_closes = [100.0 * (1.0006**i) for i in range(len(days))]
        trenddown_closes = [100.0 * (0.9997**i) for i in range(len(days))]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(_make_bars("TRENDUP", days, trendup_closes))
        repo.append_bars(_make_bars("TRENDDOWN", days, trenddown_closes))
        repo.add_security(make_security("TRENDUP", "TRENDUP"))
        repo.add_security(make_security("TRENDDOWN", "TRENDDOWN"))

        config = BacktestConfig(
            market="US_EQUITY", start_date=date(2020, 1, 2), end_date=date(2021, 6, 1),
            initial_capital=100_000.0, security_ids=("TRENDUP", "TRENDDOWN"), code_version="test",
        )
        strategy = LongTermMomentumStrategy(["TRENDUP", "TRENDDOWN"], LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3))
        result = BacktestEngine(repo, config, strategy).run()

        assert len(result.fills) > 0
        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDUP"}

        engine.close()

        # Restart: reopen the same on-disk catalog and confirm the raw
        # ingested bars are unchanged -- the backtest run above performed
        # no writes back into the repository at all (Strategy/BacktestEngine
        # never mutate DataRepository, Phase 2 spec section 5).
        engine2 = new_engine(tmp_path)
        repo2 = DuckDBDataRepository(engine2, calendars={"US_EQUITY": US_EQUITY})
        # end/as_of_time is one calendar day past the window's last
        # trading day -- the last bar's `available_time` is that day's
        # 20:00 checkpoint (backtest_helpers.checkpoint's convention), so
        # an as_of_time of that same day's midnight would correctly (not
        # a bug) exclude it as "not yet available" at that instant.
        as_of = days_to_utc(date(2021, 6, 2))
        reloaded = repo2.get_bars("TRENDUP", days_to_utc(date(2020, 1, 2)), as_of, as_of_time=as_of)
        assert len(reloaded) == len(days)
        assert reloaded[0].close == trendup_closes[0]
        engine2.close()
