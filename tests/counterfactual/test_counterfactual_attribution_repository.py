"""Unit tests for counterfactual.repository.InMemoryAttributionRepository.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 4.5.
"""

from __future__ import annotations

from counterfactual_helpers import utc

from trade_journal.models import AttributionResult

from counterfactual.repository import InMemoryAttributionRepository


def _result(experiment_id: str = "BT-000001", **overrides) -> AttributionResult:
    fields = dict(
        experiment_id=experiment_id, market=0.06, sector=None, factor=None,
        selection=0.03, timing=None, execution=-0.01, computed_at=utc(2024, 6, 1),
    )
    fields.update(overrides)
    return AttributionResult(**fields)


class TestInMemoryAttributionRepository:
    def test_get_returns_none_when_nothing_recorded(self) -> None:
        repo = InMemoryAttributionRepository()
        assert repo.get("BT-000001") is None

    def test_record_then_get_round_trips(self) -> None:
        repo = InMemoryAttributionRepository()
        result = _result()
        repo.record(result)
        assert repo.get("BT-000001") == result

    def test_get_returns_the_latest_recorded_version(self) -> None:
        repo = InMemoryAttributionRepository()
        first = _result(selection=0.03, computed_at=utc(2024, 6, 1))
        second = _result(selection=0.05, computed_at=utc(2024, 6, 2))
        repo.record(first)
        repo.record(second)
        assert repo.get("BT-000001") == second

    def test_get_history_preserves_recording_order(self) -> None:
        repo = InMemoryAttributionRepository()
        first = _result(selection=0.03)
        second = _result(selection=0.05)
        repo.record(first)
        repo.record(second)
        assert repo.get_history("BT-000001") == (first, second)

    def test_different_experiments_do_not_collide(self) -> None:
        repo = InMemoryAttributionRepository()
        a = _result(experiment_id="BT-000001")
        b = _result(experiment_id="BT-000002")
        repo.record(a)
        repo.record(b)
        assert repo.get("BT-000001") == a
        assert repo.get("BT-000002") == b

    def test_list_all_returns_every_recorded_version(self) -> None:
        repo = InMemoryAttributionRepository()
        a = _result(experiment_id="BT-000001")
        b = _result(experiment_id="BT-000002")
        repo.record(a)
        repo.record(b)
        assert set(repo.list_all()) == {a, b}
