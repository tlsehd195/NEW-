"""build_capabilities: a small constructor helper so every
`BrokerAdapter.get_capabilities()` implementation declares its support
the same explicit way -- instruction section 6: only a capability
confirmed `ENABLED` may actually be attempted; everything else is
`UNSUPPORTED` or `UNKNOWN`, never silently assumed present.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 6.
"""

from __future__ import annotations

from datetime import datetime

from broker.enums import BrokerCapability, CapabilityStatus
from broker.models import BrokerCapabilities


def build_capabilities(
    broker_id: str, statuses: dict[BrokerCapability, CapabilityStatus], *, recorded_at: datetime
) -> BrokerCapabilities:
    """Every `BrokerCapability` not explicitly named in `statuses` is
    filled in as `UNKNOWN` -- a capability this function's caller did
    not think to declare is never silently treated as `ENABLED`."""
    complete = {cap: statuses.get(cap, CapabilityStatus.UNKNOWN) for cap in BrokerCapability}
    return BrokerCapabilities(broker_id=broker_id, capabilities=complete, recorded_at=recorded_at)
