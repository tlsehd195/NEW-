"""DuckDB persistence for `broker.paper.performance.PaperPerformanceReport`
(Phase 18). Follows the exact pattern `storage.live_repository.
DuckDBReconciliationRepository` (Phase 16) already established:
natural-key idempotency on the report's own id, a `payload_json` blob
plus a few indexed columns for filtering, no new persistence design.

See docs/specifications/PHASE-18-paper-performance-and-validation.md.
"""

from __future__ import annotations

from typing import Optional, Protocol

from broker.paper.performance import PaperPerformanceReport

from storage.engine import StorageEngine
from storage.serialization import (
    json_dumps,
    json_loads,
    paper_performance_report_to_payload,
    payload_to_paper_performance_report,
    to_utc_naive,
)


class PaperPerformanceReportRepository(Protocol):
    def record(self, report: PaperPerformanceReport) -> PaperPerformanceReport: ...

    def get(self, report_id: str) -> Optional[PaperPerformanceReport]: ...

    def list_for_session(self, paper_session_id: str) -> list[PaperPerformanceReport]: ...

    def get_latest_for_session(self, paper_session_id: str) -> Optional[PaperPerformanceReport]: ...


class DuckDBPaperPerformanceReportRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, report: PaperPerformanceReport) -> PaperPerformanceReport:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM paper_performance_reports WHERE report_id = ?", [report.report_id]
        ).fetchone()
        if existing is not None:
            return payload_to_paper_performance_report(json_loads(existing[0]))

        payload = paper_performance_report_to_payload(report)
        conn.execute(
            "INSERT INTO paper_performance_reports (report_id, paper_session_id, evaluated_at, payload_json) "
            "VALUES (?, ?, ?, ?)",
            [report.report_id, report.paper_session_id, to_utc_naive(report.evaluated_at), json_dumps(payload)],
        )
        return report

    def get(self, report_id: str) -> Optional[PaperPerformanceReport]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM paper_performance_reports WHERE report_id = ?", [report_id]
        ).fetchone()
        return payload_to_paper_performance_report(json_loads(row[0])) if row is not None else None

    def list_for_session(self, paper_session_id: str) -> list[PaperPerformanceReport]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM paper_performance_reports WHERE paper_session_id = ? ORDER BY seq",
            [paper_session_id],
        )
        return [payload_to_paper_performance_report(json_loads(r[0])) for r in cur.fetchall()]

    def get_latest_for_session(self, paper_session_id: str) -> Optional[PaperPerformanceReport]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM paper_performance_reports WHERE paper_session_id = ? "
            "ORDER BY seq DESC LIMIT 1",
            [paper_session_id],
        ).fetchone()
        return payload_to_paper_performance_report(json_loads(row[0])) if row is not None else None


class InMemoryPaperPerformanceReportRepository:
    """Reference implementation mirroring every other in-memory
    repository in this codebase (natural-key dedup, no persistence)."""

    def __init__(self) -> None:
        self._reports: dict[str, PaperPerformanceReport] = {}
        self._by_session: dict[str, list[str]] = {}

    def record(self, report: PaperPerformanceReport) -> PaperPerformanceReport:
        if report.report_id in self._reports:
            return self._reports[report.report_id]
        self._reports[report.report_id] = report
        self._by_session.setdefault(report.paper_session_id, []).append(report.report_id)
        return report

    def get(self, report_id: str) -> Optional[PaperPerformanceReport]:
        return self._reports.get(report_id)

    def list_for_session(self, paper_session_id: str) -> list[PaperPerformanceReport]:
        return [self._reports[rid] for rid in self._by_session.get(paper_session_id, [])]

    def get_latest_for_session(self, paper_session_id: str) -> Optional[PaperPerformanceReport]:
        ids = self._by_session.get(paper_session_id, [])
        return self._reports[ids[-1]] if ids else None
