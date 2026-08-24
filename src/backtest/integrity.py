"""BacktestIntegrityChecker.

See docs/specifications/PHASE-2-backtesting.md section 12. Gating rule:
a result with any ERROR/CRITICAL issue must not be treated as a
legitimate performance outcome (BacktestResult.is_valid_performance).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from data_infra.models import CorporateAction

from backtest.enums import IntegritySeverity, IntegrityStatus
from backtest.fills import Fill
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent


@dataclass(frozen=True)
class IntegrityIssue:
    check: str
    severity: IntegritySeverity
    message: str
    as_of_time: Optional[datetime] = None
    security_id: Optional[str] = None


@dataclass(frozen=True)
class IntegrityReport:
    issues: tuple[IntegrityIssue, ...]
    status: IntegrityStatus

    @property
    def is_valid_performance(self) -> bool:
        return self.status in (IntegrityStatus.PASSED, IntegrityStatus.PASSED_WITH_WARNINGS)

    @property
    def critical_issues(self) -> tuple[IntegrityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == IntegritySeverity.CRITICAL)

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == IntegritySeverity.ERROR)

    @property
    def warnings(self) -> tuple[IntegrityIssue, ...]:
        return tuple(i for i in self.issues if i.severity == IntegritySeverity.WARNING)


class BacktestIntegrityChecker:
    def __init__(self) -> None:
        self._issues: list[IntegrityIssue] = []
        self._last_checkpoint: Optional[datetime] = None
        self._seen_fill_order_ids: set[str] = set()
        self._data_versions: dict[tuple[str, datetime], str] = {}

    def record(
        self,
        check: str,
        severity: IntegritySeverity,
        message: str,
        as_of_time: Optional[datetime] = None,
        security_id: Optional[str] = None,
    ) -> None:
        self._issues.append(IntegrityIssue(check, severity, message, as_of_time, security_id))

    def check_checkpoint_order(self, checkpoint: datetime) -> None:
        if self._last_checkpoint is not None and checkpoint <= self._last_checkpoint:
            self.record(
                "timestamp_ordering", IntegritySeverity.CRITICAL,
                f"checkpoint {checkpoint} did not strictly increase from {self._last_checkpoint}",
                as_of_time=checkpoint,
            )
        self._last_checkpoint = checkpoint

    def check_universe(self, intents: Sequence[OrderIntent], universe: set[str], as_of_time: datetime) -> None:
        for intent in intents:
            if intent.security_id not in universe:
                self.record(
                    "universe_correctness", IntegritySeverity.ERROR,
                    f"order intent for {intent.security_id} not in resolved universe at {as_of_time}",
                    as_of_time, intent.security_id,
                )

    def check_duplicate_intents(self, intents: Sequence[OrderIntent], as_of_time: datetime) -> None:
        seen: set[tuple[str, str]] = set()
        for intent in intents:
            key = (intent.security_id, intent.side.value)
            if key in seen:
                self.record(
                    "duplicate_trades", IntegritySeverity.ERROR,
                    f"duplicate order intent for {intent.security_id} {intent.side.value} at {as_of_time}",
                    as_of_time, intent.security_id,
                )
            seen.add(key)

    def check_fill(self, fill: Fill) -> None:
        if fill.order_id in self._seen_fill_order_ids:
            self.record(
                "duplicate_trades", IntegritySeverity.ERROR,
                f"duplicate fill for order_id {fill.order_id}",
                fill.execution_time, fill.security_id,
            )
        self._seen_fill_order_ids.add(fill.order_id)

        if fill.execution_time <= fill.decision_time:
            self.record(
                "execution_timing", IntegritySeverity.CRITICAL,
                f"fill execution_time {fill.execution_time} not after decision_time {fill.decision_time}",
                fill.execution_time, fill.security_id,
            )

        key = (fill.security_id, fill.execution_time)
        prior_version = self._data_versions.get(key)
        if prior_version is not None and prior_version != fill.data_version:
            self.record(
                "data_version_consistency", IntegritySeverity.CRITICAL,
                f"data_version changed for {fill.security_id} at {fill.execution_time}: "
                f"{prior_version} -> {fill.data_version}",
                fill.execution_time, fill.security_id,
            )
        else:
            self._data_versions[key] = fill.data_version

    def check_execution_checkpoint(self, fill: Fill, expected_execution_time: datetime) -> None:
        if fill.execution_time != expected_execution_time:
            self.record(
                "execution_timing", IntegritySeverity.CRITICAL,
                f"fill executed at {fill.execution_time}, expected the T+1 checkpoint "
                f"{expected_execution_time} (ADR-0006)",
                fill.execution_time, fill.security_id,
            )

    def check_corporate_action_timing(self, action: CorporateAction, as_of_time: datetime) -> None:
        if action.available_time > as_of_time:
            self.record(
                "corporate_action_correctness", IntegritySeverity.CRITICAL,
                f"corporate action for {action.security_id} applied before its available_time",
                as_of_time, action.security_id,
            )

    def check_portfolio_state(self, view: PortfolioView) -> None:
        if view.cash < 0:
            self.record(
                "impossible_portfolio_state", IntegritySeverity.CRITICAL,
                f"negative cash: {view.cash}", view.as_of_time,
            )
        for security_id, position in view.positions.items():
            if position.quantity < 0:
                self.record(
                    "impossible_portfolio_state", IntegritySeverity.CRITICAL,
                    f"negative position for {security_id}: {position.quantity}",
                    view.as_of_time, security_id,
                )

    def check_missing_data(self, missing_security_ids: Sequence[str], as_of_time: datetime) -> None:
        for security_id in missing_security_ids:
            self.record(
                "missing_data", IntegritySeverity.WARNING,
                f"no price available for held position {security_id} at {as_of_time}, "
                "valued at average cost",
                as_of_time, security_id,
            )

    def note_discarded_end_of_backtest(self, intents: Sequence[OrderIntent], as_of_time: datetime) -> None:
        for intent in intents:
            self.record(
                "end_of_backtest", IntegritySeverity.INFO,
                f"order intent for {intent.security_id} generated on the final checkpoint was "
                "discarded — no future execution price exists within the backtest window",
                as_of_time, intent.security_id,
            )

    def finalize(self) -> IntegrityReport:
        if any(i.severity == IntegritySeverity.CRITICAL for i in self._issues):
            status = IntegrityStatus.CRITICAL_FAILURE
        elif any(i.severity == IntegritySeverity.ERROR for i in self._issues):
            status = IntegrityStatus.FAILED
        elif any(i.severity == IntegritySeverity.WARNING for i in self._issues):
            status = IntegrityStatus.PASSED_WITH_WARNINGS
        else:
            status = IntegrityStatus.PASSED
        return IntegrityReport(tuple(self._issues), status)
