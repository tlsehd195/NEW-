"""Phase 26 point-in-time regression audit (instruction section 9,
CASE 1-5). This file exists to make the audit itself visible and
auditable -- not to duplicate coverage that already exists.

CASE 1 (a corporate action ingested after T must not appear in a query
as of T): already covered --
`tests/data/test_lookahead_guard.py::TestLookaheadGuard::test_corporate_actions_available_in_the_future_are_never_returned`.

CASE 2 (a dividend discovered after T must not change a backtest result
computed as of an earlier T): already covered --
`tests/backtest/test_total_return.py::test_past_points_are_never_rewritten_when_a_later_dividend_is_discovered`.

CASE 3 (a price bar added after T must not change an as-of query result
at an earlier T): already covered --
`tests/data/test_lookahead_guard.py::TestLookaheadGuard::test_bars_available_in_the_future_are_never_returned`.

CASE 4 (universe membership starting after T must not appear at an
earlier T): already covered --
`tests/data/test_lookahead_guard.py::TestLookaheadGuard::test_universe_membership_starting_in_the_future_is_not_yet_a_member`.

CASE 5 (re-running real ingestion -- e.g. extending a real data range
further, exactly what Phase 26 section 3 asks for -- must not
retroactively change an already-established as-of query result at an
earlier T): **genuinely new this phase** -- no existing test exercised
this specific scenario through the real `IngestionRunner`/
`DuckDBDataRepository` path (the existing idempotency tests in
`tests/data/test_provider_ingestion.py` prove re-running ingestion does
not *duplicate* records, but never assert that a *past as-of query
result* is unaffected by a *later* ingestion run that adds genuinely
new, more recent data -- the real-world Phase 26 scenario).
"""

from __future__ import annotations

from helpers import utc
from storage_helpers import new_engine

from data_infra.calendar import US_EQUITY
from data_infra.enums import IngestionStatus
from data_infra.provider import IngestionRunner, MockDataProvider

from storage.data_repository import DuckDBDataRepository


def _raw_record(security_id: str, day: int, close: float, source: str = "mock_provider_v1") -> dict:
    return {
        "security_id": security_id,
        "timestamp": utc(2024, 1, day),
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": 1000.0,
        "available_time": utc(2024, 1, day, 20),
        "ingestion_time": utc(2024, 1, day, 20),
        "source": source,
    }


class TestCase5ReIngestionDoesNotRewriteHistory:
    def test_extending_the_ingested_range_does_not_change_an_earlier_as_of_query(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})

        # First real ingestion run: days 2-5 only (simulates the
        # project's actual current real data state -- a bounded window
        # already ingested).
        first_dataset = {"AAPL": [_raw_record("AAPL", d, 100.0 + d) for d in range(2, 6)]}
        first_provider = MockDataProvider(first_dataset)
        first_runner = IngestionRunner(first_provider, repo)
        first_result = first_runner.run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 10))
        assert first_result.status == IngestionStatus.SUCCESS

        # Establish the as-of result at an early point in time, BEFORE
        # any re-ingestion happens.
        early_as_of = utc(2024, 1, 4, 20)
        before = repo.get_bars("AAPL", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=early_as_of)
        before_snapshot = [(b.timestamp, b.close) for b in before]
        assert before_snapshot == [(utc(2024, 1, 2), 102.0), (utc(2024, 1, 3), 103.0), (utc(2024, 1, 4), 104.0)]

        # Second real ingestion run, from a FRESH IngestionRunner
        # instance against the SAME repository (matching how a real
        # re-run of scripts/ingest_real_market_data.py would work) --
        # extends the range further into days 6-10, exactly the Phase 26
        # "확보 가능한 최대 기간까지" scenario. This must not touch
        # anything already ingested for days 2-5.
        second_dataset = {"AAPL": [_raw_record("AAPL", d, 100.0 + d) for d in range(2, 11)]}
        second_provider = MockDataProvider(second_dataset)
        second_runner = IngestionRunner(second_provider, repo)
        second_result = second_runner.run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 10))
        assert second_result.status == IngestionStatus.SUCCESS
        assert second_result.results[0].bars_ingested == 5  # only the 5 new days (6-10), not the 4 already there

        # The SAME early as-of query, re-run after the extension, must
        # return the byte-identical result -- no retroactive change.
        after = repo.get_bars("AAPL", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=early_as_of)
        after_snapshot = [(b.timestamp, b.close) for b in after]
        assert after_snapshot == before_snapshot

        # And the newly-ingested later days are visible only once a
        # later as_of_time actually reaches them -- the extension is
        # additive, not silently backdated into early_as_of's world.
        later_as_of = utc(2024, 1, 10, 20)
        after_later = repo.get_bars("AAPL", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=later_as_of)
        assert len(after_later) == 9  # days 2 through 10

        engine.close()

    def test_re_ingesting_the_identical_range_twice_does_not_change_an_earlier_as_of_query(self, tmp_path) -> None:
        # The "nothing new, just a retry/re-run" case -- distinct from
        # the extension case above (no new data at all, e.g. a crashed
        # or re-triggered ingestion job re-run over the exact same window).
        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})

        dataset = {"AAPL": [_raw_record("AAPL", d, 100.0 + d) for d in range(2, 6)]}
        as_of = utc(2024, 1, 4, 20)

        provider_1 = MockDataProvider(dataset)
        IngestionRunner(provider_1, repo).run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 10))
        before = [(b.timestamp, b.close) for b in repo.get_bars("AAPL", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=as_of)]

        provider_2 = MockDataProvider(dataset)
        second_result = IngestionRunner(provider_2, repo).run(["AAPL"], utc(2024, 1, 1), utc(2024, 1, 10))
        assert second_result.results[0].bars_ingested == 0  # fully idempotent -- nothing new

        after = [(b.timestamp, b.close) for b in repo.get_bars("AAPL", utc(2024, 1, 1), utc(2024, 1, 10), as_of_time=as_of)]
        assert after == before
        engine.close()
