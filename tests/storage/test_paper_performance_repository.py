"""Category: Persistence Test (Phase 18) -- save, reload, idempotency,
restart for `PaperPerformanceReport`, mirroring
tests/storage/test_monitoring_repository.py's structure."""

from __future__ import annotations

from datetime import datetime, timezone

from broker.paper.performance import BenchmarkComparison, PaperPerformanceReport
from storage_helpers import new_engine
from trade_journal.enums import TradeProvenance

from storage.paper_performance_repository import (
    DuckDBPaperPerformanceReportRepository,
    InMemoryPaperPerformanceReportRepository,
)


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _report(report_id: str = "PPR-000001", paper_session_id: str = "SESSION-1") -> PaperPerformanceReport:
    return PaperPerformanceReport(
        report_id=report_id, paper_session_id=paper_session_id, evaluated_at=utc(2024, 1, 20),
        period_start=utc(2024, 1, 1), period_end=utc(2024, 1, 20),
        total_return=0.05, cagr=0.9, volatility=0.1, sharpe_ratio=1.2, sortino_ratio=1.5,
        calmar_ratio=None, max_drawdown=-0.02, turnover=0.3, total_transaction_cost=12.5,
        total_slippage=3.1, num_trades=4, win_rate=0.75, avg_trade_return=0.01, realized_pnl=250.0,
        benchmark=BenchmarkComparison(status="BENCHMARK_UNAVAILABLE"),
        configuration_version="cfg-perf-1", provenance=TradeProvenance.PAPER_TRADING,
        strategy_version="strategy-v1", model_version=None, experiment_id=None,
        reasons={"calmar_ratio": "zero_drawdown"},
    )


class TestDuckDBPaperPerformanceReportPersistence:
    def test_record_and_get_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperPerformanceReportRepository(engine)
        report = _report()
        repo.record(report)
        fetched = repo.get(report.report_id)
        assert fetched == report
        engine.close()

    def test_recording_the_same_report_id_twice_is_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperPerformanceReportRepository(engine)
        report = _report()
        repo.record(report)
        repo.record(report)
        assert len(repo.list_for_session(report.paper_session_id)) == 1
        engine.close()

    def test_list_for_session_and_get_latest(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperPerformanceReportRepository(engine)
        r1 = _report(report_id="PPR-1", paper_session_id="SESSION-A")
        r2 = _report(report_id="PPR-2", paper_session_id="SESSION-A")
        other_session = _report(report_id="PPR-3", paper_session_id="SESSION-B")
        repo.record(r1)
        repo.record(r2)
        repo.record(other_session)
        assert len(repo.list_for_session("SESSION-A")) == 2
        assert repo.get_latest_for_session("SESSION-A").report_id == "PPR-2"
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        report = _report()
        DuckDBPaperPerformanceReportRepository(engine).record(report)
        engine.close()

        engine2 = new_engine(tmp_path)
        reloaded = DuckDBPaperPerformanceReportRepository(engine2).get(report.report_id)
        assert reloaded == report
        assert reloaded.reasons == {"calmar_ratio": "zero_drawdown"}
        engine2.close()

    def test_benchmark_unavailable_round_trips_correctly(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperPerformanceReportRepository(engine)
        report = _report()
        repo.record(report)
        fetched = repo.get(report.report_id)
        assert fetched.benchmark.status == "BENCHMARK_UNAVAILABLE"
        assert fetched.benchmark.benchmark_cumulative_return is None
        engine.close()


class TestInMemoryPaperPerformanceReportRepository:
    def test_record_get_and_idempotency(self) -> None:
        repo = InMemoryPaperPerformanceReportRepository()
        report = _report()
        repo.record(report)
        repo.record(report)
        assert repo.get(report.report_id) == report
        assert len(repo.list_for_session(report.paper_session_id)) == 1

    def test_get_latest_for_session_empty_is_none(self) -> None:
        repo = InMemoryPaperPerformanceReportRepository()
        assert repo.get_latest_for_session("nonexistent") is None
