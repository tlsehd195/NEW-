"""Category: persistence, restart, idempotency, provenance, version
lineage for the persistent Regime store (Phase 5 spec section 11, 13)."""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, trading_days
from regime_helpers import trend_up, view_at

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.regime_repository import DuckDBRegimeRepository
from storage_helpers import new_engine

from regime.config import RegimeConfig
from regime.detector import RegimeDetector
from regime.enums import RegimeAxis, SubjectKind

from trade_journal.enums import TradeProvenance


def _composite():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, trend_up(days))
    repo = build_repository(bars=bars)
    view = view_at(repo, days, len(days) - 1)
    return RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")


class TestPersistenceAndRestart:
    def test_composite_and_axes_survive_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        composite = _composite()

        engine1 = StorageEngine(config)
        regime_repo1 = DuckDBRegimeRepository(engine1)
        stored = regime_repo1.record_composite(composite)
        engine1.close()

        engine2 = StorageEngine(config)
        regime_repo2 = DuckDBRegimeRepository(engine2)
        reloaded = regime_repo2.get_composite(stored.composite_id)
        assert reloaded is not None
        assert set(reloaded.axes.keys()) == set(RegimeAxis)
        for axis, obs in reloaded.axes.items():
            assert obs.axis == axis
            assert obs.state == composite.get(axis).state
        engine2.close()


class TestIdempotency:
    def test_recording_the_same_composite_twice_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        regime_repo = DuckDBRegimeRepository(engine)
        composite = _composite()
        c1 = regime_repo.record_composite(composite)
        c2 = regime_repo.record_composite(composite)
        assert c1.composite_id == c2.composite_id
        assert len(regime_repo.list_composites()) == 1
        assert len(regime_repo.list_observations(subject_id="AAA")) == len(RegimeAxis)
        engine.close()

    def test_recording_the_same_observation_twice_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        regime_repo = DuckDBRegimeRepository(engine)
        composite = _composite()
        trend_obs = composite.get(RegimeAxis.TREND)
        regime_repo.record_observation(trend_obs)
        regime_repo.record_observation(trend_obs)
        assert len(regime_repo.list_observations(subject_id="AAA", axis=RegimeAxis.TREND)) == 1
        engine.close()


class TestPointInTimeLookup:
    def test_get_composite_as_of_returns_the_most_recent_at_or_before(self, tmp_path) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        detector = RegimeDetector(RegimeConfig())

        engine = new_engine(tmp_path)
        regime_repo = DuckDBRegimeRepository(engine)
        for i in (50, 100, 150):
            view = view_at(repo, days, i)
            regime_repo.record_composite(detector.compute_composite(view, "AAA"))

        from backtest_helpers import checkpoint

        found = regime_repo.get_composite_as_of("AAA", SubjectKind.SECURITY, checkpoint(days[120]))
        assert found is not None
        assert found.as_of_time == checkpoint(days[100])

        too_early = regime_repo.get_composite_as_of("AAA", SubjectKind.SECURITY, checkpoint(days[10]))
        assert too_early is None
        engine.close()


class TestProvenanceAndVersionLineage:
    def test_provenance_filter_isolates_categories(self, tmp_path) -> None:
        import dataclasses

        engine = new_engine(tmp_path)
        regime_repo = DuckDBRegimeRepository(engine)
        composite = _composite()
        hist = dataclasses.replace(
            composite, composite_id="CREG-H", provenance=TradeProvenance.HISTORICAL_SIMULATION,
            axes={axis: dataclasses.replace(obs, regime_id=f"REG-H-{axis.value}", provenance=TradeProvenance.HISTORICAL_SIMULATION)
                  for axis, obs in composite.axes.items()},
        )
        paper = dataclasses.replace(
            composite, composite_id="CREG-P", provenance=TradeProvenance.PAPER_TRADING,
            axes={axis: dataclasses.replace(obs, regime_id=f"REG-P-{axis.value}", provenance=TradeProvenance.PAPER_TRADING)
                  for axis, obs in composite.axes.items()},
        )
        regime_repo.record_composite(hist)
        regime_repo.record_composite(paper)

        assert len(regime_repo.list_composites(provenance=TradeProvenance.HISTORICAL_SIMULATION)) == 1
        assert len(regime_repo.list_composites(provenance=TradeProvenance.PAPER_TRADING)) == 1
        assert len(regime_repo.list_composites(provenance=TradeProvenance.LIVE_TRADING)) == 0
        engine.close()

    def test_configuration_version_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        regime_repo = DuckDBRegimeRepository(engine)
        composite = _composite()
        regime_repo.record_composite(composite)

        reloaded = regime_repo.get_observation(composite.get(RegimeAxis.TREND).regime_id)
        assert reloaded.configuration_version == composite.get(RegimeAxis.TREND).configuration_version
        assert reloaded.method_version == composite.get(RegimeAxis.TREND).method_version
        assert reloaded.feature_version == composite.get(RegimeAxis.TREND).feature_version
        engine.close()
