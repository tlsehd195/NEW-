"""AI Gateway (Phase 12).

See docs/specifications/PHASE-12-ai-gateway.md and ADR-0018.

The single entry point (`ai_gateway.gateway.AIGateway`) any future phase
must use to call an AI/LLM provider (`PROJECT_MASTER_PLAN.md` section 5:
"전체 애플리케이션에서 AI API를 직접 호출하지 않는다"). This package is
fully additive on top of Phase 0-11 -- no Phase 0-11 source file is
modified to build it.

This phase makes no real network call to any AI provider. The only
shipped `AIProviderAdapter` implementation is `ai_gateway.provider.
MockProviderAdapter` -- deterministic, offline, no API key ever read or
required (`os.environ`/`os.getenv` do not appear anywhere in this
package, verified by `tests/ai_gateway/test_ai_gateway_boundary.py`) --
mirroring the same "baseline/mock first, prove the pipeline, not a real
provider" precedent every prior phase's own reference implementation
already established (`RandomWalkPredictor`, `MeanRewardBaselineTrainer`,
etc.).

No code path in this package ever produces a `DecisionAction`, an order,
a broker call, or a `learning.enums.CandidateModelStatus.APPROVED`/
`DEPLOYED` transition -- see
`tests/ai_gateway/test_ai_gateway_boundary.py`.
"""

from __future__ import annotations
