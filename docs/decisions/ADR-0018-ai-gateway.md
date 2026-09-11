# ADR-0018: AI Gateway

**Status:** Accepted

## Context

`PROJECT_MASTER_PLAN.md` §18.1 lists Phase 12 as "AI Gateway." §5
defines the required pipeline (`Application → AI Gateway → Task Router →
Quota Manager → Provider Selector → Provider Adapter → AI Provider`) and
the `AIProvider` interface
(`generate/stream/estimate_usage/get_usage/health_check/get_limits`).
§6 requires free-tier quota rotation/failover across providers with a
hard rule: exhausting every configured provider must produce "NO AI
CALL / safe failure," never an automatic switch to paid usage. §18.4
explicitly permits this phase (unlike Phase 0-11) to build real AI API
integration scaffolding, but requires it to work safely without a real
API key ("실제 API 키 없이도 안전하게 동작(mock/무료 한도 검증)함을
우선 확인한다"). The handoff for this session reinforced the same
constraints and explicitly forbade connecting to a real AI service,
requiring/hardcoding an API key, and letting the Gateway bypass
Decision/Risk/Position Sizing or reach `CandidateModelStatus.APPROVED`/
`DEPLOYED`.

This session's Git/Branch Integrity Check (see
`docs/specifications/PHASE-12-ai-gateway.md` §0) found the repository in
a clean, correctly-lineaged state on `claude/phase-11-model-evolution-7hpibr`
and created a new branch, `claude/phase-12-ai-gateway`, from that
verified HEAD — the prior session's own branch-lineage mistake (Phase
11 having been rooted on `main` instead of the real Phase 0-10 history)
was checked for and not repeated.

## Decision

### 1. Ship exactly one provider adapter — `MockProviderAdapter` — and no
   real network code at all

The instruction is explicit: no real AI service connection, no required/
hardcoded API key. Rather than building a real provider adapter behind a
feature flag (which would still require *some* real HTTP client
dependency and a credible path to accidentally calling out), this phase
adds no network library dependency at all — `pyproject.toml` still
declares only `duckdb`/`pyarrow` after this phase.
`MockProviderAdapter` deterministically simulates every scenario
§6.5 requires (success, quota exhaustion, all-providers-fail, quota
reset, billing detection) via a `failure_mode` constructor parameter,
the same "baseline/mock first, prove the pipeline, not a real provider"
precedent every prior phase's own reference implementation already
established (`RandomWalkPredictor`, `MeanRewardBaselineTrainer`,
`TrailingWindowMeanTrainer`). `tests/ai_gateway/
test_ai_gateway_boundary.py` verifies structurally (AST scan) that no
`socket`/`http`/`urllib`/`requests`/`httpx` import and no
`os.environ`/`os.getenv` call exists anywhere in the package.

### 2. `AIResponse.status` reports the last concrete failure reason, not
   a single collapsed "NO AI CALL" bucket — except when zero providers
   were ever attempted

Two designs were possible for the failure path: (a) always collapse to
one `NO_PROVIDER_AVAILABLE` value once every candidate is exhausted
(closely mirroring §6.2's literal "NO AI CALL" language), or (b) report
the specific last-known reason (`TIMEOUT`/`AUTH_FAILED`/`RATE_LIMITED`/
`INVALID_RESPONSE`/`PROVIDER_ERROR`) whenever at least one provider was
actually attempted, reserving `NO_PROVIDER_AVAILABLE`/
`MISSING_CONFIGURATION` for the case where nothing was attempted at
all. This ADR picks (b): §5.3 requires the Gateway's failure handling to
be specific and auditable ("AI 응답 신뢰성"), and a caller debugging
"why did this fail" is better served by a factual, specific
`RequestStatus` than a single opaque bucket. The *safety property* §6.2
actually cares about — never fabricating a response, never silently
upgrading to a paid provider — holds identically either way, since it is
enforced by `AIResponse.__post_init__` (a non-`SUCCESS` response can
never carry `content`), not by which specific enum value is chosen.

### 3. `ProviderQuotaState` is an append-only observation history, not a
   mutable record

Continuing the same discipline `regime.models.RegimeObservation` (Phase
5), `trade_journal.models.PostTradeAnalysis`/`CounterfactualRecord`
(Phase 3/10), and `evolution.models.ModelStatusTransition` (Phase 11)
already established: every quota/health/billing change is a new,
appended record, never a mutation of a prior one. A provider's *current*
state is always its most recent observation
(`QuotaStateRepository.get_latest`). This gives §15's "왜 provider가
전환되었는가" auditability question a real, queryable answer for free.

### 4. `ai_requests`/`ai_responses` dedupe on the caller-assigned id
   directly; no storage-level id re-allocation (unlike Phase 9/11)

ADR-0015 §6 and ADR-0017 §7 both found and fixed a real defect class:
independent in-process id allocators can collide across independent
runs for a *content-addressed* artifact (`TrainingDataset`,
`CandidateModelArtifact`, `ModelLineageRecord`), where the fix is to let
a storage-level sequence assign the definitive id and dedupe on a
content-based natural key instead. That fix does not transfer here: an
`AIRequest`/`AIResponse` is an event log entry, not a content-addressed
artifact — two requests with byte-identical payloads sent at different
times are two distinct, legitimate events, not duplicates of one
another, so there is no meaningful content-based natural key to dedupe
on. Instead, `ai_requests`/`ai_responses` follow the *other* precedent
this codebase already established for id-carrying event records —
Phase 5-8's `decisions`/`predictions`/`regime_observations` tables,
which trust the caller-assigned id and dedupe on it directly. A single
long-lived `AIGateway` instance's own `_IdAllocator` is the source of
those ids, the same pattern `decision.agent.BaselineRuleDecisionAgent`/
`predict.predictor.DriftPredictor` already use for `decision_id`/
`prediction_id`.

### 5. `QuotaManager.mark_billing_detected` is a deterministic-code-only
   entry point, never reachable from AI-generated response content

`PROJECT_MASTER_PLAN.md` §1.5 lists "free API billing policy" among the
things AI cannot change itself. The method exists (a caller — a human or
an external monitoring process, never `ai_gateway.*` itself — needs a
way to flip a provider to `PAID_DETECTED`), but no code path inside
`ai_gateway.gateway.AIGateway.generate` calls it based on
`AIResponse.content`/`parsed` — the only two callers of
`mark_billing_detected` in this codebase are `QuotaManager` itself
(never) and test code. `tests/ai_gateway/test_ai_gateway_boundary.py`'s
AST scan additionally confirms no `.APPROVED`/`.DEPLOYED` reference and
no `DecisionAction`/`CandidateModelStatus` import exists anywhere in the
package, so even an unrelated future edit could not accidentally wire
AI output into a trading or model-approval decision through this
module.

### 6. `stream()` is implemented on the Protocol and the Mock adapter,
   but never called by `AIGateway`

`PROJECT_MASTER_PLAN.md` §5.1 names `stream()` as part of the required
interface. Rather than omitting it (incomplete interface fidelity) or
building a real streaming consumer this phase has no use for (scope
creep), `MockProviderAdapter.stream()` is implemented trivially
(yields `generate()`'s own content in two deterministic chunks) so the
Protocol is complete and testable, while `AIGateway.generate` — the only
orchestration this phase needs — never calls it. A future phase that
needs real streaming has a proven interface shape to extend rather than
design from scratch.

### 7. Retryable vs. non-retryable failures are a fixed, small
   classification, not a generic "retry N times on any error" policy

`ProviderTimeoutError`/`ProviderError` (generic) are retried on the same
provider up to `ProviderConfig.max_retries` — both are plausibly
transient. `ProviderAuthError` (retrying cannot fix bad credentials) and
a validation failure (a deterministic mock/provider would reproduce the
same malformed output) are never retried on the same provider — they
move straight to the next candidate. `ProviderRateLimitError` is treated
as an immediate quota-exhaustion signal (`mark_quota_exhausted`) rather
than a local retry, since hammering a rate-limited provider is exactly
the failure mode §6 exists to prevent.

## Alternatives Considered

1. **A real (but "safe-by-default") provider adapter guarded by a
   feature flag.** Rejected — see decision 1; the instruction's "실제
   AI 서비스에 임의로 연결하지 말 것" is unconditional for this phase,
   and any real adapter still requires a real HTTP dependency this
   phase should not add unilaterally.
2. **Collapse every exhaustion path to a single `NO_PROVIDER_AVAILABLE`
   status.** Rejected — see decision 2; loses diagnostic information
   §5.3 asks the Gateway to preserve, without buying any additional
   safety property.
3. **Re-allocate `request_id`/`response_id` from a storage-level
   sequence, mirroring Phase 9/11's fix.** Rejected for this phase — see
   decision 4; the underlying problem (content-addressed dedup) doesn't
   apply to an event log, and forcing it on would silently collapse
   legitimately-repeated requests into one record.
4. **Let `AIGateway` call `mark_billing_detected` automatically when a
   response's `parsed` content contains a billing-related keyword.**
   Rejected outright — this is precisely the "AI가 free API billing
   policy를 스스로 바꾸는" pattern `PROJECT_MASTER_PLAN.md` §1.5
   forbids; billing state must come from a deterministic, out-of-band
   signal, never from interpreting the provider's own response text.

## Consequences

### Positive

- Zero modifications to Phase 1-11 source files; `git diff | grep '^-'`
  on `src/storage/schema.py` and `src/storage/serialization.py` shows no
  deleted/changed lines, only additions.
- The full §6.5 test matrix (A succeeds; A exhausted → B; A/B/C all fail
  → safe failure; A resets → priority reverts; billing detected →
  disabled) is implemented and passing without any real network access.
- No code path anywhere in `ai_gateway.*` can express a trading decision
  or a model approval/deployment, verified structurally (AST scan), not
  just by convention.
- Every failure mode produces a typed, auditable `AIResponse` — no
  unhandled exception reaches a caller for a provider-side problem.

### Negative / Trade-offs

- Because no real provider adapter exists yet, this phase cannot prove
  behavior against a real API's actual error shapes/rate-limit headers —
  a future phase integrating a real provider will need to map that
  provider's real exceptions onto `ProviderTimeoutError`/
  `ProviderAuthError`/`ProviderRateLimitError`/`ProviderError` itself.
- `RATE_LIMITED` exhaustion with no known `reset_time` (the Mock
  adapter's rate-limit failure mode does not simulate a `Retry-After`
  header) stays exhausted indefinitely until an explicit later
  `record_success`/reset call — a real provider integration will need to
  supply a real reset time from its own rate-limit response headers.
- `ai_requests`/`ai_responses` trusting the caller-assigned id (decision
  4) means a caller that constructs two independent, uncoordinated
  `AIGateway` instances against the same DuckDB catalog *could* produce
  colliding ids for genuinely different requests — the same risk class
  Phase 5-8's tables already carry, not a new gap this phase introduces.
