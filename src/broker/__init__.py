"""Broker Adapter (Phase 13).

See docs/specifications/PHASE-13-toss-securities-adapter.md and
ADR-0019.

`PROJECT_MASTER_PLAN.md` section 9.3: "core system은 Toss API에 직접
의존하지 않는다" -- `broker.protocol.BrokerAdapter` is the neutral
interface every broker implementation (`broker.mock.MockBrokerAdapter`,
`broker.toss.adapter.TossBrokerAdapter`) satisfies. This package is
fully additive on top of Phase 0-12 -- no Phase 0-12 source file is
modified to build it.

This phase builds the boundary, not an automated trading system:
`broker.config.BrokerConfig.execution_mode` defaults to `OFFLINE`, and
no code path anywhere in this package can submit a real order without
an explicit, out-of-band opt-in to `BrokerExecutionMode.LIVE` plus real
credentials the caller supplies -- credential *values* are never read,
persisted, or logged by anything except `broker.toss.auth`, and even
there only at the moment of an explicit LIVE-mode call
(`tests/broker/test_broker_secret_safety.py`). No code path in this
package ever constructs an order by itself -- every `ValidatedOrder`
must be built from an already risk-approved
`risk.models.RiskCheckedPosition` (`broker.validation.build_validated_order`),
and no function here imports `decision.agent`/`risk.sizing`/
`risk.engine`/`predict.predictor` or calls `ai_gateway.gateway.AIGateway`
(`tests/broker/test_broker_boundary.py`).
"""

from __future__ import annotations
