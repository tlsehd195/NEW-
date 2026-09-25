"""AI Gateway (Phase 12).

See docs/specifications/PHASE-12-ai-gateway.md and ADR-0018.

The single entry point (`ai_gateway.gateway.AIGateway`) any future phase
must use to call an AI/LLM provider (`PROJECT_MASTER_PLAN.md` section 5:
"전체 애플리케이션에서 AI API를 직접 호출하지 않는다"). This package is
fully additive on top of Phase 0-11 -- no Phase 0-11 source file is
modified to build it.

This phase (the flat `ai_gateway/*.py` files listed above -- `gateway.py`,
`provider.py`, `task_router.py`, `quota_manager.py`, `provider_selector.py`,
`config.py`, `models.py`, `validation.py`, `repository.py`, `admission.py`,
`grounding.py`, `enums.py`) makes no real network call to any AI provider.
The only `AIProviderAdapter` implementation shipped AT THIS LEVEL is
`ai_gateway.provider.MockProviderAdapter` -- deterministic, offline, no
API key ever read or required (`os.environ`/`os.getenv` do not appear
anywhere in these files, verified by `tests/ai_gateway/
test_ai_gateway_boundary.py`) -- mirroring the same "baseline/mock first,
prove the pipeline, not a real provider" precedent every prior phase's
own reference implementation already established (`RandomWalkPredictor`,
`MeanRewardBaselineTrainer`, etc.).

ADR-0206 adds one real adapter, `ai_gateway.providers.gemini.
GeminiProviderAdapter` -- deliberately kept in the separate `ai_gateway.
providers` subpackage rather than here (see that subpackage's own
`__init__.py` docstring), so this file's own claims above, and the
boundary tests that verify them, continue to describe the Gateway/Router/
QuotaManager pipeline itself exactly as originally shipped. That real
adapter exists only for `scripts/run_ai_prediction_experiment.py`, a
research-only experiment tracking LLM price-direction prediction
accuracy -- never for predict/decision/risk/broker, which do not import
`ai_gateway.providers.*` at all.

No code path in this package ever produces a `DecisionAction`, an order,
a broker call, or a `learning.enums.CandidateModelStatus.APPROVED`/
`DEPLOYED` transition -- see
`tests/ai_gateway/test_ai_gateway_boundary.py`.
"""

from __future__ import annotations
