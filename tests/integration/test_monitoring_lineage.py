"""Category: Integration Test -- Risk -> Monitoring Collector ->
MonitoringEvent -> ComponentHealth -> Alert, persisted through the same
DuckDB catalog Phase 4-13 already use, SQL-joinable end to end via
`MonitoringEvent.source_record_ids` (`monitoring_events.payload_json`),
and surviving a process restart (docs/specifications/
PHASE-14-monitoring.md section 14).
"""

from __future__ import annotations

from monitoring_helpers import make_broker_response, make_config, make_risk_result, utc
from storage_helpers import new_engine

from monitoring.collectors import collect_broker, collect_risk
from monitoring.enums import ComponentHealthStatus, MonitoringComponent
from monitoring.pipeline import assemble_pipeline_observation

from storage.broker_repository import DuckDBBrokerResponseRepository
from storage.monitoring_repository import (
    DuckDBAlertRepository,
    DuckDBComponentHealthRepository,
    DuckDBMonitoringEventRepository,
)
from storage.risk_repository import DuckDBRiskRepository


class TestRiskToMonitoringLineageEndToEnd:
    def test_full_chain_is_joinable_and_survives_restart(self, tmp_path) -> None:
        as_of = utc(2024, 3, 1)
        config = make_config(min_sample_count=1)

        engine = new_engine(tmp_path)
        risk_repo = DuckDBRiskRepository(engine)
        event_repo = DuckDBMonitoringEventRepository(engine)
        health_repo = DuckDBComponentHealthRepository(engine)
        alert_repo = DuckDBAlertRepository(engine)

        risk_result = make_risk_result(risk_id="RISK-300001", as_of_time=as_of)
        stored_risk = risk_repo.record(risk_result)

        event, health = collect_risk(
            [stored_risk], as_of_time=as_of, observed_at=as_of, config=config, event_id="MONEVT-300001",
            health_id="HEALTH-300001",
        )
        assert stored_risk.risk_id in event.source_record_ids

        stored_event = event_repo.record(event)
        stored_health = health_repo.record(health)

        # -- SQL joinability: risk_assessments <-> monitoring_events via the
        # JSON-encoded source_record_ids the collector carried forward --
        rows = engine.connection.execute(
            "SELECT r.risk_id, m.event_id, m.severity FROM risk_assessments r "
            "JOIN monitoring_events m ON list_contains("
            "CAST(json_extract(m.payload_json, '$.source_record_ids') AS VARCHAR[]), r.risk_id) "
            "WHERE r.risk_id = ?",
            [stored_risk.risk_id],
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == stored_event.event_id

        engine.close()

        # -- restart: reopen the same catalog file, everything is still there --
        engine2 = new_engine(tmp_path)
        reloaded_event = DuckDBMonitoringEventRepository(engine2).get(stored_event.event_id)
        assert reloaded_event == stored_event
        reloaded_health = DuckDBComponentHealthRepository(engine2).get_latest(MonitoringComponent.RISK)
        assert reloaded_health == stored_health
        engine2.close()

    def test_multiple_components_feed_one_pipeline_observation_with_mixed_health(self, tmp_path) -> None:
        as_of = utc(2024, 3, 1)
        config = make_config(min_sample_count=1, unavailable_failure_rate_threshold=0.5)

        engine = new_engine(tmp_path)
        risk_repo = DuckDBRiskRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        event_repo = DuckDBMonitoringEventRepository(engine)
        health_repo = DuckDBComponentHealthRepository(engine)
        alert_repo = DuckDBAlertRepository(engine)

        stored_risk = risk_repo.record(make_risk_result(risk_id="RISK-400001", as_of_time=as_of))
        stored_responses = [
            response_repo.record(make_broker_response(response_id=f"BROKRESLOG-4000{i:02d}", status="ERROR"))
            for i in range(3)
        ]

        risk_event, risk_health = collect_risk(
            [stored_risk], as_of_time=as_of, observed_at=as_of, config=config, event_id="MONEVT-400001",
            health_id="HEALTH-400001",
        )
        broker_event, broker_health = collect_broker(
            stored_responses, as_of_time=as_of, observed_at=as_of, config=config, event_id="MONEVT-400002",
            health_id="HEALTH-400002",
        )

        counter = {"n": 0}

        def alert_id_factory() -> str:
            counter["n"] += 1
            return f"ALERT-4000{counter['n']:02d}"

        observation = assemble_pipeline_observation(
            [(risk_event, risk_health), (broker_event, broker_health)], as_of_time=as_of, observed_at=as_of,
            config=config, pipeline_health_id="HEALTH-400003", alert_id_factory=alert_id_factory,
        )

        for event in observation.events:
            event_repo.record(event)
        for health in observation.component_healths + (observation.pipeline_health,):
            health_repo.record(health)
        for alert in observation.alerts:
            alert_repo.record(alert)

        assert observation.pipeline_health.status == ComponentHealthStatus.UNAVAILABLE
        assert risk_health.status == ComponentHealthStatus.HEALTHY
        assert broker_health.status == ComponentHealthStatus.UNAVAILABLE
        assert len(alert_repo.list_all()) >= 1

        engine.close()
