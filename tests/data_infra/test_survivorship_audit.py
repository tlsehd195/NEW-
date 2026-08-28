"""Tests for `data_infra.universe.audit_survivorship` (Phase 31,
instruction section 28). SYNTHETIC FIXTURE ONLY -- proves the
diagnostic mechanism answers the instruction's ten questions correctly
against known inputs; not a claim about any real US equity dataset
(none exists in this environment)."""

from __future__ import annotations

from datetime import datetime, timezone

from data_infra.universe import (
    SymbolMetadata,
    UniverseDefinition,
    audit_survivorship,
    build_security_masters,
    build_universe_memberships,
)


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestCurrentUniverseOnlyClassification:
    def test_universe_with_no_confirmed_dates_is_classified_current_universe_only(self) -> None:
        universe = UniverseDefinition(
            name="TEST", version="v1", role="RESEARCH", description="test",
            symbols=(SymbolMetadata(symbol="AAPL"), SymbolMetadata(symbol="MSFT")),
        )
        masters = build_security_masters(universe, valid_from=utc(2010, 1, 1))
        memberships = build_universe_memberships(universe, valid_from=utc(2010, 1, 1))

        audit = audit_survivorship(universe, masters, memberships, as_of_time=utc(2024, 1, 1))

        assert audit.classification == "CURRENT-UNIVERSE-ONLY"
        assert audit.total_securities == 2
        assert audit.delisted_count == 0
        assert audit.securities_relying_only_on_ticker_percentage == 100.0


class TestPartiallyMitigatedClassification:
    def test_universe_with_some_confirmed_dates_is_partially_mitigated(self) -> None:
        universe = UniverseDefinition(
            name="TEST", version="v1", role="RESEARCH", description="test",
            symbols=(
                SymbolMetadata(symbol="DELISTED_CO", listed_from=utc(2005, 1, 1), listed_to=utc(2015, 6, 1)),
                SymbolMetadata(symbol="NO_DATES_CO"),
            ),
        )
        masters = build_security_masters(universe, valid_from=utc(2000, 1, 1))
        memberships = build_universe_memberships(universe, valid_from=utc(2000, 1, 1))

        audit = audit_survivorship(universe, masters, memberships, as_of_time=utc(2024, 1, 1))

        assert audit.classification == "PARTIALLY_MITIGATED"
        assert audit.delisted_count == 1
        assert audit.securities_relying_only_on_ticker_percentage == 50.0

    def test_universe_with_all_confirmed_dates_and_no_collisions_is_still_only_partially_mitigated(self) -> None:
        """Even a "perfect" input (every symbol has confirmed dates, no
        collision) must NOT be classified FULLY_SUPPORTED -- this
        project's own security_id == ticker limitation (instruction
        section 36: never overclaim) keeps it at PARTIALLY_MITIGATED."""
        universe = UniverseDefinition(
            name="TEST", version="v1", role="RESEARCH", description="test",
            symbols=(
                SymbolMetadata(symbol="A", listed_from=utc(2005, 1, 1), listed_to=utc(2015, 6, 1)),
                SymbolMetadata(symbol="B", listed_from=utc(2005, 1, 1)),
            ),
        )
        masters = build_security_masters(universe, valid_from=utc(2000, 1, 1))
        memberships = build_universe_memberships(universe, valid_from=utc(2000, 1, 1))

        audit = audit_survivorship(universe, masters, memberships, as_of_time=utc(2024, 1, 1))

        assert audit.classification == "PARTIALLY_MITIGATED"
        assert audit.securities_relying_only_on_ticker_percentage == 0.0
        assert "FULLY_SUPPORTED" not in audit.classification


class TestTickerCollisionAffectsClassification:
    def test_genuine_collision_among_fully_dated_symbols_is_reported_and_flagged(self) -> None:
        from data_infra.enums import InstrumentType, SecurityStatus
        from data_infra.models import SecurityMaster

        overlapping_a = SecurityMaster(
            security_id="A", ticker="DUPTICK", exchange="NYSE", currency="USD",
            company_id="COMPANY-A", instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2005, 1, 1), valid_to=utc(2015, 1, 1), status=SecurityStatus.DELISTED,
        )
        overlapping_b = SecurityMaster(
            security_id="B", ticker="DUPTICK", exchange="NASDAQ", currency="USD",
            company_id="COMPANY-B", instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2010, 1, 1), valid_to=None, status=SecurityStatus.ACTIVE,
        )
        universe = UniverseDefinition(
            name="TEST", version="v1", role="RESEARCH", description="test",
            symbols=(
                SymbolMetadata(symbol="A", listed_from=utc(2005, 1, 1), listed_to=utc(2015, 1, 1)),
                SymbolMetadata(symbol="B", listed_from=utc(2010, 1, 1)),
            ),
        )
        audit = audit_survivorship(universe, [overlapping_a, overlapping_b], [], as_of_time=utc(2024, 1, 1))

        assert audit.ticker_collision_count == 1
        assert audit.classification == "PARTIALLY_MITIGATED"
        assert "collision" in audit.classification_reason.lower()


class TestNoOverclaim:
    def test_permanent_id_percentage_is_always_100_but_documented_as_structural_not_provider_confirmed(self) -> None:
        universe = UniverseDefinition(
            name="TEST", version="v1", role="RESEARCH", description="test",
            symbols=(SymbolMetadata(symbol="AAPL"),),
        )
        masters = build_security_masters(universe, valid_from=utc(2010, 1, 1))
        memberships = build_universe_memberships(universe, valid_from=utc(2010, 1, 1))
        audit = audit_survivorship(universe, masters, memberships, as_of_time=utc(2024, 1, 1))

        assert audit.permanent_id_percentage == 100.0
        # This is a structural guarantee (security_id always exists),
        # not evidence of survivorship mitigation -- the classification
        # must not be upgraded merely because this number is 100.
        assert audit.classification != "FULLY_SUPPORTED"

    def test_renamed_or_merged_count_is_never_fabricated_stays_zero_when_data_source_cannot_confirm_it(self) -> None:
        universe = UniverseDefinition(
            name="TEST", version="v1", role="RESEARCH", description="test",
            symbols=(SymbolMetadata(symbol="AAPL", listed_from=utc(2005, 1, 1), listed_to=utc(2015, 1, 1)),),
        )
        masters = build_security_masters(universe, valid_from=utc(2000, 1, 1))
        memberships = build_universe_memberships(universe, valid_from=utc(2000, 1, 1))
        audit = audit_survivorship(universe, masters, memberships, as_of_time=utc(2024, 1, 1))

        # build_security_masters only ever assigns DELISTED (never
        # RENAMED/MERGED, Phase 29 Decision 2) when it lacks a reason
        # code -- so this must be 0, never guessed.
        assert audit.renamed_or_merged_count == 0
        assert audit.delisted_count == 1
