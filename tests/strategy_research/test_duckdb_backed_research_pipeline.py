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
from data_infra.enums import SecurityStatus
from data_infra.universe import SymbolMetadata, UniverseDefinition, build_security_masters, build_universe_memberships

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


class TestUniverseModuleBackedDuckDBPersistence:
    """Category: Universe <-> DuckDB persistence (Phase 24, instruction
    section F). Same shape as the test above, but the `SecurityMaster`/
    `UniverseMembership` records come from `data_infra.universe`'s
    converter functions instead of hand-built test fixtures --
    proving the actual Phase 24 population path (also used by
    `scripts/ingest_real_market_data.py --universe ...`) round-trips
    through a real on-disk restart, including `get_universe`'s
    point-in-time query."""

    def test_universe_membership_and_security_master_survive_restart(self, tmp_path) -> None:
        from backtest_helpers import trading_days

        days = trading_days(date(2020, 1, 2), date(2021, 6, 1))
        trendup_closes = [100.0 * (1.0006**i) for i in range(len(days))]
        trenddown_closes = [100.0 * (0.9997**i) for i in range(len(days))]

        custom_universe = UniverseDefinition(
            name="TEST_UNIVERSE", version="v1", role="RESEARCH", description="TEST FIXTURE",
            symbols=(SymbolMetadata(symbol="TRENDUP"), SymbolMetadata(symbol="TRENDDOWN")),
        )
        universe_valid_from = days_to_utc(date(2020, 1, 2))

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(_make_bars("TRENDUP", days, trendup_closes))
        repo.append_bars(_make_bars("TRENDDOWN", days, trenddown_closes))
        for record in build_security_masters(custom_universe, valid_from=universe_valid_from):
            repo.add_security(record)
        for record in build_universe_memberships(custom_universe, valid_from=universe_valid_from):
            repo.add_universe_membership(record)

        as_of = days_to_utc(date(2021, 6, 2))
        universe_symbols = repo.get_universe("US_EQUITY", "TEST_UNIVERSE", as_of_time=as_of)
        assert set(universe_symbols) == {"TRENDUP", "TRENDDOWN"}

        strategy = LongTermMomentumStrategy(list(universe_symbols), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3))
        config = BacktestConfig(
            market="US_EQUITY", start_date=date(2020, 1, 2), end_date=date(2021, 6, 1),
            initial_capital=100_000.0, security_ids=tuple(universe_symbols), code_version="test",
        )
        result = BacktestEngine(repo, config, strategy).run()
        assert len(result.fills) > 0

        engine.close()

        engine2 = new_engine(tmp_path)
        repo2 = DuckDBDataRepository(engine2, calendars={"US_EQUITY": US_EQUITY})
        reloaded_universe = repo2.get_universe("US_EQUITY", "TEST_UNIVERSE", as_of_time=as_of)
        assert set(reloaded_universe) == {"TRENDUP", "TRENDDOWN"}
        reloaded_security = repo2.get_security("TRENDUP", as_of_time=as_of)
        assert reloaded_security is not None
        assert reloaded_security.exchange == "UNKNOWN"  # honest sentinel, not a guessed exchange
        engine2.close()


class TestPhase29DelistedSecurityDuckDBPersistence:
    """Phase 29 (instruction sections 9, 21, 57-D/P): a delisted
    security's real `valid_to` must survive a real on-disk restart and
    `get_universe`/`get_security`'s point-in-time SQL query (not just
    `InMemoryDataRepository`'s Python filtering, already covered in
    `tests/data_infra/test_phase29_survivorship_aware_universe.py`) must
    correctly exclude it once `as_of_time` passes `valid_to` -- and
    still include it for an `as_of_time` before that."""

    def test_delisted_security_excluded_after_valid_to_survives_duckdb_restart(self, tmp_path) -> None:
        custom_universe = UniverseDefinition(
            name="DELISTED_TEST_UNIVERSE", version="v1", role="RESEARCH", description="TEST FIXTURE",
            symbols=(
                SymbolMetadata(symbol="SURVIVOR", listed_from=days_to_utc(date(2005, 1, 1))),
                SymbolMetadata(
                    symbol="DELISTED_CO",
                    listed_from=days_to_utc(date(2005, 1, 1)),
                    listed_to=days_to_utc(date(2015, 6, 1)),
                ),
            ),
        )

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        for record in build_security_masters(custom_universe, valid_from=days_to_utc(date(2000, 1, 1))):
            repo.add_security(record)
        for record in build_universe_memberships(custom_universe, valid_from=days_to_utc(date(2000, 1, 1))):
            repo.add_universe_membership(record)
        engine.close()

        engine2 = new_engine(tmp_path)
        repo2 = DuckDBDataRepository(engine2, calendars={"US_EQUITY": US_EQUITY})

        before_delisting = repo2.get_universe("US_EQUITY", "DELISTED_TEST_UNIVERSE", as_of_time=days_to_utc(date(2010, 1, 1)))
        assert set(before_delisting) == {"SURVIVOR", "DELISTED_CO"}

        after_delisting = repo2.get_universe("US_EQUITY", "DELISTED_TEST_UNIVERSE", as_of_time=days_to_utc(date(2020, 1, 1)))
        assert set(after_delisting) == {"SURVIVOR"}

        reloaded_delisted = repo2.get_security("DELISTED_CO", as_of_time=days_to_utc(date(2010, 1, 1)))
        assert reloaded_delisted is not None
        assert reloaded_delisted.status == SecurityStatus.DELISTED
        assert reloaded_delisted.valid_to == days_to_utc(date(2015, 6, 1))

        assert repo2.get_security("DELISTED_CO", as_of_time=days_to_utc(date(2020, 1, 1))) is None
        engine2.close()
