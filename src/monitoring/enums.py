"""Enumerations for Monitoring (Phase 14).

See docs/specifications/PHASE-14-monitoring.md sections 4, 5.
"""

from __future__ import annotations

from enum import Enum


class MonitoringComponent(str, Enum):
    """Every upstream layer this package can observe -- read-only, per
    `PROJECT_MASTER_PLAN.md` section 4.1's pipeline order."""

    DATA = "DATA"
    REGIME = "REGIME"
    PREDICTION = "PREDICTION"
    DECISION = "DECISION"
    SIZING = "SIZING"
    RISK = "RISK"
    BROKER = "BROKER"
    LEARNING = "LEARNING"
    MODEL_EVOLUTION = "MODEL_EVOLUTION"
    AI_GATEWAY = "AI_GATEWAY"
    PIPELINE = "PIPELINE"  # the end-to-end/aggregate view, not a single layer


class ComponentHealthStatus(str, Enum):
    """`UNKNOWN` is never treated as `HEALTHY` -- the same fail-closed
    rule `risk.enums.RiskCheckStatus.UNKNOWN`/`ai_gateway.enums.
    ProviderHealthStatus.UNKNOWN` already established (Phase 8/12),
    applied here to component health instead."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class AlertSeverity(str, Enum):
    """`PROJECT_MASTER_PLAN.md` section 12.5's `CRITICAL/WARNING/INFO`,
    plus `UNKNOWN` -- a monitoring result this package could not
    honestly evaluate is itself worth surfacing, not silently dropped
    to `INFO`."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class DriftStatus(str, Enum):
    NO_DRIFT = "NO_DRIFT"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    UNKNOWN = "UNKNOWN"
