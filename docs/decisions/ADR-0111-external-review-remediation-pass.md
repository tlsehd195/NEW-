# ADR-0111: External code review remediation pass (kill switch, Toss
encoding, AI Gateway quota recovery, position weighting, bar-level
point-in-time availability, evolution candidate id collision)

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner ran this repository's full source through two
independent external AI code reviews and handed both reports to this
session with an explicit instruction: verify every HIGH/CRITICAL
finding against the real code first, without fixing anything, then
resolve every confirmed finding in risk-priority order
("위험도 높은 순으로 순서대로 문제점들 전부 해소").

The verification pass read the actual source for every HIGH/CRITICAL
claim in both reports (cross-referencing where the two reports
disagreed) rather than trusting either report's prose. Of 9 claims
carried into the fix list, 8 were confirmed as real, reachable bugs;
one (a documentation-staleness claim) was already resolved by the time
it was checked. This ADR records the 8 confirmed fixes, each with its
own regression test, in the priority order they were actually fixed.

## Decision

1. **Kill switch self-defense** (`broker/live/session.py`
   `LiveTradingSession.submit`) -- the safety gate was evaluated against
   a caller-supplied `gate_context` only; a session whose OWN kill
   switch had been engaged (`OperationalState.KILL_SWITCHED` /
   `is_kill_switch_engaged()`) but whose caller passed a stale/permissive
   context could still submit an order. `submit()` now always evaluates
   the gate first, then augments `failed_conditions` with
   `"kill_switch_engaged"` (and forces `passed=False`) whenever the
   session's own state says the kill switch is engaged, regardless of
   what the caller's gate context said.

2. **`release_kill_switch` reconciliation loss** (same file) -- releasing
   the kill switch unconditionally returned the session to `READY`, even
   when the release happened while orders were still in
   `BrokerOrderStatus.UNKNOWN` (unreconciled) -- silently discarding the
   requirement that those orders be reconciled before new trading
   resumes. `release_kill_switch()` now checks
   `self._internal_status` for any `UNKNOWN` entries and sets
   `OperationalState.RECONCILIATION_REQUIRED` instead of `READY` when
   any exist.

   **Addendum (ADR-0115)**: this entry, on its own, only covers the
   moment the kill switch is *released* -- it does not by itself
   guarantee that `RECONCILIATION_REQUIRED` actually stays engaged
   until every `UNKNOWN` order clears. A second, independent review
   found that `reconcile_order()` (same file) transitioned
   `RECONCILIATION_REQUIRED -> ACTIVE` on the first single order it
   matched, even while other tracked orders were still `UNKNOWN` --
   silently re-opening trading with unreconciled orders still
   outstanding. ADR-0115 fixed `reconcile_order()` to only clear
   `RECONCILIATION_REQUIRED` once no other tracked `client_order_id`
   remains `UNKNOWN`; only with both fixes together does "orders must
   be reconciled before new trading resumes" hold as an enforced
   invariant rather than a partial one.

3. **Toss OAuth wire-format mismatch** (`broker/toss/transport.py`) --
   every request body was serialized as JSON regardless of the
   declared `Content-Type`, but Toss's OAuth token endpoint requires
   `application/x-www-form-urlencoded`. `post()` now branches on the
   request's own `Content-Type` header and encodes with `urlencode()`
   for form-urlencoded requests, `json.dumps()` otherwise; `get()`'s
   query string is now also built with `urlencode()` instead of raw
   f-string concatenation (same class of bug, same fix).

4. **AI Gateway QuotaManager permanent-lockout cluster**
   (`ai_gateway/quota_manager.py`, `ai_gateway/gateway.py`,
   `ai_gateway/provider.py`) -- four related bugs, one coherent fix:
   - Rollover past `reset_time` was only checked by `is_available()`;
     `record_success`/`record_error` read the pre-rollover state, so a
     provider's `remaining_requests` never actually refilled in the
     persisted history. Fixed with a pure `_effective_state()` that
     computes a transient refilled view (append-only -- the persisted
     history is never mutated in place, matching this repository's
     existing `ProviderQuotaState` discipline), used by all three
     methods.
   - A rate-limited provider had no path back to available -- once
     `mark_quota_exhausted` fired, only a real rollover past
     `reset_time` could clear it, but rate limits are not always on a
     known clock. `ProviderRateLimitError` now optionally carries
     `retry_after_seconds`; `gateway.py` turns that into a real
     `reset_time` when the provider supplies one, changing nothing when
     it doesn't (no fabricated retry window).
   - No way to reverse a `mark_billing_confirmed_free`-style detection
     once billing status changes, and no way to recover from a
     non-time-based failure class (e.g. an auth failure) at all.
     Added `mark_billing_confirmed_free()` and `mark_available_again()`
     -- both explicit, caller-invoked, never automatic/time-based
     (RULE 0.8: no fabricated recovery timer for failure classes this
     repository cannot actually observe clearing).

5. **Risk engine cost-basis-vs-market-value weighting**
   (`risk/engine.py`, `backtest/portfolio.py`,
   `orchestration/paper_runner.py`) -- `_compute_risk_state()` weighted
   every position by `quantity * average_cost` (cost basis), so a
   position's risk weight never moved with the market even as its
   actual portfolio share did. Added an additive, optional
   `PositionView.market_value` field (`None` by default -- cost-basis
   fallback preserved for every existing caller); wired through the one
   real production path that has a live reference price
   (`paper_runner._portfolio_view`). The `backtest.engine` call sites
   that would need the same wiring are explicitly NOT touched by this
   ADR (see What this does NOT do) -- scoped out as separate follow-up
   work, not silently dropped.

6. **Tiingo dividend backdating** (`data_infra/providers/tiingo.py`) --
   a dividend event's `available_time` was set to the dividend's own
   `event_date` (the ex-dividend date itself), which is announced in
   advance of that date, not first knowable on it -- a real look-ahead
   opportunity for any strategy consuming dividend events point-in-time.
   Changed to `ingestion_time` (when this repository actually learned
   about it), matching the existing split-event branch's own precedent
   in the same function.

7. **Tiingo/Stooq/file_import bar-level `available_time`**
   (`data_infra/provider.py`, and the three providers) -- every daily
   bar's `available_time` was set to its own `timestamp` (midnight UTC
   on the bar's date), implying a full day's OHLCV was knowable the
   instant the trading day began -- another look-ahead gap, this one
   affecting every bar from every provider in this repository. The
   naive fix ("use `ingestion_time` instead, like the dividend fix
   above") was considered and rejected: `fetch()` stamps every bar in
   one call with the SAME `_fetched_as_of` timestamp regardless of each
   bar's own date, so applying it bar-by-bar would make a broad
   historical backfill's oldest bars invisible until the batch's END
   date -- a worse regression than the one being fixed. Instead, added
   `data_infra.provider.bar_available_time()` /
   `END_OF_SESSION_OFFSET = timedelta(hours=20)`: a bar becomes
   available at 20:00 UTC on its own date, matching the convention
   `orchestration.paper_runner.build_daily_checkpoints`'s own
   `checkpoint_time=time(20,0)` default already used (Phase 1's mock
   data used the same convention). All three providers
   (`tiingo.py`, `stooq.py`, `file_import.py`) now call this shared
   helper instead of using the bar's own `timestamp`.

   This changed the real availability time of every real-data-fed
   integration test that queried a reference price near midnight UTC.
   Two pre-existing integration tests
   (`tests/integration/test_us_longterm_paper_trading_lineage.py`,
   `tests/integration/test_paper_trading_real_market_data.py`) used
   midnight-UTC `buy_day`/`sell_day` directly as the `as_of`/
   `requested_at` for order submission, fill capture, broker-activity
   monitoring, and performance evaluation -- all of which now needed a
   reference bar that was not yet available at that instant. Both were
   updated to use separate `buy_time`/`sell_time` variables (offset
   +20h) for every call that drives a reference-bar lookup, while
   `buy_day`/`sell_day` themselves are kept unchanged for `PriceBar
   .timestamp` matching and decision/metadata timestamps, which are a
   different field unaffected by this fix. This was a genuine behavior
   change surfaced by a real fix, not a fixture bug independent of it --
   the tests' original midnight convention was simply unrealistic
   against real production callers, which already checkpoint at 20:00
   UTC.

8. **Evolution candidate id collision**
   (`evolution/pipeline.py`, `learning/repository.py`) -- every
   `CandidateTrainer` carries its own process-local `_IdAllocator`
   starting at `"CAND-000001"`, with no way to know what other trainers
   it might run alongside. `evolution.pipeline.generate_candidate_batch`
   exists specifically to combine several trainers' output on one
   dataset (`evolution.trainer.TrailingWindowMeanTrainer`'s own module
   docstring), so every call with more than one trainer reliably
   produced multiple candidates that all claimed the same
   `candidate_id` -- confirmed directly in this repository's own
   existing test fixtures (`tests/evolution/test_evolution_comparison
   .py`'s `_evaluations()` builds exactly this three-trainer batch).
   `storage.learning_repository.DuckDBCandidateModelRepository` already
   resolves this at the persistence boundary by reassigning its own id
   from a DB sequence keyed on natural key, so the durable/production
   path was never actually affected -- but `evolution.comparison
   .compare_candidates` and anything else that reads `candidate_id`
   straight off a batch, before any repository is involved, could not
   tell the resulting candidates apart. Fixed at both points:
   - `generate_candidate_batch` now runs its output through
     `_disambiguate_candidate_ids()`, which appends a numeric suffix
     only to entries that actually collide within that one batch call
     (encounter order), leaving a non-colliding batch's ids untouched.
   - `learning.repository.InMemoryCandidateModelRepository` /
     `InMemoryEvaluationRepository` (the in-memory reference
     repositories -- not used by any production path today, but
     available for direct use) now also reassign their own id at
     record time from an internal counter, exactly mirroring
     `DuckDBCandidateModelRepository`/`DuckDBEvaluationRepository`,
     instead of trusting the caller-supplied id and silently
     overwriting one candidate/evaluation with another under a
     colliding key.

## Tests

- `tests/broker/live/test_live_session.py` -- new
  `test_stale_gate_context_cannot_bypass_the_sessions_own_kill_switch_state`;
  new class `TestReleaseKillSwitchPreservesReconciliationRequirement`
  (3 tests).
- `tests/broker/toss/test_toss_transport.py` -- new
  `TestWireEncodingMatchesDeclaredContentType` (3 tests).
  `tests/broker/toss/test_toss_auth.py` -- 1 new test.
- `tests/ai_gateway/test_ai_gateway_quota_manager.py` -- 2 new rollover
  tests plus new classes `TestBillingConfirmedFreeRecovery`,
  `TestMarkAvailableAgainRecovery`.
  `tests/ai_gateway/test_ai_gateway_gateway.py` -- new
  `TestRateLimitRetryAfterSecondsWiring` (2 tests).
- `tests/risk/test_engine.py` -- new
  `TestPositionWeightUsesMarketValueNotCostBasis` (2 tests).
  `tests/orchestration/test_paper_runner.py` -- 1 new test.
- `tests/data_infra/test_tiingo_provider.py` -- 2 new dividend/split
  tests plus an `available_time` assertion added to the existing
  normalize test.
  `tests/data_infra/test_stooq_provider.py`,
  `tests/data_infra/test_file_import_provider.py` -- matching
  `available_time` assertions added.
- `tests/evolution/test_evolution_trainer.py` -- 2 new tests
  (`test_candidate_ids_are_unique_even_though_every_trainer_starts_its_own_counter_at_one`,
  `test_a_batch_with_no_collision_keeps_every_trainer_own_id_unchanged`).
  `tests/learning/test_repository.py` (new file) -- 4 tests covering
  both in-memory repositories' id-collision and idempotency behavior.

Full suite re-run after every fix; no regressions outside the two
integration test files described in item 7, both of which were
themselves updated (not weakened) to match the corrected availability
semantics.

## What this does NOT do

Does not wire `PositionView.market_value` through `backtest.engine`'s
own call sites -- `backtest`'s portfolio snapshots have no live
reference price the way paper trading's `_reference_price` does, and
doing this correctly would need its own review of at least 4 call
sites; left as a documented gap (item 5), not silently dropped. Does
not build an automatic, time-based recovery path for AI Gateway failure
classes this repository cannot actually observe clearing (billing
status, auth failures) -- `mark_billing_confirmed_free`/
`mark_available_again` are deliberately manual, matching RULE 0.8's
no-fabrication discipline. Does not touch the one review finding that
verification found already resolved (documentation staleness) or any
MEDIUM/LOW-severity finding from either report -- only the 8 confirmed
HIGH items were in scope for this pass.
