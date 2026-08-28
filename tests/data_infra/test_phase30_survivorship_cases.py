"""Phase 30 survivorship-bias regression tests, literally traceable to
instruction section 8's CASE A-G list. SYNTHETIC FIXTURE ONLY -- these
prove the point-in-time-safe security-identity/universe-membership
mechanism holds against the instruction's own worked cases; they are
not a claim about real US equity data (none exists in this
environment -- real ingestion remains BLOCKED_BY_ENVIRONMENT, see
docs/research/STRATEGY-VALIDATION-REPORT.md's Phase 30 Addendum).

The underlying mechanism (`SecurityMaster`/`UniverseMembership`
`valid_from`/`valid_to`, `DataRepository.get_universe(as_of_time=...)`)
is unchanged from Phase 1/29 -- already exercised generically by
`tests/data_infra/test_phase29_survivorship_aware_universe.py`. This
file adds no new mechanism; it exists purely so a future reviewer can
map each of instruction section 8's seven named cases to exactly one
test by name, using the instruction's own 2010 framing rather than the
2015/2018/2020 dates Phase 29 happened to pick.
"""

from __future__ import annotations

from datetime import datetime, timezone

from data_infra.repository import InMemoryDataRepository
from data_infra.universe import (
    SymbolMetadata,
    UniverseDefinition,
    build_security_masters,
    build_universe_memberships,
    detect_ticker_collisions,
)


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _repository(universe: UniverseDefinition, *, valid_from: datetime) -> InMemoryDataRepository:
    return InMemoryDataRepository(
        securities=build_security_masters(universe, valid_from=valid_from),
        universe_memberships=build_universe_memberships(universe, valid_from=valid_from),
    )


_UNIVERSE = UniverseDefinition(
    name="PHASE30_CASE_TEST",
    version="v1",
    role="RESEARCH",
    description="Phase 30 CASE A-G fixture",
    symbols=(
        # Listed after 2010 -- must not be selectable in a 2010 query.
        SymbolMetadata(symbol="LISTED_2015", listed_from=utc(2015, 6, 1)),
        # Existed through 2010, delisted in 2017 -- must remain queryable
        # before delisting and vanish after.
        SymbolMetadata(symbol="DELISTED_2017", listed_from=utc(2008, 1, 1), listed_to=utc(2017, 3, 1)),
        # Present across the whole window.
        SymbolMetadata(symbol="SURVIVOR_2010", listed_from=utc(2005, 1, 1)),
    ),
)


class TestCaseA_SecurityUnavailableIn2010CannotBeSelectedIn2010:
    def test_security_listed_2015_absent_from_2010_universe(self) -> None:
        repo = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))
        assert "LISTED_2015" not in repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2010, 1, 1))


class TestCaseB_SecurityListedIn2015CannotLeakIntoA2010Portfolio:
    def test_2010_query_excludes_a_symbol_that_only_starts_existing_in_2015(self) -> None:
        repo = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))
        universe_2010 = set(repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2010, 6, 15)))
        assert "LISTED_2015" not in universe_2010
        # And it does appear once its own listed_from has actually passed.
        universe_2016 = set(repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2016, 1, 1)))
        assert "LISTED_2015" in universe_2016


class TestCaseC_DelistedSecurityRemainsQueryableBeforeDelisting:
    def test_security_delisted_2017_present_in_2016_query(self) -> None:
        repo = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))
        assert "DELISTED_2017" in repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2016, 12, 1))

    def test_security_delisted_2017_present_in_2010_query(self) -> None:
        """The instruction's own framing: delisting in 2017 must not
        erase the security from a 2010 historical reconstruction."""
        repo = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))
        assert "DELISTED_2017" in repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2010, 1, 1))


class TestCaseD_SecurityAfterValidToAbsentFromLaterQueries:
    def test_security_delisted_2017_absent_from_2018_query(self) -> None:
        repo = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))
        assert "DELISTED_2017" not in repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2018, 1, 1))


class TestCaseE_TickerReuseDoesNotMergeTwoDifferentSecurities:
    def test_two_different_security_ids_sharing_a_ticker_in_non_overlapping_windows_is_not_a_collision(self) -> None:
        from data_infra.models import SecurityMaster
        from data_infra.enums import InstrumentType, SecurityStatus

        old_company = SecurityMaster(
            security_id="OLDCO-0001", ticker="ABCD", exchange="NYSE", currency="USD",
            company_id="OLDCO", instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2005, 1, 1), valid_to=utc(2010, 1, 1), status=SecurityStatus.DELISTED,
        )
        new_company = SecurityMaster(
            security_id="NEWCO-0002", ticker="ABCD", exchange="NASDAQ", currency="USD",
            company_id="NEWCO", instrument_type=InstrumentType.EQUITY,
            valid_from=utc(2012, 1, 1), valid_to=None, status=SecurityStatus.ACTIVE,
        )
        findings = detect_ticker_collisions([old_company, new_company])
        assert findings == []

        # And a point-in-time query never conflates the two: 2008 sees
        # only the old company's identity, 2015 sees only the new one's.
        repo = InMemoryDataRepository(
            securities=[old_company, new_company],
            universe_memberships=[],
        )
        assert repo.get_security("OLDCO-0001", as_of_time=utc(2008, 1, 1)) is not None
        assert repo.get_security("NEWCO-0002", as_of_time=utc(2008, 1, 1)) is None
        assert repo.get_security("NEWCO-0002", as_of_time=utc(2015, 1, 1)) is not None
        assert repo.get_security("OLDCO-0001", as_of_time=utc(2015, 1, 1)) is None


class TestCaseF_HistoricalMembershipEvaluatedUsingAsOfTime:
    def test_the_same_repository_yields_different_membership_for_different_as_of_times(self) -> None:
        repo = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))
        universe_2010 = set(repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2010, 1, 1)))
        universe_2024 = set(repo.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2024, 1, 1)))
        assert universe_2010 == {"DELISTED_2017", "SURVIVOR_2010"}
        assert universe_2024 == {"LISTED_2015", "SURVIVOR_2010"}
        assert universe_2010 != universe_2024


class TestCaseG_FutureMetadataCannotAffectPastUniverseConstruction:
    """The mere presence, in the repository, of a security whose own
    domain history only begins in 2015 must not change what a 2010
    query returns -- whether or not that record has been added is
    itself irrelevant to a query strictly earlier than its own
    valid_from."""

    def test_2010_query_result_is_identical_whether_or_not_the_2015_listing_is_in_the_repository(self) -> None:
        without_future_listing = UniverseDefinition(
            name="PHASE30_CASE_TEST_NO_FUTURE", version="v1", role="RESEARCH", description="test",
            symbols=(
                SymbolMetadata(symbol="DELISTED_2017", listed_from=utc(2008, 1, 1), listed_to=utc(2017, 3, 1)),
                SymbolMetadata(symbol="SURVIVOR_2010", listed_from=utc(2005, 1, 1)),
            ),
        )
        repo_without = _repository(without_future_listing, valid_from=utc(2000, 1, 1))
        repo_with = _repository(_UNIVERSE, valid_from=utc(2000, 1, 1))

        result_without = set(
            repo_without.get_universe("US_EQUITY", "PHASE30_CASE_TEST_NO_FUTURE", as_of_time=utc(2010, 1, 1))
        )
        result_with = set(repo_with.get_universe("US_EQUITY", "PHASE30_CASE_TEST", as_of_time=utc(2010, 1, 1)))

        assert result_without == {"DELISTED_2017", "SURVIVOR_2010"}
        assert result_with == {"DELISTED_2017", "SURVIVOR_2010"}
        assert result_without == result_with
