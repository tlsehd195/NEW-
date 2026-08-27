"""Category: Universe architecture (Phase 24, instruction sections 3/4).
`UniverseDefinition`/`SymbolMetadata` validation, and the converters
into `UniverseMembership`/`SecurityMaster` -- Phase 1's own
point-in-time-safe persistence mechanism, unmodified, just newly
populated."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data_infra.enums import SecurityStatus
from data_infra.universe import (
    BENCHMARK_SYMBOL,
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE1,
    SymbolMetadata,
    UniverseDefinition,
    build_security_masters,
    build_universe_memberships,
)


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestPilotUniversePreserved:
    def test_pilot_universe_has_the_phase22_symbols(self) -> None:
        expected = {
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
            "JPM", "V", "MA", "COST", "WMT", "JNJ", "XOM",
        }
        assert set(PILOT_UNIVERSE_V1.symbol_ids) == expected

    def test_benchmark_symbol_never_a_universe_member(self) -> None:
        assert BENCHMARK_SYMBOL not in PILOT_UNIVERSE_V1.symbol_ids
        assert BENCHMARK_SYMBOL not in RESEARCH_UNIVERSE_STAGE1.symbol_ids

    def test_pilot_universe_role_and_version(self) -> None:
        assert PILOT_UNIVERSE_V1.role == "PILOT"
        assert PILOT_UNIVERSE_V1.version == "v1"

    def test_research_universe_is_a_distinct_named_universe(self) -> None:
        assert RESEARCH_UNIVERSE_STAGE1.name != PILOT_UNIVERSE_V1.name
        assert RESEARCH_UNIVERSE_STAGE1.role == "RESEARCH"


class TestUniverseDefinitionValidation:
    def test_rejects_empty_symbols(self) -> None:
        with pytest.raises(ValueError):
            UniverseDefinition(name="X", version="v1", role="RESEARCH", description="d", symbols=())

    def test_rejects_duplicate_symbol(self) -> None:
        with pytest.raises(ValueError):
            UniverseDefinition(
                name="X", version="v1", role="PILOT", description="d",
                symbols=(SymbolMetadata("AAPL"), SymbolMetadata("AAPL")),
            )

    def test_rejects_benchmark_symbol_as_member(self) -> None:
        with pytest.raises(ValueError):
            UniverseDefinition(
                name="X", version="v1", role="PILOT", description="d",
                symbols=(SymbolMetadata("AAPL"), SymbolMetadata(BENCHMARK_SYMBOL)),
            )

    def test_rejects_invalid_role(self) -> None:
        with pytest.raises(ValueError):
            UniverseDefinition(name="X", version="v1", role="BENCHMARK", description="d", symbols=(SymbolMetadata("AAPL"),))

    def test_symbol_metadata_rejects_empty_symbol(self) -> None:
        with pytest.raises(ValueError):
            SymbolMetadata(symbol="")


class TestSymbolMetadataHonesty:
    def test_pilot_universe_metadata_fields_are_unconfirmed_by_default(self) -> None:
        """Every PILOT_UNIVERSE_V1 entry must leave exchange/sector/
        market_cap_bucket/listed_from/listed_to as None -- this session
        never received a real provider response confirming any of
        them, and the module's own discipline forbids filling these in
        from general knowledge."""
        for entry in PILOT_UNIVERSE_V1.symbols:
            assert entry.exchange is None
            assert entry.sector is None
            assert entry.market_cap_bucket is None
            assert entry.listed_from is None
            assert entry.listed_to is None


class TestConverters:
    def test_build_universe_memberships_uses_supplied_valid_from(self) -> None:
        memberships = build_universe_memberships(PILOT_UNIVERSE_V1, valid_from=utc(2024, 1, 1))
        assert len(memberships) == len(PILOT_UNIVERSE_V1.symbols)
        assert all(m.valid_from == utc(2024, 1, 1) for m in memberships)
        assert all(m.universe == "PILOT_UNIVERSE" for m in memberships)
        assert {m.security_id for m in memberships} == set(PILOT_UNIVERSE_V1.symbol_ids)

    def test_build_security_masters_uses_unknown_sentinel_for_unconfirmed_exchange(self) -> None:
        records = build_security_masters(PILOT_UNIVERSE_V1, valid_from=utc(2024, 1, 1))
        assert len(records) == len(PILOT_UNIVERSE_V1.symbols)
        assert all(r.exchange == "UNKNOWN" for r in records)
        assert all(r.status == SecurityStatus.ACTIVE for r in records)
        assert all(r.currency == "USD" for r in records)

    def test_build_security_masters_uses_confirmed_exchange_when_present(self) -> None:
        """If a future universe DOES carry confirmed metadata, the
        converter must use it rather than the UNKNOWN sentinel."""
        custom = UniverseDefinition(
            name="CUSTOM", version="v1", role="RESEARCH", description="d",
            symbols=(SymbolMetadata(symbol="XYZ", exchange="NYSE"),),
        )
        records = build_security_masters(custom, valid_from=utc(2024, 1, 1))
        assert records[0].exchange == "NYSE"

    def test_converters_are_deterministic(self) -> None:
        a = build_universe_memberships(PILOT_UNIVERSE_V1, valid_from=utc(2024, 1, 1))
        b = build_universe_memberships(PILOT_UNIVERSE_V1, valid_from=utc(2024, 1, 1))
        assert a == b


class TestPointInTimeIntegration:
    """A membership built with a later `valid_from` must not appear in
    an as_of query for an earlier time -- this is Phase 1's existing
    `UniverseMembership.is_member_at` invariant, exercised here through
    THIS module's own converter to confirm the Phase 24 population path
    inherits it correctly rather than accidentally bypassing it."""

    def test_membership_with_later_valid_from_does_not_leak_into_earlier_as_of_query(self) -> None:
        from data_infra.repository import InMemoryDataRepository

        early_universe = UniverseDefinition(
            name="EARLY", version="v1", role="RESEARCH", description="d", symbols=(SymbolMetadata("AAPL"),)
        )
        late_universe = UniverseDefinition(
            name="EARLY", version="v1", role="RESEARCH", description="d", symbols=(SymbolMetadata("MSFT"),)
        )
        memberships = build_universe_memberships(early_universe, valid_from=utc(2024, 1, 1))
        memberships += build_universe_memberships(late_universe, valid_from=utc(2024, 6, 1))

        repo = InMemoryDataRepository(universe_memberships=memberships)

        early_query = repo.get_universe("US_EQUITY", "EARLY", as_of_time=utc(2024, 3, 1))
        assert "AAPL" in early_query
        assert "MSFT" not in early_query  # not yet a member as of March

        late_query = repo.get_universe("US_EQUITY", "EARLY", as_of_time=utc(2024, 7, 1))
        assert "AAPL" in late_query
        assert "MSFT" in late_query
