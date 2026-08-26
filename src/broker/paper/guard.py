"""assert_paper_environment_safe: a defense-in-depth check for a future
higher-level trading-engine dispatcher that selects a `BrokerAdapter`
implementation by configuration -- instruction section 21's explicit
"environment=paper, broker=toss 같은 위험한 조합이 발생하면 fail
closed해야 한다." `PaperTradingConfig.environment` already makes this
combination structurally unreachable through this package's own
constructors (`PaperTradingConfig.__post_init__` rejects any value
other than `"paper"`, and nothing in `broker.paper.*` ever constructs a
`TossBrokerAdapter`) -- this function exists only for a caller outside
`broker.paper.*` that independently holds an `environment` string and a
`BrokerAdapter` instance and wants one more explicit, auditable check
before wiring them together.

This is the *only* place in `broker.paper.*` that references
`broker.toss.adapter.TossBrokerAdapter` -- purely for an `isinstance`
check, never constructed or called
(`tests/broker/paper/test_paper_boundary.py`).
"""

from __future__ import annotations

from typing import Any


def assert_paper_environment_safe(environment: str, broker: Any) -> None:
    if environment != "paper":
        return
    from broker.toss.adapter import TossBrokerAdapter

    if isinstance(broker, TossBrokerAdapter):
        raise ValueError(
            f"refusing to pair environment={environment!r} with a TossBrokerAdapter -- "
            "a paper environment must never be wired to a real broker adapter"
        )
