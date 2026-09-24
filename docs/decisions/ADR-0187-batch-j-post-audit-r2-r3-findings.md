# ADR-0187: Fix the R2/R3 re-audit's new findings (Batch J)

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (uploaded
two further independent audit reports -- a round 2 re-verification at
SHA `13e422c` and a round 3 fresh full rescan at the same SHA -- and
asked to fix all problems found, then merge)

## Context

After Batches A-I closed every P1/P2/P3 item from the original
independent audit report, the account owner uploaded two further
reports: R2 (round 2), which re-verified Batches A-G against real
execution and found 8 of 11 already genuinely fixed, 1 (the delisting
performance gate) coded but unreachable against the project's own real
`SecurityMaster.valid_to` shapes, and 2 documented as deliberate
decisions -- plus 3 new P2s and a handful of stale-documentation items;
and R3 (round 3), a fresh full rescan of areas R1/R2 had not covered in
depth (ml/predict/regime/decision internals, `factor_scores.py` at
field level, 27 previously-unaudited scripts, committed backup JSON,
CI supply chain, test-suite integrity), which found 7 new P2s and 27
grouped P3s while explicitly confirming R2's "Paper 운영 가능" grade
was untouched by any of them.

This ADR covers every item this batch actually fixed. Two accompanying
analysis reports (external-repository applicability for
colibri/DeerFlow/Vibe-Trading/LLM Wiki, and an MCP-tooling-location
report) were also received during this batch's work; both are advisory
("pattern-only adoption," no runtime integration recommended) and are
not code-fix items -- their disposition was communicated directly to
the account owner, not folded into this ADR.

## Fixed in this batch

1. **CI command-injection chain (R3 P2-1)** -- `.github/workflows/
   ingest_stockanalysis_wayback_delisted_prices.yml` fetches a
   third-party CSV whose `ticker` column reaches a shell command
   unquoted (`scripts/select_delisted_candidates_since.py`'s stdout
   into `--symbols`). Fixed at the one place this content is actually
   parsed: `parse_ticker_intervals` (`data_infra.providers.
   sp500_index_constituent_history`) now rejects any ticker not
   matching `^[A-Z]{1,10}(\.[A-Z])?$`, fail-closed. The CSV fetch URL
   is additionally pinned to a specific commit SHA (defense-in-depth --
   the real fix is the charset validation, this just stops the content
   from changing between reviews at all).
2. **NaN target silently "succeeds" an OLS fit (R3 P2-2)** --
   `ml.linear_model.LinearRegressionModel.fit()`'s pivot-finiteness
   guard only inspects the design matrix (`xtx`, built from features),
   never the target vector (`xty`'s right-hand side) -- a NaN target
   poisons only the RHS, sails through, and produces an all-NaN
   "successful" fit instead of raising, asymmetric with the already-
   correct NaN-FEATURE case. Fixed: `fit()` now checks `targets` for
   finiteness before solving, and the final `solution` for finiteness
   after, both raising `ValueError`.
3. **10-K/A restatement mistaken for the prior fiscal year (R3 P2-3)**
   -- `strategy_research.factor_scores._fy_records` had no dedup by
   `period_end` (unlike its own sibling `_quarterly_records`, which
   already does). A real restatement persists as a second real record
   for the same fiscal year; every YoY consumer that indexes
   `records[-1]`/`records[-2]` positionally (`asset_growth_score`,
   `piotroski_f_score`, `sloan_accruals_score`, `shareholder_yield_
   score`, `ohlson_o_score`, `dividend_growth_score`, `net_stock_
   issuance_score`) would silently compare the restatement against the
   ORIGINAL FILING OF THE SAME YEAR instead of a real year-over-year
   change. Fixed: `_fy_records` now dedupes by `period_end` (latest-
   filed wins), exactly mirroring `_quarterly_records`.
4. **`illiquidity_score`'s return/bar pairing shifts after a 0 close
   (R3 P2-4)** -- `backtest.metrics.compute_returns` SKIPS (does not
   None-pad) an index whose prior close is 0, so its own returned list
   shortens and shifts from that point on; `zip(bars[1:], returns)` did
   not know that happened, silently re-pairing every LATER (bar,
   return) with the wrong day's bar after a single 0-close day (a real,
   reachable case -- a `negative_or_zero_price` bar is ERROR severity,
   not gated by default `get_bars()`). Fixed: computed index-aligned
   directly inside `illiquidity_score`, skipping only the one affected
   ratio with no shift to any other day's pairing.
5. **NaN silently persists as a "REAL" short-interest/institutional-
   holding record (R3 P2-5)** -- `x < 0` is silently `False` for a NaN
   `x` (every NaN comparison is `False` in Python), so `Short
   InterestRecord`/`InstitutionalHoldingRecord`'s own negativity-only
   validation let a malformed CSV cell that parses as NaN (or +/-inf)
   straight through, persisting as an ordinary record with the
   manifest reporting success -- the same NaN-comparison trap
   `ml.linear_model`'s own pre-existing pivot guard was already written
   to catch, just never applied to these two models. Fixed: both
   `__post_init__`s now check `math.isfinite` on every float field
   before the existing negativity check.
6. **`fetch_fmp_delisted_prices.py` exits 0 even when every candidate
   fails (R3 P2-6)** -- an invalid API key makes every real candidate
   fail identically to "this ticker has no real FMP data," and the
   script printed a report and returned 0 either way. Fixed: exits 1
   when `covered_report` is empty (not one candidate produced real
   data), mirroring `ingest_fundamentals_data.py`'s own established
   "0 records persisted -> failure" exit-code pattern.
7. **`fetch_sp500_index_history.py` has no zero-row gate (R3 P2-7)** --
   a header-only response (a truncated proxy, an upstream format
   change that keeps the same column names) parses "successfully" as
   zero intervals; this script feeds `UniverseMembership`, the
   documented P1-2 survivorship-mitigation data path, so a silently
   empty membership set would be invisible by exit code -- the same bug
   class P1-1 (ADR-0175) already closed for the real market-data
   ingestion scripts. Fixed: exits 1 when `parse_ticker_intervals`
   returns zero rows.
8. **Blanket 4xx -> REJECTED with false certainty (R1/R2/R3 all
   flagged this; also a process gap -- missing from ADR-0180's own
   "reviewed" list)** -- `broker.toss.mapping.parse_order_response`
   mapped EVERY 4xx code to `REJECTED`, including codes this project
   has no evidence for. Order creation is only Tier 2 evidence
   (`docs/operations/TOSS-API-GAP-ANALYSIS.md`), unlike `CANCEL_ORDER`'s
   fully Tier-1-enumerated conflict codes
   (`_CANCEL_CONFLICT_STATUS_MAP`, already correctly `UNKNOWN`-by-
   default). Fixed the same way: a new `_ORDER_REJECT_CODE_SET`
   (`insufficient-buying-power`, `order-hours-closed`, `price-out-of-
   range` -- exactly PHASE-13's own documented "Example codes" for
   order creation, `expired-token` handled separately via the 401
   path) is the only set that maps to `REJECTED`; any other 4xx code
   -- documented or not -- now maps to `UNKNOWN`, `error_code` always
   preserved for audit. ADR-0180 amended with a correction note
   pointing here.
9. **Two stale documentation items (R2)**: `paper_trading_cycle.yml`'s
   monitoring-sweep comment claimed an empty store produces an honest
   "UNKNOWN-derived report" -- verified directly (real execution
   against an empty store) that the actual behavior is
   `ComponentHealthStatus.UNAVAILABLE`, 5 CRITICAL alerts, and a real
   exit 1 (kept from failing the job only by `continue-on-error:
   true`); comment corrected to state this precisely.
   `orchestration.paper_runner.run_cycle`'s own docstring still
   described the pre-ADR-0177 "ONE snapshot shared unchanged across
   every security" behavior; corrected to describe the real,
   ADR-0177-updated behavior (the local `portfolio` variable is
   updated in memory after each real submission, so later securities
   in the same cycle see that cycle's own already-submitted orders'
   cumulative effect).

## Deliberately not changed

- The delisting performance gate's real-`SecurityMaster.valid_to`-shape
  unreachability (R2 new P2) and the Wayback full-mode timeout data-
  loss design flaw (R2 new P2) are real, but each requires a design
  decision (how to detect "this security's price window legitimately
  ended" vs. "the gate's own `valid_to=None` assumption doesn't match
  reality," and how to persist partial progress across a timeout
  respectively) rather than a narrow fix -- not attempted unilaterally
  in this batch. Flagged for a follow-up.
- R3's 27 grouped P3 items (data-plane fail-open remnants, storage/
  operational robustness, CI supply-chain hygiene beyond the one
  injection vector already fixed, research/validation logic edge
  cases, test/documentation honesty) were triaged by severity and
  reachability; this batch fixed the 7 P2s and the cross-audit-flagged
  P2 (blanket-4xx) as the highest-value, most concretely reachable
  items. The 27 P3 groups remain open, individually much lower value
  per item than the P2s above, and were not exhaustively worked through
  in this pass.
- The two advisory external-repository reports recommend several
  patterns (a NaN/gap contract document, a numeric-grounding gate for
  LLM responses, CI action SHA-pinning project-wide, a documentation
  cross-reference lint) that overlap productively with items already
  fixed here (the NaN fixes above) or already-open P3s (CI pinning) --
  these are adoption decisions for the account owner, not silently
  acted on here beyond what this ADR's own items already cover.

## Consequences

### Positive
- Closes a real, concretely exploitable CI command-injection chain
  (P2-1) before any malicious or accidental upstream change could reach
  it.
- Closes 3 independent NaN-propagation gaps (P2-2, P2-5, and the
  already-existing pivot guard's own established pattern) using the
  exact same `math.isfinite`-before-comparison fix in each case --
  consistent, not three different approaches to the same bug class.
- Closes a real research-evidence-integrity gap (P2-3, P2-4) that R3
  itself named as lowering confidence in this project's own factor
  research, without touching any live trading/fund-safety path.
- The blanket-4xx fix converges three separate audit passes (R1, R2,
  R3) onto one real, now-closed gap, and corrects a real process gap
  (an item that should have been recorded and wasn't).

### Negative / Trade-offs
- Two real R2 findings (delisting gate, Wayback timeout) remain open,
  each needing a real design decision this batch declined to make
  unilaterally.
- 27 P3 groups from R3 remain unaddressed; this batch does not claim
  completeness over the full re-audit, only over its P2-severity (plus
  the cross-audit P2) findings.
- `_ORDER_REJECT_CODE_SET` is exactly 3 codes wide, sourced from a
  Tier 2 "example codes" list, not a fully enumerated Tier 1 spec (this
  endpoint has never had one) -- a real, currently-undocumented reject
  code will now report `UNKNOWN` rather than `REJECTED` until this
  project gets real Tier 1 evidence for it. This is the correct,
  fail-closed direction (matching this project's own "never guess an
  unconfirmed endpoint shape" discipline elsewhere), but it does mean
  `RECONCILIATION_REQUIRED`/manual investigation is now the outcome for
  more 4xx cases than before, not fewer.

## Tests

Every fix has a real, executable regression test verified by reverting
the fix and confirming the new test fails first, then restoring it:
`tests/data_infra/test_sp500_index_constituent_history.py` (ticker
charset rejection + real dotted-share-class acceptance),
`tests/deploy/test_ingest_stockanalysis_wayback_delisted_prices_workflow.py`
(SHA-pin assertion), `tests/ml/test_linear_model.py` (NaN/inf target
rejection), `tests/strategy_research/test_factor_scores.py` (10-K/A
restatement not mistaken for prior year; lone-restated-year-with-no-
prior returns `None`; zero-close-day pairing stays aligned),
`tests/data_infra/test_short_interest_models.py` /
`test_institutional_holding_models.py` (NaN/inf rejection),
`tests/scripts/test_fetch_fmp_delisted_prices.py` (new file --
all-candidates-fail exits 1, one covered candidate exits 0),
`tests/scripts/test_fetch_sp500_index_history.py` (new file --
header-only response exits 1, real rows exit 0),
`tests/broker/toss/test_toss_mapping.py` (undocumented 4xx code and a
4xx with no `code` field both stay `UNKNOWN`; the 3 documented reject
codes still correctly map to `REJECTED`, unchanged).

Full suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete for every item listed as "Fixed in this batch."
This is Batch J, following directly from the originally-planned Batch
A-I pass once two further independent audit reports arrived mid-session
naming new, real findings.
