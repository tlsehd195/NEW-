"""Phase 29 survivorship-aware universe tests (instruction sections 9,
10-12, 20-21, 57 categories A/B/C/D/E/F/G/P). SYNTHETIC FIXTURE ONLY --
these prove the point-in-time-safe security-identity/universe-membership
*mechanism* works correctly, never a claim about real US equity data
(none exists in this environment; see docs/research/STRATEGY-VALIDATION-REPORT.md's
Phase 29 Addendum).

Confirms (per the Phase 29 architecture audit,
docs/decisions/ADR-0032-security-identity-and-survivorship-aware-universe.md):
`data_infra.models.SecurityMaster`/`UniverseMembership` (Phase 1,
unmodified) and `DataRepository.get_universe`/`get_security` (Phase 1,
unmodified) already ARE the survivorship-bias-aware, point-in-time-safe
architecture this phase's instruction asks for -- `security_id` is
already a permanent identifier independent of `ticker`, `valid_from`/
`valid_to` already scope both security identity and universe
membership to real historical intervals, and `SecurityStatus` already
distinguishes ACTIVE/DELISTED/RENAMED/MERGED. What this phase actually
added (`build_security_masters`/`build_universe_memberships` wiring in
`data_infra/universe.py`, plus `detect_ticker_collisions`) is exercised
here."""

from __future__ import annotations

from datetime import datetime, timezone

from data_infra.enums import SecurityStatus
from data_infra.models import SecurityMaster
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


class TestDelistedSecurityHistoricalMembership:
    """Categories A/C/D (security identity uniqueness, historical
    validity interval, delisted security inclusion)."""

    def test_delisted_symbol_gets_delisted_status_and_valid_to(self) -> None:
        universe = UniverseDefinition(
            name="TEST_UNIVERSE", version="v1", role="RESEARCH", description="test",
            symbols=(
                SymbolMetadata(symbol="STILLALIVE", listed_from=utc(2005, 1, 1)),
                SymbolMetadata(symbol="DELISTED_CO", listed_from=utc(2005, 1, 1), listed_to=utc(2015, 6, 1)),
            ),
        )
        masters = {sm.security_id: sm for sm in build_security_masters(universe, valid_from=utc(2000, 1, 1))}

        assert masters["STILLALIVE"].status == SecurityStatus.ACTIVE
        assert masters["STILLALIVE"].valid_to is None

        assert masters["DELISTED_CO"].status == SecurityStatus.DELISTED
        assert masters["DELISTED_CO"].valid_from == utc(2005, 1, 1)
        assert masters["DELISTED_CO"].valid_to == utc(2015, 6, 1)

    def test_symbol_without_confirmed_listed_dates_falls_back_to_caller_value_unchanged(self) -> None:
        """Backward compatibility: an existing SymbolMetadata with no
        listed_from/listed_to (e.g. PILOT_UNIVERSE_V1's real entries)
        must behave byte-for-byte identically to before this phase."""
        universe = UniverseDefinition(
            name="TEST_UNIVERSE", version="v1", role="RESEARCH", description="test",
            symbols=(SymbolMetadata(symbol="AAPL"),),
        )
        [master] = build_security_masters(universe, valid_from=utc(2023, 1, 1))
        assert master.valid_from == utc(2023, 1, 1)
        assert master.valid_to is None
        assert master.status == SecurityStatus.ACTIVE

        [membership] = build_universe_memberships(universe, valid_from=utc(2023, 1, 1))
        assert membership.valid_from == utc(2023, 1, 1)
        assert membership.valid_to is None


class TestPointInTimeUniverseLeakage:
    """Category B/P (future security leakage prevention, universe
    leakage) -- the instruction's own worked example (section 21)."""

    def _repository(self) -> InMemoryDataRepository:
        universe = UniverseDefinition(
            name="SURVIVORSHIP_TEST", version="v1", role="RESEARCH", description="test",
            symbols=(
                SymbolMetadata(symbol="LATE_LISTING", listed_from=utc(2018, 1, 1)),
                SymbolMetadata(symbol="EARLY_DELISTING", listed_from=utc(2005, 1, 1), listed_to=utc(2017, 1, 1)),
                SymbolMetadata(symbol="SURVIVOR", listed_from=utc(2005, 1, 1)),
            ),
        )
        return InMemoryDataRepository(
            securities=build_security_masters(universe, valid_from=utc(2000, 1, 1)),
            universe_memberships=build_universe_memberships(universe, valid_from=utc(2000, 1, 1)),
        )

    def test_security_listed_in_2018_does_not_appear_in_a_2015_query(self) -> None:
        repo = self._repository()
        assert "LATE_LISTING" not in repo.get_universe("US_EQUITY", "SURVIVORSHIP_TEST", as_of_time=utc(2015, 1, 1))

    def test_security_listed_in_2018_appears_in_a_2020_query(self) -> None:
        repo = self._repository()
        assert "LATE_LISTING" in repo.get_universe("US_EQUITY", "SURVIVORSHIP_TEST", as_of_time=utc(2020, 1, 1))

    def test_delisted_security_present_before_its_valid_to(self) -> None:
        repo = self._repository()
        assert "EARLY_DELISTING" in repo.get_universe("US_EQUITY", "SURVIVORSHIP_TEST", as_of_time=utc(2016, 1, 1))

    def test_delisted_security_absent_after_its_valid_to(self) -> None:
        repo = self._repository()
        assert "EARLY_DELISTING" not in repo.get_universe("US_EQUITY", "SURVIVORSHIP_TEST", as_of_time=utc(2018, 1, 1))

    def test_current_survivor_only_query_and_historical_query_genuinely_differ(self) -> None:
        """Category E: the instruction's central question --
        "current survivors only" vs "the real historical universe" --
        must produce DIFFERENT results, or the whole survivorship-aware
        mechanism is a no-op."""
        repo = self._repository()
        current_day_universe = set(repo.get_universe("US_EQUITY", "SURVIVORSHIP_TEST", as_of_time=utc(2024, 1, 1)))
        historical_2010_universe = set(repo.get_universe("US_EQUITY", "SURVIVORSHIP_TEST", as_of_time=utc(2010, 1, 1)))

        # "Current survivors" (2024): EARLY_DELISTING is gone, LATE_LISTING is in.
        assert current_day_universe == {"LATE_LISTING", "SURVIVOR"}
        # "What was actually investable in 2010": LATE_LISTING doesn't exist
        # yet, EARLY_DELISTING is still alive -- the exact opposite bias
        # a naive "use today's constituent list" backtest would introduce.
        assert historical_2010_universe == {"EARLY_DELISTING", "SURVIVOR"}
        assert current_day_universe != historical_2010_universe


class TestTickerReuseAndCollisionDetection:
    """Category F/G-adjacent (broad universe determinism, historical
    identity correctness) -- instruction section 8's ticker-reuse
    scenario, and section 20's identity-collision data-quality check."""

    def test_legitimate_ticker_reuse_across_non_overlapping_windows_is_not_flagged(self) -> None:
        # ticker "ABC" delisted by company A in 2015, reassigned to an
        # unrelated company B in 2019 -- both keep the SAME ticker
        # string but are different, non-overlapping security_ids.
        masters = [
            SecurityMaster(
                security_id="COMPANY-A-2005", ticker="ABC", exchange="NASDAQ", currency="USD",
                company_id="COMPANY-A", instrument_type="EQUITY",
                valid_from=utc(2005, 1, 1), valid_to=utc(2015, 1, 1), status=SecurityStatus.DELISTED,
            ),
            SecurityMaster(
                security_id="COMPANY-B-2019", ticker="ABC", exchange="NASDAQ", currency="USD",
                company_id="COMPANY-B", instrument_type="EQUITY",
                valid_from=utc(2019, 1, 1), status=SecurityStatus.ACTIVE,
            ),
        ]
        assert detect_ticker_collisions(masters) == []

    def test_genuine_overlapping_ticker_collision_is_flagged(self) -> None:
        # A real data bug: two DIFFERENT security_ids both claiming
        # ticker "XYZ" at an overlapping point in time.
        masters = [
            SecurityMaster(
                security_id="COMPANY-X", ticker="XYZ", exchange="NASDAQ", currency="USD",
                company_id="COMPANY-X", instrument_type="EQUITY",
                valid_from=utc(2010, 1, 1), status=SecurityStatus.ACTIVE,
            ),
            SecurityMaster(
                security_id="COMPANY-Y", ticker="XYZ", exchange="NYSE", currency="USD",
                company_id="COMPANY-Y", instrument_type="EQUITY",
                valid_from=utc(2012, 1, 1), status=SecurityStatus.ACTIVE,
            ),
        ]
        findings = detect_ticker_collisions(masters)
        assert len(findings) == 1
        assert "XYZ" in findings[0] and "COMPANY-X" in findings[0] and "COMPANY-Y" in findings[0]

    def test_same_security_id_relisted_under_the_same_ticker_is_not_a_collision(self) -> None:
        masters = [
            SecurityMaster(
                security_id="COMPANY-Z", ticker="ZZZ", exchange="NASDAQ", currency="USD",
                company_id="COMPANY-Z", instrument_type="EQUITY",
                valid_from=utc(2005, 1, 1), valid_to=utc(2010, 1, 1), status=SecurityStatus.DELISTED,
            ),
            SecurityMaster(
                security_id="COMPANY-Z", ticker="ZZZ", exchange="NASDAQ", currency="USD",
                company_id="COMPANY-Z", instrument_type="EQUITY",
                valid_from=utc(2012, 1, 1), status=SecurityStatus.ACTIVE,
            ),
        ]
        assert detect_ticker_collisions(masters) == []

    def test_no_collision_among_distinct_tickers(self) -> None:
        universe = UniverseDefinition(
            name="TEST_UNIVERSE", version="v1", role="RESEARCH", description="test",
            symbols=(SymbolMetadata(symbol="AAA"), SymbolMetadata(symbol="BBB"), SymbolMetadata(symbol="CCC")),
        )
        masters = build_security_masters(universe, valid_from=utc(2020, 1, 1))
        assert detect_ticker_collisions(masters) == []


class TestBenchmarkUniverseSeparationStillHolds:
    """Category benchmark separation, re-verified at the Phase 29
    boundary (already structurally enforced since Phase 24 --
    UniverseDefinition.__post_init__ raises if BENCHMARK_SYMBOL appears
    among its symbols)."""

    def test_benchmark_symbol_rejected_even_with_listed_from_to_populated(self) -> None:
        import pytest
        from data_infra.universe import BENCHMARK_SYMBOL

        with pytest.raises(ValueError):
            UniverseDefinition(
                name="BAD_UNIVERSE", version="v1", role="RESEARCH", description="test",
                symbols=(SymbolMetadata(symbol=BENCHMARK_SYMBOL, listed_from=utc(1993, 1, 29)),),
            )
