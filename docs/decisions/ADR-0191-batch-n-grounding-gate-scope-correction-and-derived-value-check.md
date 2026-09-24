# ADR-0191: Batch N -- grounding-gate scope correction + derived-value anchoring check

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
proceed with "그라운딩 게이트 이식" -- porting Vibe-Trading's grounding
gate, `EXTERNAL_REPO_APPLICABILITY_REPORT.md` priority 4, the report's
own single most strongly recommended item and its estimate of the
largest remaining piece of work, 2-4 weeks)

## Context

The report describes Vibe-Trading's grounding gate as "NEW-'s single
structural weakness's exact solution" and estimates a 2-4 week port of
~5,600 lines across `agent/src/agent/grounding/`'s 6 files (`identity`,
`evidence`, `figures`, `policies`, `release`, `ledger`). Before writing
any code, this batch re-cloned Vibe-Trading and read all 6 files
directly (5,838 lines total, confirmed) to scope the actual port rather
than start translating blind.

**What that reading found changes the shape of this work substantially.**
Vibe-Trading is a chat agent: a general-purpose LLM writes a free-form,
often bilingual (Chinese/English) natural-language answer, and numbers
the model wants to assert appear inline in prose ("the stock closed at
38.68 yuan, up 2.3%..."). The gate's hardest problem -- and the bulk of
its code -- is finding and disambiguating those numbers: `figures.py`
(1,080 lines) is a Unicode-aware number-shape parser handling CJK dates,
currency symbols in multiple scripts, magnitude suffixes ("24.6M",
"2.4万"), percentage-point/basis-point marks, look-alike character
normalization (full-width periods, invisible characters), list markers,
and table cells. `identity.py`/`evidence.py` carry Chinese-market
source/currency alias tables (`"eastmoney"`/`"东方财富"`/`"东财"`, CNY/HKD/
JPY character disambiguation) to resolve what a prose mention of "元"
or "腾讯" refers to.

**This project has no free-form prose to parse.** `AIGateway.generate()`
only ever accepts a response when `response_schema` is set and the
content parses as a JSON object carrying exactly those named keys
(`ai_gateway.validation.validate_response_content`) -- confirmed by
reading that module directly. Every numeric value a real provider would
return already arrives labeled by its field name. The entire class of
problem `figures.py`/`identity.py`/`evidence.py` solves -- "which
substring of this paragraph is a number, and what does it mean" -- does
not exist in this project's design, and porting it would add real,
non-trivial complexity (Unicode normalization, CJK-script handling) to
solve a problem this project's own architecture already sidestepped by
using structured JSON output from the start.

**What genuinely does port, independent of language or prose**: the
"derived" role's validation core, in `policies.py` --
`_evaluate_formula` (a safe, non-`eval()` AST arithmetic evaluator) and
`_unanchored_term` (every additive/subtractive term in a claimed
derivation must trace back to a real observed value, so a model cannot
launder a fabricated number into a seemingly-derived one via arithmetic
on it). This logic operates on a plain expression STRING and a plain
list of observed floats -- it has no dependency on prose parsing,
Chinese-market aliases, or any of the rest of the gate.

## Decision

Add `src/ai_gateway/grounding.py`: `evaluate_formula()` and
`validate_derived_value()`, an independent reimplementation of
Vibe-Trading's `policies._evaluate_formula`/`_check_derived` against
this project's own evidence-pool shape (a plain `Sequence[float]` of
observed values -- e.g. from `AsOfDataView`/`PredictionOutput` -- rather
than Vibe-Trading's CSV/tool-quote ingestion pipeline). One disclosed
simplification: the original's "`1 +/- c` used as a multiplicative
discount factor" special case (an idiom specific to Chinese financial
prose, e.g. "0.666 x (1 - 0.03)") is dropped, since there is no prose
here for that idiom to appear in.

**Explicitly NOT ported, and why**:
- `figures.py` (prose number-shape detection) -- solves a problem that
  does not exist given this project's structured-JSON response design.
- `identity.py`/`evidence.py`'s Chinese-market alias tables -- specific
  to Vibe-Trading's multi-source, multi-market, bilingual chat scope;
  this project is US/Korea equities only, via `ai_gateway`'s own
  provider abstraction, not a tool-calling chat agent.
- `release.py` (redaction-and-retry orchestration over prose text
  spans) and `ledger.py` (persistence for that chat system) -- both
  operate on the prose shape this project does not have; a JSON-based
  equivalent (what should happen when a "derived" field fails
  validation -- retry with a correction, or fail the whole response
  closed) is a real design question, addressed below.

**Not wired into `AIGateway`/`decision.agent` in this batch.** Using
`validate_derived_value` for real requires a prompt/schema design
decision this session should not make unilaterally: which decision-
agent fields should be treated as "derived" (as opposed to "observed"
fields checked directly with `matches_evidence`, or free "proposed"
fields), and extending that field's schema entry so the model supplies
an accompanying formula string (e.g. `expected_return_formula:
"past_close * (1 + momentum_pct)"` alongside `expected_return`) -- today
`response_schema` is a flat tuple of field names with no such pairing.
Whether a failed derived-value check should retry-with-correction (as
Vibe-Trading does) or fail the whole response closed (`RequestStatus.
INVALID_RESPONSE`, this project's existing pattern for any other
validation failure) is itself a product decision. This follows the same
"adopt now, wire in later" precedent ADR-0151 set, and this session's
own `RpmAdmissionGate` (Batch K) and `normalized_entropy` (Batch L)
already used.

## Consequences

### Positive
- The report's own highest-priority recommendation is not silently
  dropped for being too large -- its actually-portable, actually-
  valuable core (formula-anchoring) is delivered, tested, and ready to
  wire in once the schema-design question is settled.
- A large amount of complexity (Unicode/CJK prose parsing, market-
  specific alias tables) that the report's own size estimate (2-4 weeks)
  implicitly assumed necessary is identified as inapplicable and
  explicitly not built -- this is disclosed as a finding, not a
  shortcut: the report's estimate was based on the full 5,838-line
  system, not on what a structured-JSON consumer of the same idea
  actually needs.

### Negative / Trade-offs
- This is a real, substantial scope reduction from what "그라운딩 게이트
  이식" (port the grounding gate) may have been expected to mean --
  disclosed here plainly rather than silently shipping something
  smaller than asked without saying so.
- No decision-quality improvement ships in this batch: `validate_
  derived_value` has no caller today, matching the same trade-off
  `RpmAdmissionGate`/`normalized_entropy` already disclosed. The real
  value (catching a numerically fabricated "derived" field before it
  reaches a trading decision) only materializes once the schema-design
  work above is done.
- The "observed" and "proposed" roles' simpler checks (direct tolerance
  matching, range membership) are not built as their own module here --
  `matches_evidence()` already covers "observed" directly; "proposed"
  (a value must be derived OR inside the observed range) is straight-
  forward to add once a real caller needs it, so it is left for that
  point rather than built speculatively now.

## Tests

`tests/ai_gateway/test_ai_gateway_grounding.py`: formula evaluation
(precedence, unary minus, division-by-zero, malformed syntax, a
rejected `**` power operator, a rejected function-call injection
attempt, a deeply-nested-expression stress case), evidence tolerance
matching, and the full derived-value check including the anchoring
logic's central property (an added/subtracted term with no real anchor
is rejected even when another part of the same formula IS real).
Verified as a real regression guard: temporarily forced the anchoring
check to always pass and confirmed the two unanchored-term tests fail,
then restored it.

Full suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete for `evaluate_formula`/`validate_derived_value`.
The prose-parsing majority of the original gate is explicitly scoped
out, not deferred as unfinished -- it does not apply to this project's
architecture. Wiring the derived-value check into a live prompt/schema
is separate, unscheduled follow-up work requiring an account-owner
design decision on which fields are "derived" and how a failed check
should be handled.
