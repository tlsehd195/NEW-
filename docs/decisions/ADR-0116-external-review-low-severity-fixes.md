# ADR-0116: second independent review — LOW-severity findings pass

**Status:** Accepted
**Session:** 37 (continued)

## Context

ADR-0115 fixed every MEDIUM-severity finding from the second,
independent 16-agent/727-file review (`main` @ `145ea95`). The account
owner asked to continue on through the review's LOW-severity findings
as a follow-up once MEDIUM was done ("미디움 끝나고 로우까지 처라").
This ADR records that pass.

**Scope note, stated plainly**: the review document available to this
session states "LOW ~90건 ... 모듈별 표는 §4·§5" (approximately 90 LOW
findings, tables in its own §4 and §5) but is itself only a 206-line
summary report; several of its own findings (§4.3, §5, §6, §7)
reference a separate, more detailed "worklog" this session does not
have access to. Every LOW finding actually enumerated in the summary
report this session CAN read -- the 6 documentation findings (D-7
through D-12, §6) and the concrete test-quality findings named in §5.1
(bug-pinning tests) and §5.3 (vacuous/no-op tests) -- was independently
re-verified against the real code and processed below. The broader
"~90" aggregate figure cannot be exhaustively accounted for from this
summary alone, and this ADR does not claim to.

**Method, unchanged from every prior review-remediation ADR in this
project**: every finding was independently re-verified against the
real source before any fix was made. One finding (§5.2 item 4, BUY-
path `market_value` weighting coverage) was investigated and found NOT
to need a new test -- `_compute_risk_state`'s `position_weights`
computation reads only `portfolio_state.positions`, entirely
independent of the sizing/decision action, so a BUY-specific test
would exercise the identical code path the existing HOLD-based test
already covers; adding one would be redundant, not a real coverage
gap. Every other finding below carries a genuine code or documentation
fix, and every code fix carries a regression test verified via `git
stash` to fail without the fix and pass with it.

## Decision

### Code fixes

**A real functional bug found while verifying D-10's third sub-item — `compute_incremental_ingestion_start.py` computed a catalog-wide max, not a per-symbol one.**
ADR-0085's own script computed `MAX(timestamp)` across every bar in
the catalog with no per-symbol grouping, then used that single date to
derive the next `--start` for every requested symbol. A symbol left
with ZERO bars by a prior partial-failure run (the exact rate-limit-
exhaustion scenario that motivated ADR-0085 in the first place)
contributed no rows to that query and therefore never widened the
computed start date backward -- the result stayed recent, dominated by
whichever symbols already had plenty of history, and the empty
symbol's true multi-year gap would never actually be re-requested by
any later run. This directly contradicted ADR-0085's own "What this
does NOT do" claim that the next run's incremental window "naturally"
catches a partial-failure tail. Fixed: `_min_known_bar_date` now
groups by `security_id`, restricted to the symbols the run actually
requests (via new `--universe`/`--symbols` CLI arguments mirroring
`ingest_real_market_data.py`'s own), and returns the MINIMUM across
them -- a symbol absent from the catalog entirely correctly forces the
full fallback range, same as an empty catalog. The workflow now passes
`--universe "$UNIVERSE"` to this script too. One of the five existing
tests, `test_takes_the_global_max_across_every_security_not_per_
security`, had itself been pinning the old (wrong) behavior as
intended design -- rewritten to prove the fix instead, alongside three
new tests for the corrected per-symbol/minimum/not-requested-symbol
behavior.

**A real restart-safety gap found while verifying §5.1's `test_experiment_repository.py` bug-pinning entry.**
`backtest.experiment.ExperimentTracker` allocates monotonic
`BT-000001`-style ids starting fresh at 1 on every construction. A
test explicitly documented, as "by design," that two independent
`BacktestEngine` runs recorded into the same
`storage.experiment_repository.DuckDBExperimentRepository` silently
collide and the second, genuinely different experiment's real results
are discarded -- the same restart-safety id-collision class ADR-0115
already fixed for `ai_gateway.QuotaManager`/`broker.paper` observation
ids/`evolution.ModelStatusTransition`/`storage.data_repository` batch
ids, left unaddressed here. No production caller currently chains
`BacktestEngine` output into `DuckDBExperimentRepository` across
multiple runs, so this was latent, not exploited -- matching this
project's own precedent for this exact situation (N-11's optional,
backward-compatible parameter). Fixed: `ExperimentTracker.__init__`
now accepts an optional `starting_id: int = 1`, letting a future
caller that does chain runs together seed each fresh tracker past
whatever the shared repository already holds. The pinned test was
rewritten to document the collision honestly (still real, still
latent, not "by design") and a new test proves the seeding path avoids
it.

### Test-quality fixes (§5.3 — vacuous/no-op assertions)

**`tests/predict/test_regime_aware_predictor.py::test_extreme_volatility_dampens_expected_return_relative_to_plain_drift`.**
The test's whole assertion body was gated behind `if volatility_state
== "EXTREME" and ...`, and under its fixed seed the fixture's
volatility state actually came out `NORMAL` -- the guarded assertions
never ran, and the test passed regardless of whether damping worked at
all. `compute_volatility` ranks the CURRENT 20-day realized volatility
against its own trailing 100-reading percentile history, so a
uniformly noisy series (the old fixture) never ranks itself extreme
relative to its own past; reaching `EXTREME` needs an actual
volatility regime shift. Fixed with a deterministic fixture (calm
history, then a sharp recent spike) verified to actually reach
`EXTREME`, with the assertions now unconditional.

**`tests/monitoring/test_monitoring_boundary.py::test_no_drift_function_returns_anything_but_a_driftresult`.**
Compared `return_annotation.__name__` after checking `hasattr(...,
"__name__")` -- but `monitoring/drift.py` has `from __future__ import
annotations`, so `inspect.signature(...).return_annotation` is the
plain string `"DriftResult"`, not the class, and a `str` has no
`__name__` attribute. `hasattr` was therefore always `False`, the
assert always took its vacuous `else True` branch, and the check never
ran regardless of what any function actually returned. Fixed using
`typing.get_type_hints`, which correctly resolves the stringified
annotation back to the real class.

### Documentation fixes (D-7 through D-12)

**D-7 — `docs/PROJECT_STATUS.md`'s own mega-line coverage-boundary claim was wrong, and its "Updated By" line read as a whole-document staleness claim.**
`docs/decisions/ADR-0112` (and `PROJECT_STATUS.md`'s own copy of the
same claim) stated line 8's historical mega-line covers "through
ADR-0085," with unstructured paragraphs after it covering "ADR-0087
through ADR-0111." A direct scan of line 8's own content shows ADR
numbers up to 0096, and the unstructured paragraphs after it start at
ADR-0097 -- both off by roughly 11. Corrected in both documents. Also
relabeled `PROJECT_STATUS.md`'s "**Updated By:**" field (which
documents who last appended to line 8 specifically, not the whole
document) to say so explicitly, since its own "(Session 36)" value sat
confusingly next to a "Last Updated" line already several sessions
newer, reading as a contradiction.

**D-8 — `docs/decisions/ADR-0113` cited "ADR-0086" for its own, deleted duplicate document, colliding with a different, unrelated, still-live ADR-0086 (insider trading).**
A reader following the citation before reaching the ADR's own later
clarification would land on the wrong document. Added an explicit
disambiguation at the citation's first mention and at its second,
un-clarified mention later in the same file.

**D-9 — 30 early ADRs (ADR-0016 through ADR-0045) had no `**Status:**` field at all.**
Every later ADR in this project carries one; these 30 had silently
never gotten one. All marked `**Status:** Accepted` (every one of
these decisions is long since implemented and in production use). New
regression test (`tests/docs/test_adr_metadata.py`) guards against the
same class of drift going forward -- every ADR file must declare a
status.

**D-10 — three separate stale/contradictory citations, previously flagged and left unaddressed:**
- `docs/decisions/ADR-0006` cited `tests/backtest/test_orders_fills.py`,
  which no longer exists -- `OrderSimulator`/`FillSimulator`/
  `BacktestBroker` coverage has since been distributed across several
  other test files rather than living in one place. Citation corrected
  to name the actual current test file plus a note on where the rest
  of the coverage now lives.
- `docs/decisions/ADR-0053` explicitly rejected building PEAD/SUE
  ("Not built" -- current research found it ineffective for large-cap
  stocks). `docs/decisions/ADR-0084` built it anyway on the account
  owner's own later, explicit instruction, without referencing
  ADR-0053's rejection at all -- a silent contradiction for a future
  reader. Both ADRs now cross-reference each other, recording that
  this was an account-owner override, not a re-evaluation that found
  the original rejection wrong.
- `docs/decisions/ADR-0085`'s own "What this does NOT do" claim about
  natural per-symbol catch-up was corrected to describe the actual
  fix above (this ADR), rather than the original, incorrect claim.

**D-11 — `docs/operations/ORACLE-CLOUD-DEPLOYMENT.md` repeated the "PAT never written to disk" claim ADR-0115 already fixed in code, and carried no SUPERSEDED banner despite ADR-0082 replacing this entire deployment path with GitHub Actions.**
Added a SUPERSEDED banner at the top (ADR-0082 replaced the VM-based
scheduler with GitHub Actions; this guide is reference-only, not the
active path) and corrected the PAT claim to describe the actual
`git -c http.extraheader=...` mechanism ADR-0115 implemented, rather
than the URL-embedding approach that used to make the claim false.

**D-12 — four separate expired/misquoted statements:**
- `docs/specifications/PHASE-17-production-safety-review.md` cited
  `docs/decisions/ADR-0022` "decision 8" as the design rationale for
  "no automatic order cancellation on shutdown" (twice) -- ADR-0022's
  actual decision 8 is about a submission exception mapping to
  `UNKNOWN`, unrelated; `docs/decisions/ADR-0045` had already found
  and corrected this exact misattribution elsewhere, and resolved the
  underlying question (automatic cancellation now happens on kill-
  switch engagement specifically), but PHASE-17's own two citations
  were never updated to match. Both corrected.
- `docs/research/walk-forward-pbo-deflated-sharpe.md` stated "PBO
  itself, the CSCV resampling procedure, is not implemented anywhere
  in this codebase today" -- it has been, since `docs/decisions/
  ADR-0035`, in `src/strategy_research/pbo_dsr.py`. Corrected with a
  pointer to the real implementation and its real usage.
- `docs/operations/MARKET-DATA-PROVIDER.md` stated `RESEARCH_UNIVERSE`
  Stage 2 "remains ... not populated" -- it was populated in Session
  36 (`docs/decisions/ADR-0036`) and the universe has since expanded
  further to Stage 4 (`ADR-0044`). Corrected with an explicit "UPDATE"
  note rather than silently rewriting the original (now historical)
  reasoning.
- `docs/specifications/PHASE-1-data-infrastructure.md`/`PHASE-2-
  backtesting.md`/`PHASE-3-trade-journal.md` all still read "**Status:**
  ACTIVE (design confirmed, reference implementation in progress)"
  while every later phase spec (4 through 9) reads "... implementation
  complete" -- Phases 1-3 are long finished. All three corrected to
  match.

## What this does NOT do

Does not exhaustively process the review's full "~90 LOW" aggregate
estimate -- only what this session's copy of the review document
actually enumerates (see Context's Scope note). Does not sweep the
remaining, individually-ambiguous dangling `§N` PROJECT_MASTER_PLAN.md
references scattered across other early ADRs beyond the ADR-0008 fix
ADR-0115 already made (explicitly deferred there, unchanged here).
Does not add BUY-path market_value weighting test coverage (§5.2 item
4) -- investigated and found not to exercise a different code path
than the existing HOLD-based test, so it would be redundant, not a
real gap. Does not retroactively re-verify D-9's now-added `**Status:**
Accepted` value against each ADR's actual real-world implementation
state beyond "clearly long since implemented and in production use" --
no ADR in this range was found to be anything other than Accepted.

## Tests

`tests/deploy/test_compute_incremental_ingestion_start.py` (rewritten
bug-pinning test + 3 new), `tests/storage/test_experiment_repository.py`
(rewritten bug-pinning test + 1 new), `tests/predict/
test_regime_aware_predictor.py` (fixed vacuous assertion),
`tests/monitoring/test_monitoring_boundary.py` (fixed vacuous
assertion), `tests/docs/test_adr_metadata.py` (new file, guards D-9's
class of regression). Full suite re-run: **2868 passed, 0 failed** (up
from ADR-0115's own 2862, +6).
