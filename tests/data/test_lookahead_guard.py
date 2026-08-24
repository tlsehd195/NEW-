"""Category 7: Look-ahead test.

Verifies the structural guard described in
docs/specifications/PHASE-1-data-infrastructure.md section 15 and
ADR-0004: no DataRepository query can ever return a record whose
available_time is after the requested as_of_time, across every
as-of-aware method (bars, corporate actions, benchmark, universe).
"""

from __future__ import annotations

from helpers import make_provenance, utc

from data_infra.enums import BenchmarkReturnType, CorporateActionType
from data_infra.models import BenchmarkPoint, CorporateAction, PriceBar, UniverseMembership
from data_infra.repository import InMemoryDataRepository


class TestLookaheadGuard:
    def test_bars_available_in_the_future_are_never_returned(self) -> None:
        future_bar = PriceBar(
            security_id="SEC-AAA",
            timestamp=utc(2024, 1, 2),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=1000.0,
            available_time=utc(2024, 6, 1),  # far in the future relative to as_of_time below
            ingestion_time=utc(2024, 6, 1),
            provenance=make_provenance(),
        )
        repo = InMemoryDataRepository(bars=[future_bar])
        result = repo.get_bars(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 12, 31), as_of_time=utc(2024, 1, 15)
        )
        assert result == []

    def test_corporate_actions_available_in_the_future_are_never_returned(self) -> None:
        future_action = CorporateAction(
            security_id="SEC-AAA",
            action_type=CorporateActionType.SPLIT,
            available_time=utc(2024, 6, 1),
            ingestion_time=utc(2024, 6, 1),
            provenance=make_provenance(),
            event_time=utc(2024, 1, 10),
            effective_time=utc(2024, 1, 10),
        )
        repo = InMemoryDataRepository(corporate_actions=[future_action])
        result = repo.get_corporate_actions(
            "SEC-AAA", utc(2024, 1, 1), utc(2024, 12, 31), as_of_time=utc(2024, 1, 15)
        )
        assert result == []

    def test_benchmark_points_available_in_the_future_are_never_returned(self) -> None:
        future_point = BenchmarkPoint(
            benchmark_id="SP500",
            timestamp=utc(2024, 1, 2),
            level=4700.0,
            return_type=BenchmarkReturnType.PRICE_RETURN,
            currency="USD",
            available_time=utc(2024, 6, 1),
            ingestion_time=utc(2024, 6, 1),
            provenance=make_provenance(),
        )
        repo = InMemoryDataRepository(benchmarks=[future_point])
        result = repo.get_benchmark(
            "SP500", utc(2024, 1, 1), utc(2024, 12, 31), as_of_time=utc(2024, 1, 15)
        )
        assert result == []

    def test_universe_membership_starting_in_the_future_is_not_yet_a_member(self) -> None:
        membership = UniverseMembership(
            security_id="SEC-AAA", universe="SP500", valid_from=utc(2024, 6, 1)
        )
        repo = InMemoryDataRepository(universe_memberships=[membership])
        result = repo.get_universe("US", "SP500", as_of_time=utc(2024, 1, 15))
        assert "SEC-AAA" not in result

    def test_no_lookahead_leak_even_when_a_wider_time_range_is_requested(self) -> None:
        # A caller widening the [start, end] window must not be able to
        # "smuggle" future-available data through — the as_of_time filter
        # applies independently of the requested window width.
        near_bar = PriceBar(
            security_id="SEC-AAA",
            timestamp=utc(2024, 1, 2),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=1000.0,
            available_time=utc(2024, 1, 2, 20),
            ingestion_time=utc(2024, 1, 2, 20),
            provenance=make_provenance(source_record_id="near"),
        )
        far_future_bar = PriceBar(
            security_id="SEC-AAA",
            timestamp=utc(2024, 1, 3),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=1000.0,
            available_time=utc(2030, 1, 1),
            ingestion_time=utc(2030, 1, 1),
            provenance=make_provenance(source_record_id="far-future"),
        )
        repo = InMemoryDataRepository(bars=[near_bar, far_future_bar])
        result = repo.get_bars(
            "SEC-AAA", utc(2000, 1, 1), utc(2040, 1, 1), as_of_time=utc(2024, 1, 2, 21)
        )
        assert result == [near_bar]
