"""Category 8: Idempotent ingestion test.
Category 9: Retry test.
Category 10: Partial failure test.
Category 11: Checkpoint recovery test.

See docs/specifications/PHASE-1-data-infrastructure.md sections 21-27
and ADR-0005.
"""

from __future__ import annotations

from helpers import utc

from data_infra.enums import IngestionStatus
from data_infra.provider import IngestionCheckpoint, IngestionRunner, MockDataProvider
from data_infra.repository import InMemoryDataRepository


def _raw_record(security_id: str, day: int, source: str = "mock_provider_v1") -> dict:
    return {
        "security_id": security_id,
        "timestamp": utc(2024, 1, day),
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 102.0,
        "volume": 1000.0,
        "available_time": utc(2024, 1, day, 20),
        "ingestion_time": utc(2024, 1, day, 20),
        "source": source,
    }


def _no_sleep(_seconds: float) -> None:
    return None  # keep retry tests fast — no real waiting


class TestIdempotentIngestion:
    def test_running_ingestion_twice_does_not_duplicate_bars(self) -> None:
        dataset = {"AAA": [_raw_record("AAA", 2), _raw_record("AAA", 3)]}
        provider = MockDataProvider(dataset)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, sleep_fn=_no_sleep)

        first = runner.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))
        second = runner.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))

        assert first.status == IngestionStatus.SUCCESS
        assert first.results[0].bars_ingested == 2
        assert second.status == IngestionStatus.SUCCESS
        assert second.results[0].bars_ingested == 0  # nothing new — already ingested
        assert len(repo.all_bars()) == 2  # not 4

    def test_idempotency_holds_across_separate_runner_instances(self) -> None:
        dataset = {"AAA": [_raw_record("AAA", 2)]}
        repo = InMemoryDataRepository()

        runner1 = IngestionRunner(MockDataProvider(dataset), repo, sleep_fn=_no_sleep)
        runner1.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))

        # A fresh runner against the same repository must still see the
        # existing data and not duplicate it (idempotency seeded from
        # repository state, not runner-instance memory).
        runner2 = IngestionRunner(MockDataProvider(dataset), repo, sleep_fn=_no_sleep)
        result2 = runner2.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))

        assert result2.results[0].bars_ingested == 0
        assert len(repo.all_bars()) == 1


class TestRetry:
    def test_transient_failure_recovers_within_retry_policy(self) -> None:
        dataset = {"AAA": [_raw_record("AAA", 2)]}
        provider = MockDataProvider(dataset, transient_failures={"AAA": 2})
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, max_retries=3, sleep_fn=_no_sleep)

        result = runner.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))

        assert result.status == IngestionStatus.SUCCESS
        assert result.results[0].status == IngestionStatus.SUCCESS
        assert provider.call_count["AAA"] == 3  # 2 failures + 1 success
        assert len(repo.all_bars()) == 1

    def test_exceeding_retry_budget_fails_that_symbol(self) -> None:
        dataset = {"AAA": [_raw_record("AAA", 2)]}
        provider = MockDataProvider(dataset, transient_failures={"AAA": 10})
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, max_retries=2, sleep_fn=_no_sleep)

        result = runner.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))

        assert result.status == IngestionStatus.FAILED
        assert result.results[0].status == IngestionStatus.FAILED
        assert result.results[0].error is not None
        assert len(repo.all_bars()) == 0


class TestPartialFailure:
    def test_one_failed_symbol_among_several_yields_partial_success(self) -> None:
        dataset = {
            "AAA": [_raw_record("AAA", 2)],
            "BBB": [_raw_record("BBB", 2)],
            "CCC": [_raw_record("CCC", 2)],
        }
        provider = MockDataProvider(dataset, permanent_failures={"BBB"})
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, sleep_fn=_no_sleep)

        result = runner.run(["AAA", "BBB", "CCC"], utc(2024, 1, 1), utc(2024, 1, 10))

        assert result.status == IngestionStatus.PARTIAL_SUCCESS
        by_symbol = {r.security_id: r for r in result.results}
        assert by_symbol["AAA"].status == IngestionStatus.SUCCESS
        assert by_symbol["BBB"].status == IngestionStatus.FAILED
        assert by_symbol["BBB"].error is not None
        assert by_symbol["CCC"].status == IngestionStatus.SUCCESS
        assert len(result.failed) == 1

    def test_all_symbols_failing_yields_failed_status(self) -> None:
        dataset = {"AAA": [_raw_record("AAA", 2)]}
        provider = MockDataProvider(dataset, permanent_failures={"AAA"})
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, sleep_fn=_no_sleep)

        result = runner.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10))
        assert result.status == IngestionStatus.FAILED


class TestCheckpointRecovery:
    def test_resumed_run_skips_already_completed_symbols(self) -> None:
        dataset = {
            "AAA": [_raw_record("AAA", 2)],
            "BBB": [_raw_record("BBB", 2)],
            "CCC": [_raw_record("CCC", 2)],
        }
        provider = MockDataProvider(dataset)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, sleep_fn=_no_sleep)

        # Simulate a first run that only got through AAA and BBB before
        # being interrupted.
        checkpoint = IngestionCheckpoint(completed_security_ids={"AAA", "BBB"})

        result = runner.run(["AAA", "BBB", "CCC"], utc(2024, 1, 1), utc(2024, 1, 10), checkpoint=checkpoint)

        # Only CCC should have actually been fetched.
        assert provider.call_count.get("AAA", 0) == 0
        assert provider.call_count.get("BBB", 0) == 0
        assert provider.call_count.get("CCC", 0) == 1
        assert len(result.results) == 1
        assert result.results[0].security_id == "CCC"
        assert result.checkpoint.completed_security_ids == {"AAA", "BBB", "CCC"}

    def test_checkpoint_accumulates_across_multiple_resumed_runs(self) -> None:
        dataset = {"AAA": [_raw_record("AAA", 2)], "BBB": [_raw_record("BBB", 2)]}
        provider = MockDataProvider(dataset)
        repo = InMemoryDataRepository()
        runner = IngestionRunner(provider, repo, sleep_fn=_no_sleep)

        checkpoint = IngestionCheckpoint()
        result1 = runner.run(["AAA"], utc(2024, 1, 1), utc(2024, 1, 10), checkpoint=checkpoint)
        result2 = runner.run(
            ["AAA", "BBB"], utc(2024, 1, 1), utc(2024, 1, 10), checkpoint=result1.checkpoint
        )

        assert provider.call_count["AAA"] == 1  # not re-fetched in the second run
        assert provider.call_count["BBB"] == 1
        assert result2.checkpoint.completed_security_ids == {"AAA", "BBB"}
