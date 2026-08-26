"""assert_live_environment_broker_safe: the mirror image of
`broker.paper.guard.assert_paper_environment_safe` (Phase 15).
Instruction section 9: "Live environment + Paper Broker → REJECT 또는
명시적 operational mode에 한해 허용." A live environment paired with a
non-live-capable adapter is refused by default; the one escape hatch
(`allow_non_live_broker_for_testing=True`) must be passed explicitly by
the caller -- never a default, never inferred from configuration, so a
grep for that keyword finds every place this repository intentionally
runs Live-environment code against a non-real broker (this module's own
tests only).

This is the *only* place in `broker.live.*` that references
`broker.toss.adapter.TossBrokerAdapter` -- purely for an `isinstance`
check, never constructed or called
(`tests/broker/live/test_live_boundary.py`).

See docs/specifications/PHASE-16-live-trading.md section 9 (environment
separation).
"""

from __future__ import annotations

from typing import Any


def assert_live_environment_broker_safe(
    environment: str, broker: Any, *, allow_non_live_broker_for_testing: bool = False,
) -> None:
    if environment != "live":
        return
    if allow_non_live_broker_for_testing:
        return

    from broker.toss.adapter import TossBrokerAdapter

    if not isinstance(broker, TossBrokerAdapter):
        raise ValueError(
            f"refusing to pair environment={environment!r} with a {type(broker).__name__} -- "
            "a live environment must use a real, live-capable broker adapter unless "
            "allow_non_live_broker_for_testing=True is passed explicitly"
        )
