"""Broker error hierarchy -- every failure a `BrokerAdapter` can raise,
mirroring `ai_gateway.provider`'s exception pattern (Phase 12) so both
external-integration boundaries in this codebase fail the same way.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 11.
"""

from __future__ import annotations


class BrokerError(Exception):
    """Base class for every broker failure `broker.adapter`/callers
    explicitly handle. Never used for a boundary/programming bug --
    those raise a plain `ValueError`/`RuntimeError` instead, so they are
    not silently treated as "just another broker failure.\""""


class BrokerAuthError(BrokerError):
    pass


class BrokerTimeoutError(BrokerError):
    pass


class BrokerRateLimitError(BrokerError):
    pass


class BrokerProviderError(BrokerError):
    """A 5xx response -- the broker's own infrastructure failed, not a
    definitive judgment about the order itself. Deliberately distinct
    from a mapped `BrokerOrderStatus.REJECTED` (Phase 17 Production
    Safety Review finding): REJECTED asserts the broker looked at the
    order and declined it, which a 5xx never establishes -- the order
    may or may not have been accepted server-side. Raising this (like
    `BrokerAuthError`/`BrokerRateLimitError`) lets `LiveTradingSession`
    treat it as `BrokerOrderStatus.UNKNOWN` plus
    `OperationalState.RECONCILIATION_REQUIRED`, never as a safe-to-retry
    rejection."""


class BrokerTransportError(BrokerError):
    """Connection failure / malformed response at the transport layer
    -- distinct from an authenticated, well-formed error the broker
    itself returned (`BrokerAuthError`/`BrokerRateLimitError`)."""


class BrokerCapabilityError(BrokerError):
    """Raised when an operation is not `ENABLED` for this adapter
    (instruction section 6: "지원하지 않는 order type을 임의로 다른
    order type으로 변환하지 않는다") -- including operations this
    project could not independently verify against Toss Securities'
    official documentation at implementation time
    (`CapabilityStatus.UNKNOWN`), which are conservatively treated the
    same as `UNSUPPORTED` rather than attempted."""
