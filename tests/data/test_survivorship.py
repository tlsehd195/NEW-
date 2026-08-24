"""Category 14: Survivorship bias protection test.

Verifies that `get_universe(..., as_of_time=T)` returns different
constituent sets for different T, so the "copy today's index membership
back over all of history" bug is structurally impossible with this
interface. See docs/specifications/PHASE-1-data-infrastructure.md
section 8.
"""

from __future__ import annotations

from helpers import utc

from data_infra.models import UniverseMembership
from data_infra.repository import InMemoryDataRepository


class TestSurvivorshipBiasProtection:
    def test_universe_membership_changes_over_time(self) -> None:
        # SEC-OLD was in the SP500 mock universe until it was removed
        # (e.g. delisted/dropped); SEC-NEW joined afterward. A naive
        # "use today's constituents for all history" approach would get
        # this wrong in both directions.
        memberships = [
            UniverseMembership(
                security_id="SEC-OLD", universe="SP500", valid_from=utc(2020, 1, 1), valid_to=utc(2023, 6, 1)
            ),
            UniverseMembership(
                security_id="SEC-NEW", universe="SP500", valid_from=utc(2023, 6, 1)
            ),
            UniverseMembership(
                security_id="SEC-STABLE", universe="SP500", valid_from=utc(2015, 1, 1)
            ),
        ]
        repo = InMemoryDataRepository(universe_memberships=memberships)

        before_change = repo.get_universe("US", "SP500", as_of_time=utc(2022, 1, 1))
        after_change = repo.get_universe("US", "SP500", as_of_time=utc(2024, 1, 1))

        assert set(before_change) == {"SEC-OLD", "SEC-STABLE"}
        assert set(after_change) == {"SEC-NEW", "SEC-STABLE"}
        # The critical assertion: querying "today's" universe and applying
        # it to a historical as_of_time would silently include SEC-NEW
        # (not yet a member) and exclude SEC-OLD (still a member back
        # then) — this must not happen.
        assert "SEC-NEW" not in before_change
        assert "SEC-OLD" not in after_change

    def test_membership_query_requires_as_of_time_no_unscoped_default(self) -> None:
        # There is no DataRepository.get_universe() overload that omits
        # as_of_time — this is enforced by the method signature itself
        # (a TypeError, not a logic bug, if a caller tries to omit it).
        import inspect

        signature = inspect.signature(InMemoryDataRepository.get_universe)
        assert "as_of_time" in signature.parameters
        assert signature.parameters["as_of_time"].default is inspect.Parameter.empty

    def test_removed_member_not_included_at_a_boundary_moment(self) -> None:
        membership = UniverseMembership(
            security_id="SEC-OLD", universe="SP500", valid_from=utc(2020, 1, 1), valid_to=utc(2023, 6, 1)
        )
        repo = InMemoryDataRepository(universe_memberships=[membership])
        # Half-open interval: valid_to itself is exclusive.
        assert "SEC-OLD" in repo.get_universe("US", "SP500", as_of_time=utc(2023, 5, 31))
        assert "SEC-OLD" not in repo.get_universe("US", "SP500", as_of_time=utc(2023, 6, 1))
