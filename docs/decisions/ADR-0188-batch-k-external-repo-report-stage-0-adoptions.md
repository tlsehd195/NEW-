# ADR-0188: Batch K -- Stage-0 adoptions from EXTERNAL_REPO_APPLICABILITY_REPORT.md

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
act on `EXTERNAL_REPO_APPLICABILITY_REPORT.md`'s applicability judgment
for 4 external repositories -- colibri, DeerFlow 2.0, Vibe-Trading,
LLM Wiki -- explicitly scoped to that report's own "Stage 0, immediate,
~1 week" roadmap group after confirming the larger items (the Vibe-
Trading grounding gate port, alpha101 reimplementation, the KIS
connector, and running colibri's own inference engine) are each either
too large to responsibly land in one batch or physically impossible in
this remote session's hardware/account-verification constraints)

## Context

`EXTERNAL_REPO_APPLICABILITY_REPORT.md` (an independent read-only
analysis of 4 external GitHub repositories against this project's own
constraints) concluded no repository is a wholesale-adoption candidate,
but named a ranked list of specific patterns and small components worth
adopting. Its own "Stage 0" grouping (items 1-4 of its Part 5 roadmap,
estimated ~1 week combined) is scoped small enough to implement and
fully verify in one session; Stage 1's grounding-gate port (2-4 weeks,
~5,600 lines of original logic to adapt) and Stage 2's items (a KIS
paper-trading connector needing real account verification the report's
own text says is unverified, and running colibri's actual inference
engine at 20GB+ disk / 24GB+ RAM this container does not have) are
explicitly deferred -- see "Reviewed, not done in this batch" below.

## Fixed in this batch

1. **NaN/gap contract, enforced at the ML pipeline's two assembly
   chokepoints** (Vibe-Trading's `agent/src/factors/base.py` contract,
   report priority 1). `ml.features.compute_feature_vector` and
   `ml.target.compute_target` previously only checked `value is None`;
   a future or existing score function returning `float("nan")`/`inf`
   instead of `None` on some edge case would have silently reached
   `MLSample.features`/`.target` rather than being excluded like a
   missing value -- the exact "missing bar treated as a constant"
   failure class Vibe-Trading's own CHANGELOG documents finding (and
   fixing) in 84/462 of its own alphas. Both functions now treat
   non-finite exactly like `None`: excluded from the sample, never
   passed through. This complements, rather than duplicates, Batch J's
   `LinearRegressionModel.fit()` guard (ADR-0187 item 2) -- that guard
   is the last-resort fail-loud check inside `fit()` itself; this one
   stops a bad value from ever reaching a sample at all, so a corrupted
   sample is silently excluded from the dataset rather than crashing
   the whole fit.

2. **Documentation citation-drift lint** (LLM Wiki's broken-links/
   stale-entries pattern, report priority 2). New
   `tests/docs/test_documentation_citations_resolve.py`: every
   `ADR-NNNN`/`PHASE-N` citation anywhere in this repository's tracked
   `.md`/`.py`/`.yml` files must resolve to a real file under
   `docs/decisions/`/`docs/specifications/`. Directly targets the
   independent audit's own repeated R8-e finding (24 citation-drift
   instances found by hand across prior audit rounds) -- this makes
   that drift class a test failure instead of a future manual finding.
   Verified as a real regression guard: a temporary fake citation to a
   nonexistent ADR number (9999) and a nonexistent PHASE number (99)
   was staged, confirmed to fail both new tests, then removed before
   this commit.

3. **Every GitHub Action pinned to a commit SHA** (colibri/DeerFlow/
   Vibe-Trading's own shared CI hygiene practice, report priority 3;
   continues ADR-0187/Batch J's third-party-CSV-fetch pin onto this
   project's own CI itself). All 4 actions used across this repo's 13
   workflows (`actions/checkout@v4`, `actions/setup-python@v5`,
   `actions/upload-artifact@v4`, `actions/download-artifact@v4`) were
   floating major-version tags -- each now pinned to the exact commit
   its tag currently resolves to (`checkout` -> v4.4.0, `setup-python`
   -> v5.6.0, `upload-artifact` -> v4.6.2, `download-artifact` ->
   v4.3.0), each with a `# vX.Y.Z` comment so the pin stays readable
   and bumpable without re-resolving the SHA. New
   `tests/deploy/test_workflow_actions_are_sha_pinned.py` (mirrors
   `test_workflow_concurrency_and_timeouts.py`'s existing one-file-for-
   all-workflows pattern) makes this permanent: any future workflow
   step using a floating tag, or a SHA pin with no version comment,
   fails the suite. Verified as a real regression guard by reverting
   the workflow changes and confirming the new pin-format test fails
   first.

4. **`ai_gateway.admission.RpmAdmissionGate`** (DeerFlow's
   `models/request_admission.py` evenly-spaced-FIFO pacing idea, report
   priority 5 -- an independent reimplementation, not a copy of that
   file, since DeerFlow's own version subclasses `langchain_core`'s
   `BaseRateLimiter` and this project's `src/` stays dependency-free).
   `ProviderConfig.rpm_limit`/`tpm_limit` have existed since Phase 12
   but nothing has ever enforced them -- `MockProviderAdapter.
   get_limits()` only reports the configured value back to a caller
   that asks. This is real, previously-dead configuration made
   enforceable: given a `rpm_limit`, admissions are spaced at least
   `60/rpm_limit` seconds apart, and idle time never accumulates burst
   allowance (waiting 100x the minimum interval still admits exactly
   one request, not several back-to-back) -- the same property the
   report's own summary of DeerFlow's design called out as the reason
   to prefer it over a plain token bucket. Deliberately **not wired
   into `AIGateway`/`ProviderSelector` yet**: this phase ships only
   `MockProviderAdapter`, which makes no real network call and so has
   no real provider-side rate limit to protect against yet -- wiring
   this into the routing pipeline is separate follow-up work once a
   real provider adapter exists, following the same "adopt now, wire
   in later" precedent ADR-0151 already set for skfolio/purgedcv/
   exchange_calendars.

## Reviewed, not done in this batch

5. **Vibe-Trading's grounding gate** (report priority 4, "강력 추천").
   Report's own estimate is 2-4 weeks to port ~5,600 lines of original
   logic into a new `AsOfDataView`/`PredictionOutput`-integrated
   validation subsystem with retry-quota budgeting. This is a genuine
   new subsystem, not a small fix -- landing a shallow or rushed port
   under this batch's own "small items, one PR" discipline would risk
   introducing exactly the kind of half-verified new surface this
   project's own audit discipline exists to catch. Left open for a
   dedicated future session that can scope, design, and test it
   properly on its own, not squeezed into a batch of otherwise-small
   items.
6. **LLM Wiki MCP registration** and **colibri's Brio entropy-gate
   pattern documentation** (report priorities 6-7, each estimated
   half a day to 2 days). Both are legitimate near-term follow-ups
   the report itself scoped as small, but registering a project-wide
   MCP tool and writing a new decision-gate design document are each
   their own unit of work distinct from this batch's four concrete
   code/test changes above; left for the next session rather than
   further expanding this one's scope.
7. **KIS paper-trading connector** (report priority 8). The report's
   own text names its one condition explicitly: "TR_ID이 실계정
   미검증으로 작성됨... 모의투자 계정 실증 필수" -- this remote session
   has no real KIS paper-trading account to verify against, and this
   project's own established discipline (`docs/operations/
   TOSS-API-GAP-ANALYSIS.md`'s Tier 1/Tier 2/UNKNOWN classification,
   ADR-0180 item 5's refusal to guess an unconfirmed Toss cancel-status
   shape) is to never guess an unverified external API's behavior.
   Writing the connector code without that verification would violate
   this project's own standard, not merely leave a gap. Not started.
8. **alpha101 factor reimplementations** and **ColibriProviderAdapter**
   (report priorities 9-10). The former is real net-new feature scope
   (10-20 new factors plus tests, not a fix); the latter needs a
   dedicated inference host with >=24GB RAM and >=20GB disk this
   container does not have -- the report's own text states this is
   "물리적으로 [GitHub Actions 호스트 러너에서] 실행 불가." Neither
   started.

## Consequences

### Positive
- Two real, previously-latent gaps are now closed with enforcement,
  not just documentation: a NaN/inf value can no longer silently reach
  an `MLSample`, and `rpm_limit`/`tpm_limit` config that has been dead
  since Phase 12 is now a real, tested, reusable capability.
- Two new permanent lint suites (`test_documentation_citations_resolve.py`,
  `test_workflow_actions_are_sha_pinned.py`) convert two classes of
  drift the independent audit found by hand into automatic test
  failures going forward.
- All four items were independently verifiable within this session
  (implement, write a real regression test, revert, confirm the new
  test fails, restore) -- no speculative code shipped unverified.

### Negative / Trade-offs
- `RpmAdmissionGate` has no current caller -- it is real, tested
  capability with zero production exposure today, matching this
  project's own precedent (ADR-0151's three adopted-but-unwired
  libraries) rather than a novel risk.
- The report's higher-value items (the grounding gate specifically,
  which the report calls this project's single most valuable available
  external pattern for its own largest structural weakness) remain
  undone. This is disclosed, not silently dropped -- item 5 above names
  exactly what is left and why.
- The SHA-pinned actions will need a manual bump (update the pin +
  version comment) whenever a real upgrade is wanted; this is the
  accepted trade-off of pinning at all, identical to the one already
  accepted for the third-party CSV fetch in ADR-0187/Batch J.

## Tests

`tests/ml/test_ml_features.py` (NaN/inf price and fundamentals feature
values rejected), `tests/ml/test_target.py` (NaN/inf forward-return
values rejected), `tests/docs/test_documentation_citations_resolve.py`
(new file), `tests/deploy/test_workflow_actions_are_sha_pinned.py` (new
file), `tests/ai_gateway/test_ai_gateway_admission.py` (new file, 12
tests covering construction validation, unlimited/limited pacing,
boundary spacing, idle-time-does-not-accumulate-burst, and admission-
timestamp monotonicity).

Every fix/addition verified as a real regression guard before this
commit: the ML chokepoint fixes and workflow SHA-pinning were each
temporarily reverted and the new tests confirmed to fail first, then
restored; the documentation-citation lint was verified against a
temporary staged fake citation (removed before commit); the admission
gate's boundary logic was verified by temporarily loosening its `>=`
comparison and confirming the boundary tests fail, then restored.

Full suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete for all four items listed as "Fixed in this
batch." Items 5-8 are explicitly reviewed and deferred, not silently
dropped -- each names what is left and why in "Reviewed, not done in
this batch" above.
