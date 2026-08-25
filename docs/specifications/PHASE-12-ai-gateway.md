# Phase 12 — AI Gateway

## 0. Git / Branch Integrity Check (performed before any implementation)

This session ("Session 13") started from a fresh container/context, in
the same repository the prior session left. `git status`/`git branch
--show-current` showed the working tree clean, on
`claude/phase-11-model-evolution-7hpibr` at HEAD
`b957ac2bd45befe6bcea3e8ca110f34417518623` ("Update README to Phase 11
status"). `git log --oneline --graph --decorate --all` confirmed a
single linear history (`Initial commit → Phase 0 → … → Phase 11 →
README update`), zero merge commits, and `git merge-base --is-ancestor`
confirmed both handoff-supplied reference commits
(`483600fb571c2f392bcc193f7ebbe733b6122a4b` "Phase 10: Counterfactual /
Attribution" and `1f0194f89d24a33db57af8f2d0c0eb4a605d29ed` "Phase 11:
Model Evolution") are genuine ancestors of the current HEAD. No remote
branch named for Phase 12 existed yet (`git branch -r` after `git fetch
--prune`), so a new branch, `claude/phase-12-ai-gateway`, was created
from this verified HEAD — not from `main` (which is still only
`Initial commit`), avoiding the exact lineage mistake Phase 11's
handoff flagged from its own prior session. Dependencies were already
installed from the prior session; the full suite was run before any
Phase 12 code was written: **669/669 tests passed** on the branch point.

## 1. Scope

Per `PROJECT_MASTER_PLAN.md` §18.1 (Phase 12 = "AI Gateway") and §5-6
(the AI API Gateway architecture and the free-tier quota rotation
requirements), this phase implements:

- **The single AI-call entry point** (`ai_gateway.gateway.AIGateway`),
  matching §5's pipeline: `Application → AI Gateway → Task Router →
  Quota Manager → Provider Selector → Provider Adapter → AI Provider`.
- **`AIProviderAdapter` Protocol** matching §5.1's interface
  (`generate`/`stream`/`estimate_usage`/`get_usage`/`health_check`/
  `get_limits`), with exactly one shipped implementation:
  `ai_gateway.provider.MockProviderAdapter` — deterministic, offline,
  no real network call, no API key ever read.
- **`TaskRouter`** (§5.2): routes by `TaskTier` (LOW/MEDIUM/HIGH), each
  provider declaring which tiers it supports.
- **`QuotaManager`** (§6.3-6.4): tracks every field §6.3 lists
  (minus the literal secret value — `api_key_reference` is a name, per
  §14.2) as an append-only `ProviderQuotaState` history, and is the
  single fail-closed gate (`is_available`) every routing decision goes
  through.
- **`ProviderSelector`** (§5's pipeline stage between Quota Manager and
  Provider Adapter): narrows the Task Router's ordered candidates to
  what is actually available right now.
- **Response validation** (§5.3): schema/JSON/missing-field/
  invalid-value detection, so a malformed provider response is never
  passed through as a trusted result.
- **Provider rotation / failover** (§6.2, §6.5): quota-exhausted →
  next provider; all exhausted → a safe, factual failure, never a
  fabricated response, never an automatic switch to a paid tier.
- **Persistence**: three new DuckDB tables
  (`ai_requests`, `ai_responses`, `provider_quota_states`).

### 1.1 Explicitly out of scope (per the handoff and Master Plan §18.4)

- **A real AI provider connection.** `MockProviderAdapter` is the only
  shipped adapter; nothing in `ai_gateway.*` reads `os.environ`/
  `os.getenv`, imports a network library (`socket`/`http`/`urllib`/
  `requests`/`httpx`), or requires an API key
  (`tests/ai_gateway/test_ai_gateway_boundary.py`).
- **Decision Agent / Risk Engine / Position Sizing / Order Creation /
  Broker.** The Gateway cannot even express a trading decision:
  `trade_journal.enums.DecisionAction` is never imported anywhere in
  `ai_gateway.*` (verified by AST scan), and no type in this package has
  an order/broker/risk-shaped field.
- **Model Evolution `APPROVED`/`DEPLOYED`.**
  `learning.enums.CandidateModelStatus` is never imported anywhere in
  `ai_gateway.*` either — this phase cannot approve or deploy a
  candidate even by accident, because the vocabulary to do so is never
  present.
- **Toss Securities Adapter (Phase 13), Monitoring/Drift (Phase 14),
  Paper Trading (Phase 15), Live Trading (Phase 16).** Untouched.
- **`stream()` as a real streaming interface.** `AIProviderAdapter.
  stream()` exists (per §5.1's named interface) and
  `MockProviderAdapter.stream()` implements it (two deterministic
  chunks of the same content `generate()` would produce) so the
  Protocol is complete and testable, but nothing in this phase's
  `AIGateway` calls it — there is no streaming consumer yet.

## 2. Architecture boundary

The Gateway sits after Model Evolution in the layer order the handoff
specifies (`Data → Feature → Regime → Prediction → Decision → Position
Sizing → Risk → Learning → Model Evolution → AI Gateway → …`). It is a
sibling utility layer, not an authority over any of them:

| It is **not** | Why |
|---|---|
| Decision Agent | never imports `DecisionAction`, never returns BUY/SELL/HOLD/EXIT/NO_TRADE |
| Risk Engine | no risk_limit/position_limit field or method anywhere |
| Position Sizer | no target_weight/target_quantity field |
| Order Creator | no order_id/quantity/side field |
| Broker | no broker call, no network import at all |
| Model Registry | never imports `CandidateModelStatus`, cannot approve/deploy |
| Monitoring | out of scope; no alerting/drift code |

`tests/ai_gateway/test_ai_gateway_boundary.py` verifies every row
structurally (reflection + AST scan), not just by convention.

## 3. Pipeline

```
AIRequest (caller-built)
   -> AIGateway.generate(request, as_of=...)
      -> TaskRouter.candidates_for(tier)          [no configured provider -> MISSING_CONFIGURATION]
      -> ProviderSelector.select(tier, as_of=...)  [nothing available -> NO_PROVIDER_AVAILABLE]
      -> for each candidate, in priority order:
           AIProviderAdapter.generate(request)
             -> ProviderAuthError    -> QuotaManager.mark_unavailable, try next provider
             -> ProviderRateLimitError -> QuotaManager.mark_quota_exhausted, try next provider
             -> ProviderTimeoutError -> QuotaManager.record_error, retry same provider (max_retries)
             -> ProviderError        -> QuotaManager.record_error, retry same provider (max_retries)
             -> success              -> ai_gateway.validation.validate_response_content
                  -> invalid  -> QuotaManager.record_error, try next provider
                  -> valid    -> QuotaManager.record_success, return AIResponse(SUCCESS)
      -> every candidate exhausted -> return AIResponse(<last concrete failure status>)
```

`AIResponse.status` always reflects the specific, last-known failure
reason (`TIMEOUT`/`AUTH_FAILED`/`RATE_LIMITED`/`INVALID_RESPONSE`/
`PROVIDER_ERROR`) rather than a single generic bucket, except when zero
candidates were ever attempted: `MISSING_CONFIGURATION` (nothing
configured for the tier at all) or `NO_PROVIDER_AVAILABLE` (something is
configured, but the Quota Manager's pre-check found nothing currently
usable) — a deliberate choice documented in ADR-0018 §2.

## 4. Data Model

- `AIRequest` — opaque, already-built `payload: str` the caller
  assembled; `task_tier`; `prompt_template_id`/`prompt_template_version`
  (prompt/template versioning, §6 below); optional `response_schema`
  (required JSON keys, when the caller expects structured output).
- `AIResponse` — always exactly one of `status == SUCCESS` with
  `content` set, or `status != SUCCESS` with `content=None` and a
  factual `error_reason` (enforced in `__post_init__`, not just by
  convention). Carries `provider_id`/`model`/`prompt_template_version`/
  `configuration_version`/`attempt_count`/`usage` for lineage (§6).
- `ProviderQuotaState` — one observation per point in time (mirrors
  `regime.models.RegimeObservation`'s pattern, Phase 5), never mutated;
  a provider's current state is its most recent observation.
- `UsageInfo`/`ProviderLimits`/`UsageEstimate` — small value types
  matching §5.1's `estimate_usage`/`get_usage`/`get_limits`.

## 5. Fail-Closed Behavior

| Situation | Result |
|---|---|
| Provider unavailable (never initialized / disabled / `UNAVAILABLE`/`UNKNOWN` health) | `QuotaManager.is_available` → `False`, skipped by `ProviderSelector` |
| Timeout | `ProviderTimeoutError` → recorded, retried up to `max_retries` on the same provider, then next provider |
| Malformed / unparseable / missing-field response | `ai_gateway.validation` → `INVALID_RESPONSE`, `content=None`, next provider (not retried on the same one — a deterministic provider would repeat the same malformed output) |
| Missing configuration (no provider at all for the tier) | `MISSING_CONFIGURATION`, zero attempts |
| Authentication failure | `ProviderAuthError` → `QuotaManager.mark_unavailable` (not retried — retrying an auth failure cannot succeed), next provider |
| Rate limit | `ProviderRateLimitError` → `QuotaManager.mark_quota_exhausted`, next provider |
| Provider error (generic) | `ProviderError` → recorded, retried up to `max_retries`, then next provider |
| Billing/paid status detected | `QuotaManager.mark_billing_detected` (deterministic-code call only, never triggered by AI-generated response content) → provider unavailable regardless of remaining quota, `PROJECT_MASTER_PLAN.md` §1.5 |
| Free quota state genuinely unknown | `BillingStatus.UNKNOWN`/`ProviderHealthStatus.UNKNOWN` are treated exactly like the corresponding "definitely bad" state — never assumed usable (§6.4's "보수적으로 처리한다") |
| Every candidate exhausted/failed | `AIResponse` with `status != SUCCESS`, `content=None` — never a fabricated result, never an automatic switch outside the configured provider list |

None of these paths raises an unhandled exception out of
`AIGateway.generate` for a provider-side failure — every one produces a
typed `AIResponse`.

## 6. Provider / Model Versioning & Lineage

`AIResponse` carries `provider_id`, `model` (already version-qualified,
e.g. `"mock-model-v1"`), `prompt_template_version`, `configuration_version`
(`ProviderConfig.configuration_version()` when a provider was attempted,
else `GatewayConfig.configuration_version()`), `attempt_count`, and
`usage` — enough to answer "which provider/model/config/prompt version
produced this, and how many attempts did it take" without ever needing
to replay a real network call. `ProviderQuotaState.reason` plus its
append-only history is the audit trail for *why* a provider was or
was not selected at a given time. No secret value is ever part of this
lineage — `ProviderConfig.api_key_reference` is a name
(`tests/ai_gateway/test_ai_gateway_secret_safety.py`).

## 7. Point-in-Time / Leakage Protection

`AIGateway.generate(request, *, as_of)` takes an already-built
`AIRequest` and an explicit `as_of` timestamp with no default — it never
calls `datetime.now()`/`datetime.utcnow()`, and nothing in `ai_gateway.*`
imports `data_infra.repository.DataRepository` or
`backtest.asof.AsOfDataView` (AST-scanned, not just read). `AIRequest.
payload` is a plain string the caller assembled — there is no field
through which a security_id/date-range could be threaded in for the
Gateway to go fetch data itself. `as_of` only ever gates quota/reset-
window availability; it never rewrites already-recorded
`ProviderQuotaState` history.

## 8. Secrets

`ProviderConfig.api_key_reference` is an environment-variable *name*
(matching the placeholders `.env.example` already reserved in Phase 0:
`AI_PROVIDER_A_API_KEY`/`AI_PROVIDER_B_API_KEY`/`AI_PROVIDER_C_API_KEY`)
— never a value. This phase makes no real provider call, so nothing here
ever needs to resolve that name to an actual secret; `os.environ`/
`os.getenv` do not appear anywhere in `ai_gateway/*.py`
(`tests/ai_gateway/test_ai_gateway_boundary.py`). Persisted
`AIRequest`/`AIResponse`/`ProviderQuotaState` payloads are checked to
contain no secret-shaped substring (`tests/ai_gateway/
test_ai_gateway_secret_safety.py`).

## 9. Persistence

Three new tables in Phase 4's existing DuckDB catalog file
(`src/storage/schema.py`, purely additive — `git diff | grep '^-'`
shows zero deleted/changed lines):

- `ai_requests` / `ai_responses` — dedupe on the caller-assigned
  `request_id`/`response_id` directly (the same pattern Phase 5-8's
  `decisions`/`predictions`/`regime_observations` tables already use) —
  unlike a content-addressed artifact, a request/response log has no
  meaningful content-based natural key (see ADR-0018 §4 for why this
  differs from Phase 9/11's re-allocated-id fix).
- `provider_quota_states` — append-only (seq-ordered), the same
  `regime_observations`/`attribution_results`/`model_status_transitions`
  pattern.

`ai_gateway.repository`'s Protocols + `InMemory*` reference
implementations, and `storage.ai_gateway_repository`'s DuckDB
implementations, follow the identical Protocol/idempotency/restart
discipline every prior phase's repository layer already established.

## 10. Reproducibility

No module in `ai_gateway.*` imports `random` or calls
`datetime.now()`/`datetime.utcnow()`
(`tests/ai_gateway/test_ai_gateway_reproducibility.py`, an AST scan).
An end-to-end test runs the full Gateway → TaskRouter → QuotaManager →
ProviderSelector → MockProviderAdapter → validation chain twice from
identical inputs and asserts byte-identical output.

## 11. Lineage Traceability

```
AIRequest -> AIResponse (1:many via get_by_request's "latest" read)
ProviderConfig -> ProviderQuotaState (append history, one chain per provider_id)
```

`tests/integration/test_ai_gateway_lineage.py` proves this is
SQL-joinable (`ai_requests`⋈`ai_responses`, correlated against
`provider_quota_states` by `provider_id`) and survives a process
restart, including the "all providers exhausted" safe-failure case still
being fully persisted and re-readable.

## 12. Test Strategy

| Category | File |
|---|---|
| Provider abstraction | `tests/ai_gateway/test_ai_gateway_provider.py` |
| Response validation | `tests/ai_gateway/test_ai_gateway_validation.py` |
| Quota Manager / fail-closed rotation | `tests/ai_gateway/test_ai_gateway_quota_manager.py` |
| Task Router | `tests/ai_gateway/test_ai_gateway_task_router.py` |
| Provider Selector | `tests/ai_gateway/test_ai_gateway_provider_selector.py` |
| Gateway integration (§6.5 scenarios) | `tests/ai_gateway/test_ai_gateway_gateway.py` |
| Boundary | `tests/ai_gateway/test_ai_gateway_boundary.py` |
| Reproducibility | `tests/ai_gateway/test_ai_gateway_reproducibility.py` |
| Point-in-time / leakage | `tests/ai_gateway/test_ai_gateway_point_in_time.py` |
| Secret safety | `tests/ai_gateway/test_ai_gateway_secret_safety.py` |
| Persistence / restart / idempotency | `tests/storage/test_ai_gateway_repository.py` |
| Integration lineage | `tests/integration/test_ai_gateway_lineage.py` |

## 13. Definition of Done

- [x] Implementation matching this spec
- [x] Unit + integration tests, all passing (see completion report for exact counts)
- [x] Error handling: every provider failure mode produces a typed,
      factual `AIResponse`, never an unhandled exception or a fabricated
      success
- [x] Logging/audit: `ProviderQuotaState.reason` + append history is the
      audit trail for every quota/health/billing change
- [x] Documentation: this spec + ADR-0018
- [x] Configuration: `ProviderConfig`/`GatewayConfig` — no hardcoded
      thresholds, no hardcoded/required API keys
- [x] Validation: structural boundary tests confirm no order/broker/
      risk/decision/model-approval capability and no real secret access
