"""Real (non-mock) `ai_gateway.provider.AIProviderAdapter` implementations.

`ai_gateway/*.py` (the flat, top-level Phase 12 package -- `gateway.py`,
`provider.py`, `task_router.py`, `quota_manager.py`, `provider_selector.py`,
`config.py`, `models.py`, `validation.py`, `repository.py`, `admission.py`,
`grounding.py`, `enums.py`) stays exactly what Phase 12 originally shipped
and `tests/ai_gateway/test_ai_gateway_boundary.py` still verifies: mock-only,
offline, no `os.environ`/`os.getenv`, no network import. This subpackage is
where a REAL provider adapter lives instead -- mirroring
`data_infra.providers.*` (the real Tiingo/Alpha Vantage/Stooq/Twelve Data
adapters) sitting alongside `data_infra.provider`'s own generic, offline
`DataProvider` Protocol the exact same way.

See ADR-0206 for why a real adapter exists at all now (a genuine caller --
`scripts/run_ai_prediction_experiment.py`, a research-only experiment
tracking how well an LLM predicts price direction, deliberately never
wired into predict/decision/risk/broker) and docs/specifications/
PHASE-12-ai-gateway.md section 1.1's own "explicitly out of scope" note,
which this subpackage does not contradict: that scope statement is about
what `ai_gateway.*`'s flat package ships, not about whether any real
adapter may ever exist anywhere in the codebase.
"""

from __future__ import annotations
