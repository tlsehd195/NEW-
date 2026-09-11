# ADR-0117: second verification pass residuals — MEDIUM/LOW fixes and one real gap the report itself named

**Status:** Accepted
**Session:** 37 (continued)

## Context

After ADR-0115 (MEDIUM) and ADR-0116 (LOW) merged, the account owner
relayed a THIRD-PARTY VERIFICATION PASS that re-read `main` against the
*original* review report (not the second 16-agent review ADR-0114/0115/
0116 responded to) and found, by direct diff/code inspection against
real commits `055ca6e`/`4f4fcac`: 22 of 32 original MEDIUM findings
genuinely fixed, 1 partially fixed, **9 still open**; the LOW pass had
addressed every doc-pattern item and two real code bugs it found
independently, but had not touched the report's own enumerated LOW
*code* patterns (dead params, `None`-close guards, `get_as_of` tie-
break, docstring/behavior mismatches); and one of the ten originally-
flagged bug-pinning tests (`test_portfolio.py`'s realized-PnL cases)
still used `spread_cost=slippage_cost=0` on every case, so it never
actually exercised the H-2 double-counting fix ADR-0114 made.

**Method, unchanged**: every item was independently re-verified against
the real, current source before any fix — several of the report's own
claims turned out to be imprecise or simply wrong on inspection, and
are recorded as such below rather than "fixed" anyway. Every real fix
carries a regression test verified via `git stash` (or a temporary
revert, where the underlying fix predates this session's diff) to fail
without the fix and pass with it.

## Decision

### The 9 open MEDIUM items

**M-2 — `broker.pipeline`'s module-level `_request_ids`/`_log_response_ids` had no restart-safe seeding, and `status_repository` was a dead parameter.**
Confirmed real: `DuckDBBrokerRequestRepository.record`/
`DuckDBBrokerResponseRepository.record` dedupe on the CALLER-assigned
id itself (no other natural key exists for a request/response log) —
a post-restart id colliding with an already-persisted, unrelated row
silently returns that stale row instead of persisting the new order's
own audit entry. Fixed: `_IdAllocator.advance_past()` plus a new
`seed_broker_pipeline_ids()`, wired into
`run_multi_strategy_paper_trading_cycle.py` (the one real caller)
right after constructing the repositories. `status_repository` was
confirmed genuinely unused by any real caller (`OrderStatusObservation`
recording already happens independently via `PaperTradingSession`) —
removed rather than wired, to avoid inventing a parallel, redundant
mechanism.

**M-4 — `broker.paper.us_longterm_runner`'s risk/sizing/decision ids reset to `-000001` on every call.**
Re-derivation found the report's own causal claim ("client_order_id
collision, silent replay-skip") does not actually hold — `compute_
client_order_id`'s hash already includes `security_id`/`quantity`/
`side`/`as_of_time` directly, so two calls only ever produce the same
`client_order_id` when they describe the literal same order, which is
`compute_client_order_id`'s own documented idempotency-retry
guarantee, not a bug. The real, smaller issue: these synthetic ids ARE
independently persisted into `BrokerRequestRecord.decision_id`/etc for
audit, and two genuinely different real calls sharing the "first
symbol processed" position got the identical `"DEC-BAH-000001"` label,
making the audit trail unable to tell them apart. Fixed by deriving
each id from `(buy_time, security_id)` instead of a per-call counter —
naturally unique per real economic event, no seeding needed since
there is no backing sequence for a synthetic id.

**M-8 — `ml.linear_model`'s singularity guard let a NaN pivot through.**
Confirmed real: `abs(nan) < 1e-12` is `False` in Python (every NaN
comparison is), so a NaN-poisoned input sailed past the guard and
produced a "successfully fitted" model with every coefficient `NaN`,
contradicting the module's own "never a fabricated fit" docstring.
Fixed with an explicit `math.isfinite` check on the pivot, both when
selecting the pivot row and when validating it.

**M-1 — `strategy_research.result_analysis`'s median used the upper element on an even-length list, not the true median.**
Confirmed real: `sorted(returns)[len(returns) // 2]` returns index 2
of a 4-element list (0.03 for `[0.01, 0.02, 0.03, 0.04]`) instead of
the true median 0.025 — a systematic bias on the common case of an
even fold count. Fixed to `statistics.median`, matching `walk_forward_
evaluation.py`'s own established convention for the same statistic.

**M-7 — `risk.sizing`'s HOLD/NO_TRADE branch fabricated a target when `portfolio_state` was unknown.**
Confirmed real: the branch returned `status=PASS` with `proposed_
target_quantity=0.0`/`proposed_target_weight=None` even when
`portfolio_state is None` — "keep the current position" is only a
meaningful target when the current position is actually known, and
this violated both the model's own docstring (`proposed_target_
weight`: "None only when status is UNKNOWN") and §1.4's fail-closed
default. `risk.engine`'s own independent, earlier `portfolio_state`
gate happened to make this unreachable on the real order-construction
path, but the fabricated value was still genuinely persisted into
every `PositionSizingResult` record taking this branch. Fixed: the
HOLD/NO_TRADE branch now returns `UNKNOWN`/`portfolio_state_
unavailable` when `portfolio_state is None`, matching the same gate
`risk.sizing` already applies to every other branch.

**M-5 — `broker.mock.MockBrokerAdapter.get_positions` returned `()` for its own `account_unavailable` simulation, ambiguous with "zero real positions."**
Confirmed real, and the module's own docstring already explicitly
promised `available=False` reporting from `get_positions` that the
code never delivered. `tuple[BrokerPosition, ...]` has no list-level
availability field the way `BrokerAccountSnapshot` does, so fixed by
raising `BrokerTransportError` instead — matching how the real `Toss`
adapter (`broker.toss.mapping.parse_holdings_response`) already
handles the identical ambiguity, and how every other real adapter
failure naturally propagates. Two existing tests that had pinned the
old `()` behavior as correct (one explicitly framed as accepting a
"Known Issue") rewritten to assert the raise instead.

**M-3 — `broker.paper.adapter.get_account` hardcoded `currency="KRW"`.**
Confirmed real: Paper accounting is natively USD-denominated
(`PortfolioAccounting`/`PriceBar` price exclusively in USD, ADR-0025/
ADR-0026 — `broker.paper.us_longterm_config`'s own docstring states
this explicitly), so every real Paper account snapshot's currency
field was mislabeled. Fixed to `"USD"`.

**M-6 — `data_infra.calendar.US_EQUITY`'s toy holiday set (3 dates, 2024 only) is used by real multi-year scripts.**
Confirmed real and materially more consequential than the report's own
framing suggested: `backtest.engine.BacktestEngine.run` calls `repository.
get_trading_calendar(...)` to build ONE CHECKPOINT PER "TRADING DAY" via
`build_daily_checkpoints` — and `run_paper_trading_cycle.py` (the actual,
cron-scheduled DAILY PRODUCTION paper-trading job, ADR-0075), `run_
multi_strategy_paper_trading_cycle.py`, `run_first_real_strategy_
evaluation.py`, and `run_long_horizon_validation.py` (the script behind
every multi-year walk-forward result in `STRATEGY-VALIDATION-REPORT.md`)
all registered `US_EQUITY` for exactly this purpose. A real run spanning
any year besides 2024 would generate a checkpoint on every real US market
holiday it doesn't happen to already know about. Fixed with a new,
rule-derived `US_EQUITY_NYSE` calendar (New Year's/MLK/Presidents/Good
Friday/Memorial/Juneteenth [2022+]/Independence/Labor/Thanksgiving/
Christmas, each computed from its own published observance rule —
including a standard Gregorian Easter calculation for Good Friday —
spanning 2000-2035, not a hand-recalled date list), spot-checked against
several real years' known holidays, and wired into all four real
scripts in place of `US_EQUITY`. Explicitly documented residual gap:
ad-hoc NYSE closures with no fixed rule (9/11/2001, Hurricane Sandy
2012, a national day of mourning) cannot be derived this way and are
not claimed to be covered.

**Partial — `ai_gateway.gateway`'s 429 handling has no default recovery window when a provider never supplies `retry_after_seconds`.**
Re-verified: the behavior is real and intentional (`ProviderRateLimitError`'s
own docstring already extensively documents it: "Never fabricated by
this codebase itself... absent, the conservative pre-existing behavior
... is unchanged"). The report's own second option — document the
adapter contract on `ProviderAdapter` itself, not only on the
exception class — was the gap: `AIProviderAdapter`'s Protocol
definition had no docstring at all. Added one stating the expectation
explicitly (a real adapter MUST populate `retry_after_seconds`
whenever the provider's response supplies one). Opening a default
retry window without a real signal was rejected — it would itself
violate the "never fabricate a value" discipline the existing code
already follows.

**M-9 — `run_paper_trading_cycle.py`'s `--initial-capital` default, re-verified: NOT a bug.**
The report's own claim conflates two distinct capital conventions:
`PAPER_CAPITAL_USD` ($10,000) is `us_longterm_config.py`'s own,
explicitly Phase-22/`buy_and_hold`-scoped reference figure. `run_paper_
trading_cycle.py` only ever runs the unrelated `baseline_rule`
(`run_cycle`) strategy — the SAME strategy kind ADR-0115's own fix
correctly left at `PaperTradingConfig`'s generic default for the
multi-strategy runner, specifically because `PAPER_CAPITAL_USD` does
not apply to it. No ratified capital figure exists for this script's
own strategy. Forcing `PAPER_CAPITAL_USD` here would be an unjustified
capital change to the real, ongoing production paper-trading job with
no basis in any ratified decision — left unchanged.

### LOW code-pattern residuals (report §2-2)

**`get_as_of` tie-break non-determinism** — `decision.repository`/
`predict.repository`/`risk.repository` (both `PositionSizingResult`
and `RiskCheckedPosition`) and their `storage.*_repository` DuckDB
counterparts all resolved a genuine `as_of_time` tie via `max(...,
key=as_of_time)`/a bare `ORDER BY as_of_time DESC LIMIT 1` — a
meaningless, implementation-dependent choice on a real tie (two
records legitimately sharing the same timestamp), and not guaranteed
to agree between the InMemory and DuckDB implementations of the same
Protocol. Fixed all 8 call sites with a secondary tie-break on the
record's own monotonically-increasing id (`decision_id`/
`prediction_id`/`sizing_id`/`risk_id`), consistently applied across
both implementations of each of the three repository types.

**`tiingo.py`'s `_headers_with_token`** — confirmed genuinely dead (never
called anywhere; Tiingo authenticates via query parameter, not a
header). Removed; its explanatory comment moved to `_auth_params`,
which is the method that actually needs it.

**`decision.agent`'s `risk_state` parameter** — re-verified NOT a bug:
`docs/specifications/PHASE-7-decision-agent.md` already explicitly
labels it "currently-unused `risk_state: dict`" — a disclosed, reserved-
for-future-phase parameter, not hidden dead code. No change.

**`backtest.validation.ValidationSplitter`'s "ADR-0008 reuse claim unfulfilled"** —
re-verified NOT a bug: the Protocol's own docstring already correctly
frames it as prospective ("the shape any FUTURE splitter... must
satisfy"), never claiming a Purged K-Fold/Embargo splitter already
exists. Building one is a real feature, not a code-quality fix: out of
scope here.

**`storage.schema.py`'s 2 unused sequences / `risk.engine.py:230`'s `current_price`** —
re-verified already addressed by ADR-0116 (explanatory comments
present in both places); no further action needed.

**3 momentum/ensemble strategies' `bars[-1].close` used without an explicit `None` check** —
re-verified NOT a bug: `PriceBar.close: float` is non-Optional by its
own dataclass type (never `Optional[float]`), and nothing in this
codebase constructs a `PriceBar` with `close=None`. The report's own
comparison to `factor_strategy.py`'s supposedly more defensive style
does not hold either — that module has no `None`-check for `close`
present. No change.

**`trade_journal.analysis.compute_execution_error`'s `reference_price == 0` case returned a fabricated `0.0`.**
Confirmed real: a 0 reference price makes the ratio genuinely
undefined, not "no execution error" — contradicting the module's own
stated "never estimate a value and present it as fact" discipline.
Fixed to return `Optional[float]`/`None` instead; no production caller
exists yet (only this repository's own tests call it), so the
type-signature change is low-risk.

**`storage.parquet_layer.write_batch`'s docstring claimed an empty batch is a no-op; the code writes a real empty Parquet file.**
Confirmed real mismatch, confirmed currently unreachable in production
(both real callers, `storage.data_repository.append_bars`/`append_raw_
payloads`, already guard against calling this with empty rows
themselves). Fixed the docstring to describe the actual behavior
honestly rather than changing behavior (which would require an
`Optional[Path]` return-type change for no real caller's benefit) —
a new characterization test pins the corrected, honest description.

**`pyproject.toml`'s stale `description`** ("Phase 4: Baseline Models...")
replaced with a pointer to `docs/PROJECT_STATUS.md`, matching the same
"point, don't duplicate a number that will go stale again" pattern
ADR-0115's D-4 fix already established for `README.md`/`PROJECT_STATUS.
md`'s own Phase-count sections.

### Test gap: `test_portfolio.py`'s realized-PnL cases never exercised the H-2 fix

Confirmed real: every existing `TestPnl` case set `spread_cost=
slippage_cost=0` on both legs, so `- fill.commission` (the ADR-0114
fix) and the old, buggy `- fill.total_cost` produce numerically
IDENTICAL results there — the tests would pass identically whether the
fix was in place or reverted. Added a case using `_fill`'s own real
default nonzero `spread_cost`/`slippage_cost`, where the two formulas
diverge (199.0 vs 198.0) — verified via a temporary revert of the H-2
formula that this new case fails without the fix and passes with it.

## What this does NOT do

Does not build a Purged K-Fold/Embargo `ValidationSplitter`
implementation (`backtest.validation`'s own residual item above) — a
real feature, not a bug fix, left for whenever that validation
methodology is actually prioritized. Does not add a default AI Gateway
retry window for a 429 without a real `retry_after_seconds` signal —
would itself violate this project's "never fabricate a value"
discipline. Does not sweep the review's own broader, less-precisely-
scoped claims that re-verification found to not actually hold (M-4's
literal causal claim, M-9, the 3 momentum strategies' `None`-guard
claim, `risk_state`) — each is recorded above with the reasoning for
why no code change was made, not silently dropped.

## Tests

New or extended: `tests/broker/test_broker_pipeline.py` (new file),
`tests/broker/paper/test_us_longterm_runner.py`,
`tests/ml/test_linear_model.py`,
`tests/strategy_research/test_result_analysis.py`,
`tests/risk/test_sizing.py`,
`tests/broker/test_broker_mock.py`,
`tests/broker/live/test_production_safety_cross_cutting.py`,
`tests/broker/paper/test_paper_adapter.py`,
`tests/data/test_calendar.py`,
`tests/decision/test_decision_repository_inmemory.py` (new file),
`tests/predict/test_predict_repository.py` (new file),
`tests/risk/test_risk_repository_inmemory.py` (new file),
`tests/storage/test_decision_repository.py`,
`tests/storage/test_prediction_repository.py`,
`tests/storage/test_risk_repository.py`,
`tests/trade_journal/test_analysis.py`,
`tests/storage/test_parquet_layer.py` (new file),
`tests/backtest/test_portfolio.py`.
Full suite re-run: see `PROJECT_STATUS.md`'s own session entry for the
exact before/after count.
