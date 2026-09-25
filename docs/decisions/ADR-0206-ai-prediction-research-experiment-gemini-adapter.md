# ADR-0206: AI prediction research experiment -- a real Gemini provider adapter, deliberately isolated from the trading pipeline

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session, account owner (explicit request)

**Related documents:** `docs/specifications/PHASE-12-ai-gateway.md`,
`docs/decisions/ADR-0018-ai-gateway-design.md` (if present) / Phase 12's
own handoff, `docs/decisions/ADR-0151-...md` ("adopt now, wire in
later" precedent), `PROJECT_MASTER_PLAN.md` sections 1.5, 5, 6.

## Context

The account owner asked for a new, standalone research experiment,
explicitly separate from the real trading pipeline: how well does an LLM
(Google Gemini, via the account owner's own `GEMINI_API_KEY`) predict a
security's short-term price direction? This is the first real (non-mock)
caller `ai_gateway.gateway.AIGateway` has ever had in this codebase --
CLAUDE.md's "Grounding Gate 배선 보류 결정" (2026-09-24) section
explicitly named this exact trigger ("실제 AI 기반 predictor/decision
agent를 새로 만들 때... 이 시점에 다시 꺼내서") as the point to revisit
that deferred decision, so this ADR also addresses it (see "Grounding
Gate" below).

Phase 12 shipped `ai_gateway.*` as mock-only, offline, by explicit
design (`docs/specifications/PHASE-12-ai-gateway.md` section 1.1:
"Explicitly out of scope: A real AI provider connection... nothing in
`ai_gateway.*` reads `os.environ`/`os.getenv`, imports a network library
... or requires an API key"), verified structurally by
`tests/ai_gateway/test_ai_gateway_boundary.py`'s AST scans. A real
adapter needed to be added without breaking that phase's own documented
guarantees, and without ever letting predict/decision/risk/broker reach
a real network call.

## Decision

### 1. A real adapter lives in a new `ai_gateway.providers` subpackage, not in `ai_gateway.provider`

`src/ai_gateway/providers/{__init__,gemini_auth,gemini_transport,gemini}.py`
mirrors `data_infra.providers.*` (Tiingo/Alpha Vantage/Stooq/Twelve
Data) sitting alongside `data_infra.provider`'s own generic Protocol the
exact same way -- config/auth/transport split, stdlib `urllib.request`
only (no new dependency), secrets isolated to one `*_auth.py` file.

This was a deliberate choice over two rejected alternatives:
- **Adding a real adapter directly to `ai_gateway/provider.py`** --
  would have broken `test_ai_gateway_boundary.py`'s `test_no_os_environ_
  or_getenv_call_anywhere`/`test_mock_provider_adapter_makes_no_network_
  call`/`test_mock_adapter_is_the_only_shipped_adapter_class`, each of
  which is a real, currently-true guarantee about the flat package;
  breaking them to add a research side-experiment would have been the
  wrong trade.
- **Rewriting those tests to accept a real adapter in the flat
  package** -- would have erased Phase 12's own documented boundary
  (mock-only, offline) for the CORE Gateway/Router/QuotaManager
  pipeline every future phase reads as ground truth, not just for this
  one experiment.

`tests/ai_gateway/test_ai_gateway_boundary.py` is **unmodified** --
`_package_files()` globs only `ai_gateway/*.py` (non-recursive), so it
never sees the new subpackage, and every one of its assertions about the
flat package remains literally true. `src/ai_gateway/__init__.py`'s own
docstring was updated to say so explicitly, so a future reader is not
misled by the "no real network call" claim into thinking no real adapter
exists anywhere in `ai_gateway.*`.

A new test file, `tests/ai_gateway/test_ai_gateway_gemini_boundary.py`,
carries the boundary guarantee that actually matters for a real adapter:
secrets stay isolated to `gemini_auth.py` alone, the adapter still
cannot express a `DecisionAction`/`CandidateModelStatus`, and --
verified by AST scan across `src/predict/`, `src/decision/`, `src/risk/`,
`src/broker/` -- **none of those packages import `ai_gateway.providers`
at all**.

### 2. Verified against a real Gemini API call (not just documentation)

Unlike this project's market-data providers (Tiingo etc., built only
against Tier 2 documentation, "never exercised against a live response
in this environment"), this adapter's request/response shape WAS
verified directly: `curl`-level probes during design, then a full,
real, end-to-end `AIGateway.generate()` call via
`scripts/verify_gemini_adapter.py` (2026-09-25, account owner's own
`GEMINI_API_KEY`) -- `status: SUCCESS`, real token usage returned,
`attempt_count: 2` showing the Gateway's own retry-on-transient-error
path also fired and recovered for real.

Two real facts this design would have gotten wrong from documentation
alone, both now encoded directly in `ai_gateway.providers.gemini_
transport`'s own docstring and its tests:
1. A 429 response carries **no `Retry-After` HTTP header** -- the real
   retry signal is inside the JSON error body
   (`error.details[].retryDelay`, a protobuf-duration string like
   `"18s"`). A header-only implementation (the generic HTTP convention
   this codebase's other transports use) would have silently gotten
   `retry_after_seconds=None` on every single real 429, defeating the
   whole point of `ProviderRateLimitError.retry_after_seconds` (Session
   36's own fix, referenced in `ai_gateway.provider`'s docstring).
2. `gemini-3.8-flash` is a "thinking" model by default -- real usage
   includes a `thoughtsTokenCount` not captured by `promptTokenCount`/
   `candidatesTokenCount` alone, so `UsageInfo.total_tokens` is read
   from Gemini's own `totalTokenCount` field directly, never
   reconstructed by summing the other two.
3. The real free-tier rate limit for this model is **5 requests/minute**
   (from a real 429 response body: `"limit: 5, model: gemini-3.8-flash"`)
   -- `DEFAULT_GEMINI_PROVIDER_CONFIG.rpm_limit=5` records this real,
   confirmed number; `rpd_limit`/`tpm_limit`/`tpd_limit` stay `None`
   (honestly "not confirmed"), never a guessed number.

One assumption remains genuinely unverified and is disclosed as such in
`ai_gateway.providers.gemini`'s own docstring: whether
`generationConfig.thinkingConfig.thinkingBudget: 0` actually suppresses
thinking-token spend for this model (named after the equivalent
Gemini 2.5-generation parameter) -- the free tier's 5 RPM was already
spent confirming everything else above before this one field could be
checked against a real response.

### 3. `scripts/run_ai_prediction_experiment.py` -- the actual experiment

Two subcommands:
- `predict`: for each security in a universe, reads real, point-in-time
  price history via `storage.data_repository.DuckDBDataRepository`
  (the same `DataRepository` Protocol backtest/strategy_research use --
  this experiment never sees data that would not have been available
  `--as-of` that date), builds a prompt, calls `AIGateway.generate()`
  through `GeminiProviderAdapter`, and persists the request/response
  into the **existing, unmodified** `ai_requests`/`ai_responses` DuckDB
  tables (Phase 12's own schema -- no new table, no migration), plus a
  small human-readable JSON sidecar under
  `docs/research/reports/ai_prediction_experiment/` (the same
  "permanent JSON report" convention `run_full_validation.yml` already
  established) recording `{security_id, as_of, predicted_direction,
  predicted_confidence, ...}` -- reusing `AIRequest`/`AIResponse.
  experiment_id` rather than inventing a second identity scheme.
- `score`: reads a `predict` sidecar file, looks up the now-realized
  price move for each prediction whose target trading day has passed
  (again via `DataRepository`, respecting the same point-in-time
  discipline), and reports directional accuracy (`UP`/`DOWN`/`FLAT`
  vs. actual). Never mutates what `predict` wrote.

Client-side pacing (`--pause-seconds`, default 13s) is the caller's own
responsibility, not `QuotaManager`'s: `QuotaManager` today only tracks
`rpd_limit`/`tpd_limit` (per-day) proactively, never `rpm_limit`/
`tpm_limit` (confirmed by reading `ai_gateway.quota_manager` -- no
per-minute enforcement exists anywhere in the Gateway pipeline). Adding
proactive per-minute pacing to `QuotaManager` itself, mirroring
`data_infra.providers.tiingo_transport`'s own `TiingoRequestBudget`,
was considered and deliberately deferred as scope creep for a
research-only side experiment -- the reactive path (a real 429 ->
`ProviderRateLimitError` with a real, body-parsed `retry_after_seconds`
-> `QuotaManager.mark_quota_exhausted`) is a correct, if less
proactive, backstop, and `verify_gemini_adapter.py`'s own real run
(`attempt_count: 2`) demonstrates it actually recovers from a transient
failure on its own.

Verified end to end (offline, `urllib.request.urlopen` stubbed):
`tests/scripts/test_run_ai_prediction_experiment.py`, seeding a real
DuckDB catalog via `backtest_helpers.make_bars`/`make_security`
(mirroring `tests/scripts/test_run_monitoring_sweep.py`'s own
precedent), covering: a successful predict+persist round trip,
insufficient-history skip, a scored correct prediction against a real
realized price move, and a pending (not-yet-realized) outcome.

### 4. `AIRequest.provenance`/`AIResponse.provenance`: reused `HISTORICAL_SIMULATION`, no new `TradeProvenance` value added

`trade_journal.enums.TradeProvenance` is a deliberately closed,
system-wide triad (`HISTORICAL_SIMULATION | PAPER_TRADING |
LIVE_TRADING`) -- `PROJECT_MASTER_PLAN.md` section 10.7 names exactly
these three as required for classifying Experience Dataset training
data ("이 구분 없이 세 가지 출처의 데이터를 섞어서 학습하지 않는다"),
and `regime/enums.py`'s own docstring calls it "exactly like every other
record this project keeps a permanent history of." Adding a fourth
value for this one side experiment risked widening a load-bearing,
system-wide vocabulary for a narrow, one-off need.

This experiment tags its `AIRequest`/`AIResponse` rows
`TradeProvenance.HISTORICAL_SIMULATION` instead -- the closest existing
meaning (an offline analysis against already-ingested historical data,
never live/paper trading activity). This has no real contamination
risk for the Experience Dataset that section 10.7's rule actually
protects: `ai_requests`/`ai_responses` are Phase 12's own tables,
never read by `src/learning/cleaning.py`, `src/trade_journal/
experience.py`, or anything else in the Experience Dataset conversion
path (grep-verified across `src/` before this decision: zero references
to `ai_gateway.repository`/`ai_gateway.models.AIRequest`/`AIResponse`
outside `ai_gateway.*` and this experiment's own script). If a future
session ever builds something that reads `ai_requests`/`ai_responses`
INTO the Experience Dataset, it must re-examine this reuse at that
point -- this ADR's reasoning here does not hold if that ever becomes
true.

### 5. Grounding Gate wiring: still not exercised, and correctly so

CLAUDE.md's 2026-09-24 "Grounding Gate 배선 보류 결정" named "a real
AI-based predictor/decision agent... i.e. the first call site that
actually uses `response_schema`" as the condition to revisit whether
`ai_gateway.grounding.evaluate_formula`/`validate_derived_value` and
`decision.entropy.normalized_entropy` should be wired in. This
experiment IS such a first call site (`AIRequest.response_schema =
("direction", "confidence", "reasoning")`) -- but it is a **research
experiment**, not the real predictor/decision agent that deferral was
actually about, and its schema has no numeric field derived from a
deterministic formula the Grounding Gate could check (`direction`/
`reasoning` are free-form; `confidence` is the model's own
self-reported number, not a value re-derivable from a formula this
codebase owns). `validate_derived_value` has nothing to validate here
by construction. The Grounding Gate's reactivation condition therefore
remains open for whenever a real predict/decision-facing AI caller is
built -- this ADR does not close it, and this experiment never imports
`ai_gateway.grounding`.

## Consequences

### Positive
- A genuine, real-API-verified research capability now exists, answering
  the account owner's actual question (does an LLM predict direction
  better than chance?) without touching a single file in
  predict/decision/risk/broker.
- Phase 12's original mock-only boundary guarantees for the CORE Gateway
  pipeline are unchanged and still verified by the unmodified
  `test_ai_gateway_boundary.py` -- this ADR adds a sibling boundary
  (`test_ai_gateway_gemini_boundary.py`) rather than loosening the
  original one.
- The real-API verification (not just Tier 2 documentation) caught a
  real design bug before it shipped: a header-only Retry-After parser
  would have silently never recovered from a real Gemini rate limit.

### Negative / Trade-offs
- `GeminiProviderAdapter`'s `thinkingConfig.thinkingBudget: 0` is an
  unverified assumption (disclosed in its own docstring) -- if it does
  nothing, real runs will spend more tokens/quota on thinking than
  necessary until a future session confirms and either fixes or removes
  it.
- `QuotaManager` still has no proactive per-minute pacing; this
  experiment's own `--pause-seconds` is a script-level workaround, not a
  Gateway-level fix. A second real provider with a tighter RPM limit
  would need the same workaround repeated, or `QuotaManager` genuinely
  extended at that point.
- Reusing `HISTORICAL_SIMULATION` for a fundamentally different kind of
  record (an AI prediction log, not a simulated trade) is a real,
  disclosed semantic compromise, chosen over widening a system-wide enum
  for one side experiment. If `ai_requests`/`ai_responses` are ever
  consumed by the Experience Dataset pipeline, this choice must be
  revisited (see Decision 4).
- `GEMINI_API_KEY` still needs to be added as a GitHub Actions repository
  secret (Settings -> Secrets and variables -> Actions) for
  `.github/workflows/verify_gemini_adapter.yml` to run in CI -- it is
  only set in this interactive session's own environment today.

## Tests

`tests/ai_gateway/test_ai_gateway_gemini_auth.py`,
`test_ai_gateway_gemini_transport.py`,
`test_ai_gateway_gemini_adapter.py`, `test_ai_gateway_gemini_boundary.py`
(all offline, no real network call). `tests/scripts/
test_run_ai_prediction_experiment.py` (offline, real seeded DuckDB
catalog). `scripts/verify_gemini_adapter.py` was additionally run once,
for real, in this session (`GEMINI_API_KEY` already present in the
environment) -- `status: SUCCESS`, confirming the whole pipeline
end-to-end, not just its offline test doubles.

Full suite run before merge as the merge gate (see PR).
