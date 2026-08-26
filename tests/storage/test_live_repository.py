"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 16's two Live Trading DuckDB stores (docs/specifications/
PHASE-16-live-trading.md section 12)."""

from __future__ import annotations

from live_helpers import make_approval, utc
from storage_helpers import new_engine

from broker.live.kill_switch import engage_kill_switch, release_kill_switch
from broker.live.reconciliation import compare_account
from broker.models import BrokerAccountSnapshot

from storage.live_repository import DuckDBKillSwitchRepository, DuckDBReconciliationRepository


def _account_snapshot(cash=1000.0) -> BrokerAccountSnapshot:
    return BrokerAccountSnapshot(broker_id="toss", as_of_time=utc(2024, 1, 2), available=True, unavailable_reason=None, cash=cash, buying_power=cash, currency="KRW")


class TestKillSwitchPersistence:
    def test_record_and_get_latest(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBKillSwitchRepository(engine)
        event = engage_kill_switch(event_id="KS1", reason="broker_health_unavailable", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(event)
        assert repo.get_latest() == event
        engine.close()

    def test_idempotent_on_event_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBKillSwitchRepository(engine)
        event = engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(event)
        repo.record(event)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_append_only_history_engage_then_release(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBKillSwitchRepository(engine)
        repo.record(engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1"))
        repo.record(release_kill_switch(event_id="KS2", approval=make_approval(), occurred_at=utc(2024, 1, 3), configuration_version="cfg-1"))
        assert len(repo.list_all()) == 2
        assert repo.get_latest().engaged is False
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        event = engage_kill_switch(event_id="KS1", reason="x", occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        DuckDBKillSwitchRepository(engine).record(event)
        engine.close()

        engine2 = new_engine(tmp_path)
        assert DuckDBKillSwitchRepository(engine2).get_latest() == event
        engine2.close()


class TestReconciliationPersistence:
    def test_record_and_get_latest(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBReconciliationRepository(engine)
        result = compare_account(1000.0, _account_snapshot(), tolerance=0.01, reconciliation_id="R1", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(result)
        assert repo.get_latest("account", "toss") == result
        engine.close()

    def test_idempotent_on_reconciliation_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBReconciliationRepository(engine)
        result = compare_account(1000.0, _account_snapshot(), tolerance=0.01, reconciliation_id="R1", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(result)
        repo.record(result)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        result = compare_account(1000.0, _account_snapshot(), tolerance=0.01, reconciliation_id="R1", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        DuckDBReconciliationRepository(engine).record(result)
        engine.close()

        engine2 = new_engine(tmp_path)
        assert DuckDBReconciliationRepository(engine2).get_latest("account", "toss") == result
        engine2.close()
