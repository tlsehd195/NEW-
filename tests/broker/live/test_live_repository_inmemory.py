"""Category: Persistence Test (in-memory) -- append-only idempotency for
`InMemoryKillSwitchRepository`/`InMemoryReconciliationRepository`."""

from __future__ import annotations

from live_helpers import make_approval, utc

from broker.live.kill_switch import InMemoryKillSwitchRepository, engage_kill_switch, release_kill_switch
from broker.live.reconciliation import InMemoryReconciliationRepository, compare_account
from broker.models import BrokerAccountSnapshot


class TestKillSwitchRepository:
    def test_idempotent_on_event_id(self) -> None:
        repo = InMemoryKillSwitchRepository()
        event = engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(event)
        repo.record(event)
        assert len(repo.list_all()) == 1

    def test_get_latest_none_when_empty(self) -> None:
        repo = InMemoryKillSwitchRepository()
        assert repo.get_latest() is None

    def test_history_preserved_across_engage_release(self) -> None:
        repo = InMemoryKillSwitchRepository()
        repo.record(engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1"))
        repo.record(release_kill_switch(event_id="KS2", approval=make_approval(), occurred_at=utc(2024, 1, 3), configuration_version="cfg-1"))
        assert len(repo.list_all()) == 2
        assert repo.get_latest().event_id == "KS2"


class TestReconciliationRepository:
    def test_idempotent_on_reconciliation_id(self) -> None:
        repo = InMemoryReconciliationRepository()
        snap = BrokerAccountSnapshot(broker_id="toss", as_of_time=utc(2024, 1, 2), available=True, unavailable_reason=None, cash=1000.0, buying_power=1000.0, currency="KRW")
        result = compare_account(1000.0, snap, tolerance=0.01, reconciliation_id="R1", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(result)
        repo.record(result)
        assert len(repo.list_all()) == 1

    def test_get_latest_none_when_no_matching_target(self) -> None:
        repo = InMemoryReconciliationRepository()
        assert repo.get_latest("account", "toss") is None
