"""Enumerations for the Broker Adapter (Phase 13).

See docs/specifications/PHASE-13-toss-securities-adapter.md sections 5,
6, 10.
"""

from __future__ import annotations

from enum import Enum


class BrokerExecutionMode(str, Enum):
    """PROJECT_MASTER_PLAN.md section 14.4's `LIVE_TRADING=false` default
    principle, applied to broker execution specifically. `OFFLINE` is
    the only mode any `BrokerConfig` constructs without the caller
    explicitly overriding it -- no environment variable, credential, or
    capability check alone can move a broker into `LIVE`
    (`broker.config.BrokerConfig.__post_init__` enforces this: setting
    `execution_mode=LIVE` requires `live_opt_in=True` to also be passed
    explicitly, or construction raises)."""

    OFFLINE = "OFFLINE"  # MockBrokerAdapter / MockTransport only -- no network, no credential ever read
    SANDBOX = "SANDBOX"  # reserved: Toss Securities publishes no sandbox environment as of this phase's research (ADR-0019 section on Toss API verification) -- no code path uses this value yet
    LIVE = "LIVE"  # real orders against a real account -- requires explicit opt-in


class BrokerOrderStatus(str, Enum):
    """Toss Securities' own observed order-state vocabulary (confirmed
    via research at implementation time -- see ADR-0019's Toss API
    Verification section), not the generic placeholder list this
    phase's instructions suggested. Toss groups orders into OPEN
    (PENDING/PARTIAL_FILLED/PENDING_CANCEL/PENDING_REPLACE) and CLOSED
    (FILLED/CANCELED/REJECTED/REPLACED/CANCEL_REJECTED/REPLACE_REJECTED);
    this enum keeps that same vocabulary rather than inventing a
    parallel one. `UNKNOWN` is PROJECT_MASTER_PLAN.md section 9.1's
    required broker-disconnected state: "Broker API와 연결이 끊긴 경우
    주문이 실제로 체결됐는지 시스템이 모를 수 있다" -- never treated as
    a terminal or safe state.

    `CANCEL_REJECTED`/`REPLACE_REJECTED` (Phase 21 addition, Tier 1
    evidence -- the official Toss OpenAPI spec's `Order.status` enum has
    10 values, not the 8 this enum originally had): Toss represents "a
    cancel/modify request was itself rejected" as its own distinct
    terminal order-status value, not a `REJECTED` original order and not
    a silent no-op -- see docs/operations/TOSS-API-GAP-ANALYSIS.md Phase
    20 addendum."""

    PENDING = "PENDING"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    PENDING_REPLACE = "PENDING_REPLACE"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    REPLACED = "REPLACED"
    CANCEL_REJECTED = "CANCEL_REJECTED"
    REPLACE_REJECTED = "REPLACE_REJECTED"
    UNKNOWN = "UNKNOWN"


_OPEN_STATUSES = frozenset({
    BrokerOrderStatus.PENDING, BrokerOrderStatus.PARTIAL_FILLED,
    BrokerOrderStatus.PENDING_CANCEL, BrokerOrderStatus.PENDING_REPLACE,
})
_CLOSED_STATUSES = frozenset({
    BrokerOrderStatus.FILLED, BrokerOrderStatus.CANCELED,
    BrokerOrderStatus.REJECTED, BrokerOrderStatus.REPLACED,
    BrokerOrderStatus.CANCEL_REJECTED, BrokerOrderStatus.REPLACE_REJECTED,
})


def is_open_status(status: BrokerOrderStatus) -> bool:
    return status in _OPEN_STATUSES


def is_closed_status(status: BrokerOrderStatus) -> bool:
    return status in _CLOSED_STATUSES


class OrderValidationStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"


class BrokerCapability(str, Enum):
    """What a given `BrokerAdapter` implementation might support --
    PROJECT_MASTER_PLAN.md/instruction section 6: "Toss Securities가
    지원하는 기능을 무조건 있다고 가정하지 않는다.\""""

    MARKET_ORDER = "MARKET_ORDER"
    LIMIT_ORDER = "LIMIT_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    ORDER_STATUS = "ORDER_STATUS"
    ACCOUNT_BALANCE = "ACCOUNT_BALANCE"
    POSITIONS = "POSITIONS"
    QUOTE = "QUOTE"
    IDEMPOTENT_CLIENT_ORDER_ID = "IDEMPOTENT_CLIENT_ORDER_ID"


class CapabilityStatus(str, Enum):
    ENABLED = "ENABLED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"  # capability exists per public research but could not be independently verified end-to-end
