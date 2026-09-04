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
    RESEARCH_UNIVERSE_STAGE2,
    RESEARCH_UNIVERSE_STAGE3,
    RESEARCH_UNIVERSE_STAGE4,
    SymbolMetadata,
    UniverseDefinition,
    _real_symbol_metadata,
    _SP500_PIT_CONFIRMED_LISTED_FROM,
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


class TestResearchUniverseStage2:
    """Stage 2 (confirmed Tiingo free-tier limits: 50 req/hour,
    1,000 req/day, 2.00 GB/month) -- addresses mega-cap-tech
    concentration risk, deliberately NOT survivorship bias."""

    def test_stage2_contains_all_of_pilot_universe(self) -> None:
        assert set(PILOT_UNIVERSE_V1.symbol_ids) <= set(RESEARCH_UNIVERSE_STAGE2.symbol_ids)

    def test_stage2_adds_exactly_24_new_symbols(self) -> None:
        new_symbols = set(RESEARCH_UNIVERSE_STAGE2.symbol_ids) - set(PILOT_UNIVERSE_V1.symbol_ids)
        assert len(new_symbols) == 24

    def test_stage2_has_no_duplicate_symbols(self) -> None:
        ids = RESEARCH_UNIVERSE_STAGE2.symbol_ids
        assert len(ids) == len(set(ids))

    def test_stage2_benchmark_symbol_never_a_member(self) -> None:
        assert BENCHMARK_SYMBOL not in RESEARCH_UNIVERSE_STAGE2.symbol_ids

    def test_stage2_is_distinct_version_from_stage1(self) -> None:
        assert RESEARCH_UNIVERSE_STAGE2.version != RESEARCH_UNIVERSE_STAGE1.version
        assert RESEARCH_UNIVERSE_STAGE2.name == RESEARCH_UNIVERSE_STAGE1.name  # same named universe, later stage

    def test_stage2_symbols_carry_no_listed_to_and_only_real_confirmed_listed_from(self) -> None:
        """Stage 2 is a wider hand-curated list, not survivorship-bias
        mitigation on its own -- `listed_to` stays unconfirmed for
        every entry (no symbol has actually left the index), and
        `listed_from` is real only for the subset ADR-0061's real
        S&P 500 point-in-time data actually confirmed (never a
        fabricated value for the rest)."""
        for entry in RESEARCH_UNIVERSE_STAGE2.symbols:
            assert entry.listed_to is None
            assert entry.source == "manual_curation"
            if entry.symbol in _SP500_PIT_CONFIRMED_LISTED_FROM:
                assert entry.listed_from is not None
            else:
                assert entry.listed_from is None

    def test_stage2_request_budget_fits_one_hourly_window(self) -> None:
        """24 new symbols x 2 requests/symbol (price + corporate
        actions, `scripts/ingest_real_market_data.py`) must fit under
        the confirmed 50-requests/hour Tiingo free-tier cap."""
        new_symbol_count = len(set(RESEARCH_UNIVERSE_STAGE2.symbol_ids) - set(PILOT_UNIVERSE_V1.symbol_ids))
        assert new_symbol_count * 2 <= 50


class TestResearchUniverseStage3:
    """Stage 3 -- built per the user's explicit direction after 9
    hypotheses tested against Stage 2's 40 symbols all failed to reach
    CANDIDATE. Addresses cross-sectional breadth, deliberately NOT
    survivorship bias -- same discipline as Stage 2."""

    def test_stage3_contains_all_of_stage2(self) -> None:
        assert set(RESEARCH_UNIVERSE_STAGE2.symbol_ids) <= set(RESEARCH_UNIVERSE_STAGE3.symbol_ids)

    def test_stage3_adds_exactly_24_new_symbols(self) -> None:
        new_symbols = set(RESEARCH_UNIVERSE_STAGE3.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE2.symbol_ids)
        assert len(new_symbols) == 24

    def test_stage3_has_no_duplicate_symbols(self) -> None:
        ids = RESEARCH_UNIVERSE_STAGE3.symbol_ids
        assert len(ids) == len(set(ids))

    def test_stage3_benchmark_symbol_never_a_member(self) -> None:
        assert BENCHMARK_SYMBOL not in RESEARCH_UNIVERSE_STAGE3.symbol_ids

    def test_stage3_is_distinct_version_from_stage2(self) -> None:
        assert RESEARCH_UNIVERSE_STAGE3.version != RESEARCH_UNIVERSE_STAGE2.version
        assert RESEARCH_UNIVERSE_STAGE3.name == RESEARCH_UNIVERSE_STAGE2.name  # same named universe, later stage

    def test_stage3_symbols_carry_no_listed_to_and_only_real_confirmed_listed_from(self) -> None:
        """Same real-vs-honest-None split as Stage 2's own test above."""
        for entry in RESEARCH_UNIVERSE_STAGE3.symbols:
            assert entry.listed_to is None
            assert entry.source == "manual_curation"
            if entry.symbol in _SP500_PIT_CONFIRMED_LISTED_FROM:
                assert entry.listed_from is not None
            else:
                assert entry.listed_from is None

    def test_stage3_request_budget_fits_one_hourly_window(self) -> None:
        """24 new symbols x 2 requests/symbol must fit under the
        confirmed 50-requests/hour Tiingo free-tier cap, same margin as
        Stage 2's own addition."""
        new_symbol_count = len(set(RESEARCH_UNIVERSE_STAGE3.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE2.symbol_ids))
        assert new_symbol_count * 2 <= 50


class TestResearchUniverseStage4:
    """Stage 4 -- Session 36's "전부 다 진행하는건?" item #3, deepening
    the 5 sectors Stage 3 leaves thinnest (Energy specifically was the
    diagnosed root cause of the SLB concentration artifact behind
    size_score's walk-forward CANDIDATE result). Same discipline as
    Stage 2/Stage 3 -- concentration risk only, NOT survivorship bias."""

    def test_stage4_contains_all_of_stage3(self) -> None:
        assert set(RESEARCH_UNIVERSE_STAGE3.symbol_ids) <= set(RESEARCH_UNIVERSE_STAGE4.symbol_ids)

    def test_stage4_adds_exactly_24_new_symbols(self) -> None:
        new_symbols = set(RESEARCH_UNIVERSE_STAGE4.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE3.symbol_ids)
        assert len(new_symbols) == 24

    def test_stage4_has_no_duplicate_symbols(self) -> None:
        ids = RESEARCH_UNIVERSE_STAGE4.symbol_ids
        assert len(ids) == len(set(ids))

    def test_stage4_benchmark_symbol_never_a_member(self) -> None:
        assert BENCHMARK_SYMBOL not in RESEARCH_UNIVERSE_STAGE4.symbol_ids

    def test_stage4_is_distinct_version_from_stage3(self) -> None:
        assert RESEARCH_UNIVERSE_STAGE4.version != RESEARCH_UNIVERSE_STAGE3.version
        assert RESEARCH_UNIVERSE_STAGE4.name == RESEARCH_UNIVERSE_STAGE3.name  # same named universe, later stage

    def test_stage4_symbols_carry_no_listed_to_and_only_real_confirmed_listed_from(self) -> None:
        """Same real-vs-honest-None split as Stage 2's own test above."""
        for entry in RESEARCH_UNIVERSE_STAGE4.symbols:
            assert entry.listed_to is None
            assert entry.source == "manual_curation"
            if entry.symbol in _SP500_PIT_CONFIRMED_LISTED_FROM:
                assert entry.listed_from is not None
            else:
                assert entry.listed_from is None

    def test_stage4_request_budget_fits_one_hourly_window(self) -> None:
        """24 new symbols x 2 requests/symbol must fit under the
        confirmed 50-requests/hour Tiingo free-tier cap, same margin as
        Stage 2's and Stage 3's own additions."""
        new_symbol_count = len(set(RESEARCH_UNIVERSE_STAGE4.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE3.symbol_ids))
        assert new_symbol_count * 2 <= 50

    def test_stage4_new_symbols_do_not_collide_with_any_prior_stage(self) -> None:
        # A sanity guard distinct from the plain duplicate check above --
        # confirms the 24 new tickers were genuinely NEW additions, not
        # an accidental re-listing of an existing symbol under this
        # stage's own tuple (which the duplicate check alone would not
        # catch, since UniverseDefinition builds via concatenation).
        new_symbols = set(RESEARCH_UNIVERSE_STAGE4.symbol_ids) - set(RESEARCH_UNIVERSE_STAGE3.symbol_ids)
        assert len(new_symbols) == len(RESEARCH_UNIVERSE_STAGE4.symbol_ids) - len(RESEARCH_UNIVERSE_STAGE3.symbol_ids)


class TestRealSymbolMetadata:
    """Session 36 (ADR-0058) -- `_real_symbol_metadata` is the one
    place `SymbolMetadata.sector`/`exchange` are populated from real,
    provider-sourced SEC EDGAR data rather than left `None`."""

    def test_a_resolved_symbol_gets_its_real_sector_and_exchange(self) -> None:
        metadata = _real_symbol_metadata("MSFT")
        assert metadata.sector == "Services-Prepackaged Software"
        assert metadata.exchange == "Nasdaq"
        assert metadata.symbol == "MSFT"

    def test_an_unresolved_symbol_gets_the_honest_all_none_default(self) -> None:
        # AVB's real fetch run did not resolve a CIK -- never fabricated.
        metadata = _real_symbol_metadata("AVB")
        assert metadata.sector is None
        assert metadata.exchange is None

    def test_a_symbol_never_fetched_at_all_also_gets_the_honest_default(self) -> None:
        metadata = _real_symbol_metadata("NOT_A_REAL_SYMBOL_XYZ")
        assert metadata.sector is None
        assert metadata.exchange is None

    def test_a_symbol_with_a_confirmed_sector_but_no_confirmed_exchange_leaves_exchange_none(self) -> None:
        # XOM's real fetch resolved a sector but the exchanges list was
        # empty that run -- exchange must stay None, not fabricated.
        metadata = _real_symbol_metadata("XOM")
        assert metadata.sector == "Petroleum Refining"
        assert metadata.exchange is None

    def test_a_symbol_with_a_confirmed_sp500_pit_join_date_gets_a_real_listed_from(self) -> None:
        # ADR-0061: an independent real data source from sector/exchange.
        metadata = _real_symbol_metadata("TSLA")
        assert metadata.listed_from == datetime(2020, 12, 21, tzinfo=timezone.utc)

    def test_a_symbol_left_censored_in_the_sp500_pit_dataset_leaves_listed_from_none(self) -> None:
        # AAPL was already present in the source dataset's very first
        # snapshot -- true join date unknown, never fabricated.
        metadata = _real_symbol_metadata("AAPL")
        assert metadata.listed_from is None

    def test_sector_exchange_and_listed_from_are_independently_populated(self) -> None:
        # AVB has no real sector/exchange (unresolved CIK) but DOES have
        # a real confirmed listed_from -- the two data sources must not
        # be coupled to each other.
        metadata = _real_symbol_metadata("AVB")
        assert metadata.sector is None
        assert metadata.exchange is None
        assert metadata.listed_from == datetime(2007, 1, 10, tzinfo=timezone.utc)


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
    def test_pilot_universe_market_cap_bucket_and_listed_to_are_still_unconfirmed(self) -> None:
        """market_cap_bucket has no real data source this project has
        ever integrated -- stays None unconditionally. listed_to stays
        None too -- no PILOT_UNIVERSE_V1 symbol has actually left the
        S&P 500 (ADR-0061)."""
        for entry in PILOT_UNIVERSE_V1.symbols:
            assert entry.market_cap_bucket is None
            assert entry.listed_to is None

    def test_pilot_universe_listed_from_is_now_real_sp500_pit_data_where_resolved(self) -> None:
        """Session 36 continued (ADR-0061): listed_from is no longer
        unconditionally None -- real for symbols ADR-0061's real S&P
        500 point-in-time data actually confirmed, still honestly None
        for the rest (e.g. AAPL, present in the source dataset's very
        first snapshot -- true join date unknown, never fabricated)."""
        by_symbol = {s.symbol: s for s in PILOT_UNIVERSE_V1.symbols}
        assert by_symbol["NVDA"].listed_from == datetime(2001, 11, 30, tzinfo=timezone.utc)
        assert by_symbol["AAPL"].listed_from is None

    def test_pilot_universe_sector_is_now_real_sec_edgar_data_where_resolved(self) -> None:
        """Session 36 (ADR-0058): `sector`/`exchange` are no longer
        unconditionally None -- `_real_symbol_metadata` populates them
        from real, provider-sourced SEC EDGAR SIC data for every symbol
        this project's fetch run actually resolved, PILOT_UNIVERSE_V1's
        entries included (they are the same real companies Stage 4's
        real fetch also covers, just referenced from a different
        UniverseDefinition -- the underlying fact does not change with
        which definition happens to list the symbol)."""
        by_symbol = {s.symbol: s for s in PILOT_UNIVERSE_V1.symbols}
        assert by_symbol["AAPL"].sector == "Electronic Computers"
        assert by_symbol["AAPL"].exchange == "Nasdaq"
        # XOM's real fetch resolved a sector but not an exchange that
        # run -- exchange stays honestly None, not fabricated.
        assert by_symbol["XOM"].sector == "Petroleum Refining"
        assert by_symbol["XOM"].exchange is None


class TestConverters:
    def test_build_universe_memberships_uses_supplied_valid_from(self) -> None:
        memberships = build_universe_memberships(PILOT_UNIVERSE_V1, valid_from=utc(2024, 1, 1))
        assert len(memberships) == len(PILOT_UNIVERSE_V1.symbols)
        # AAPL has no real, provider-confirmed listed_from (ADR-0061) --
        # it must fall back to the caller-supplied valid_from.
        by_id = {m.security_id: m for m in memberships}
        assert by_id["AAPL"].valid_from == utc(2024, 1, 1)
        # NVDA DOES have a real, provider-confirmed listed_from that
        # predates 2024-01-01 -- the converter must prefer it over the
        # caller-supplied fallback (Phase 29's own `s.listed_from or
        # valid_from` precedent, unchanged by this ADR).
        assert by_id["NVDA"].valid_from == datetime(2001, 11, 30, tzinfo=timezone.utc)
        assert all(m.universe == "PILOT_UNIVERSE" for m in memberships)
        assert {m.security_id for m in memberships} == set(PILOT_UNIVERSE_V1.symbol_ids)

    def test_build_security_masters_uses_unknown_sentinel_only_for_symbols_with_no_confirmed_exchange(self) -> None:
        records = build_security_masters(PILOT_UNIVERSE_V1, valid_from=utc(2024, 1, 1))
        assert len(records) == len(PILOT_UNIVERSE_V1.symbols)
        by_id = {r.security_id: r for r in records}
        # AAPL now has a real, provider-confirmed exchange (Session 36,
        # ADR-0058) -- the converter must use it, not the sentinel.
        assert by_id["AAPL"].exchange == "Nasdaq"
        # XOM's real fetch resolved a sector but not an exchange --
        # still honestly UNKNOWN, not fabricated.
        assert by_id["XOM"].exchange == "UNKNOWN"
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
