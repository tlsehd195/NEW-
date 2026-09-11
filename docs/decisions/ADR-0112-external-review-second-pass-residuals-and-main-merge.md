# ADR-0112: third-party re-verification residuals (universe count errata, session-record convention, current_price/DST documentation) and main merge

**Status:** Accepted
**Session:** 37

## Context

ADR-0111 (Session 36 continued) fixed 8 confirmed HIGH-severity issues
from an external code review and recorded a full test-suite pass
(2756 passed) at commit `1435afb`. The account owner then had a
**third party independently re-verify** that work by checking out the
branch and running the suite themselves, and relayed the results with
two categories of finding:

1. **All 8 fixes re-confirmed correct** -- no rework needed.
2. **`main` was never merged.** `main` (`d018cf8`) still predates every
   fix; the work exists only on `claude/phase-11-model-evolution-7hpibr`,
   222 commits ahead of `main`.
3. **The prior session's "1 finding already resolved" verdict on a
   documentation-staleness claim was itself inaccurate** -- re-verification
   found 4 residual documentation issues and 2 residual code issues that
   the original pass had not actually resolved.

This ADR records the residual fixes and the merge.

## Decision

### 1. Universe symbol-count errata (`docs/PROJECT_STATUS.md`, `src/data_infra/universe.py`)

Actual counts, confirmed by literal enumeration of each
`UniverseDefinition.symbols` tuple (matching what `tests/data_infra/
test_universe.py::TestPilotUniversePreserved` had already asserted all
along -- the DATA was always correct; only the PROSE describing it was
stale): **PILOT 15 / Stage2 cumulative 39 / Stage3 cumulative 63 /
Stage4 cumulative 87**.

Fixed:
- `docs/PROJECT_STATUS.md`'s Stage 3 section: "24 symbols added
  (40→64)" → "24 symbols added (39→63)"; "existing 40 symbols (PILOT 16
  + Stage2 24)" → "existing 39 symbols (PILOT 15 + Stage2 24)"; "now
  points to 64 symbols" → "now points to 63 symbols".
- Line 8's own mega-line: "real Stage 3 (64 symbols)" → "real Stage 3
  (63 symbols)" -- this single line had contradicted itself, separately
  also saying "실제 63종목 ingestion" and "STAGE3 63종목" a few thousand
  characters later.
- `src/data_infra/universe.py`: `PILOT_UNIVERSE_V1`'s own module
  comment and `description=` field said "original 16-symbol" -- fixed
  to 15. `RESEARCH_UNIVERSE_STAGE2`'s adjacent `description=` field
  (same off-by-one, same root cause, one function away -- not
  separately flagged by the review but fixed alongside since it is the
  same bug, not a different area) said "PILOT_UNIVERSE_V1's 16 symbols
  plus 24" -- fixed to 15.

### 2. Stage 3 selection-rationale arithmetic (`docs/PROJECT_STATUS.md`)

"Real Estate: PLD/AMT/EQIX/SPG, Materials: LIN/APD/ECL/NEM, Utilities:
DUK/SO/D, remaining **14** symbols" summed to 4+4+3+14=25, not the
actual 24 new Stage 3 symbols. Cross-checked against the real
`RESEARCH_UNIVERSE_STAGE3` symbol set (`set(RESEARCH_UNIVERSE_STAGE3.
symbol_ids) - set(RESEARCH_UNIVERSE_STAGE2.symbol_ids)`, 24 symbols):
the three named groups (11 symbols) are correct as listed; the
remainder is 13, not 14. Corrected to "remaining 13 symbols" (4+4+3+13=24).

### 3. ADR-0071 citation check

The re-verification report could not find ADR-0071 cited anywhere in
`docs/PROJECT_STATUS.md` ("case/word-boundary grep, 0 hits"). Checked
independently this session: the file `docs/decisions/
ADR-0071-live-runner-derives-mechanically-certain-gate-fields.md` is
real, and a direct grep of the current `docs/PROJECT_STATUS.md` finds
exactly one hit, inside line 8's own mega-line, in a factually coherent
context ("나머지 6개(risk_health/model_state_valid/
configuration_integrity_valid/max_turnover/approval/
required_capabilities)는 각각 다른 진짜 이유로 여전히 caller
책임(ADR-0071에 개별 사유 기록)"). The re-verification's "0 hits"
finding does not reproduce against the current file; no correction was
needed here beyond re-citing it explicitly in this session's own
`### Completed` record (Decision 4 below) for future discoverability,
since a citation buried inside one 37KB line is easy to miss even when
present.

### 4. Session-record convention

Per the review: work since ADR-0053 through ADR-0096 has no `###
Completed (Session N — ...)` structural record, only line 8's
continuously-appended mega-line; work since ADR-0097 exists as a series
of separate paragraphs (each citing its own ADR number) but still
without structural `###` headers. Per the review's own second option
("문서 상단에 명시 + 향후 규칙 문서화"), rather than retroactively
rewriting ~30 ADRs' worth of history into `### Completed` blocks (real
risk of transcription error for no material benefit -- the content
already exists and is already ADR-numbered), `docs/PROJECT_STATUS.md`'s
`Last Updated` line and this session's own new `### Completed (Session
37 — ...)` section now state explicitly: line 8 is the closed,
historical record through ADR-0096 (corrected in ADR-0115 -- the
original "through ADR-0085" claim here undercounted by measuring only
this ADR's own citation range rather than the mega-line's actual
content, which a direct scan shows cites ADR numbers up to 0096); the
unstructured paragraphs after it cover ADR-0097 through ADR-0111; and
every session from this one
forward uses a structural `### Completed (Session N — topic, ADR-NNNN)`
header, no further appending to line 8.

### 5. `risk/engine.py`'s unused `current_price` parameter

Confirmed by direct search: `PortfolioRiskEngine.assess`'s
`current_price` parameter is never read anywhere in
`DeterministicPortfolioRiskEngine.assess`'s body (the position-weighting
fix ADR-0111 already made reads `PositionView.market_value` off
`portfolio_state` instead). Of the review's two acceptable resolutions,
chose **documentation over removal**: `orchestration.paper_runner`,
`orchestration.live_runner`, and `risk.shadow.evaluate_in_shadow` all
already pass this parameter through today, so removing it is a
four-file signature change whose only benefit is cleanliness, not
correctness -- deferred to a dedicated future session rather than
bundled into a remediation pass, to keep this pass's diff reviewable
and its risk low. Added an explicit "intentionally unused, here is why,
here is what keeps it on the Protocol" comment to `PortfolioRiskEngine.
assess`, `DeterministicPortfolioRiskEngine.assess`, and
`risk.shadow.evaluate_in_shadow`.

### 6. `END_OF_SESSION_OFFSET`'s winter (EST) gap

`END_OF_SESSION_OFFSET = timedelta(hours=20)` matches US equity market
close exactly during EDT (summer) but is 1 hour early during EST
(winter, roughly November-March) -- a narrower reopening of the same
look-ahead class this constant exists to close, not a new one.
Documented, not fixed: `backtest.clock.build_daily_checkpoints`'s own
`checkpoint_time=time(20, 0)` default is the explicit precedent this
constant was chosen to match, and it shares the identical DST blind
spot -- fixing one without the other would make an as-of query and the
checkpoint clock driving it disagree about when a winter session
closed, a worse inconsistency than today's shared 1-hour gap. Left as
a deliberate, now-documented project convention; a real fix would vary
the offset by whether `event_date` falls in EDT or EST and must change
both together, left for a future session that takes on that pair
intentionally.

### 7. `main` merge

Merged `claude/phase-11-model-evolution-7hpibr` (including this
session's own residual fixes, commit range through this ADR) into
`main` via pull request, resolving the "`main` still predates every
fix" finding. See Tests section for the post-merge full-suite result.

## What this does NOT do

Does not touch any of the 8 already-reverified ADR-0111 fixes -- no
file from that pass was re-opened. Does not retroactively rewrite
ADR-0053-0111's history into `### Completed` blocks (Decision 4's own
reasoning). Does not remove `current_price` from any signature (Decision
5) or change `END_OF_SESSION_OFFSET`'s value (Decision 6) -- both
deliberately deferred, not silently dropped. Does not touch
`docs/research/STRATEGY-VALIDATION-REPORT.md`/`STRATEGY-RESEARCH-REPORT.md`'s
own "16-symbol" mentions -- those describe specific historical runs
made against the universe as it existed at that time and are out of
this ADR's explicitly-scoped area (`docs/PROJECT_STATUS.md` and
`src/data_infra/universe.py`'s own docstrings only, per the review's own
instruction section 5: other repository areas are out of scope).

## Tests

`tests/data_infra/test_universe_documentation_numeric_consistency.py`
(11 tests, new): pins the actual `UniverseDefinition.symbols` counts
(15/39/63/87) and the actual Stage3/Stage4 new-symbol-count deltas (24
each) as ground truth; asserts `src/data_infra/universe.py`'s source no
longer contains the stale "16-symbol"/"16 symbols" wording and does
contain the corrected "15-symbol"/"15 symbols" wording; asserts
`docs/PROJECT_STATUS.md` no longer contains the specific stale
substrings the review flagged and does contain the corrected ones,
including the corrected 4+4+3+13=24 Stage 3 breakdown. Full suite
re-run on this branch (`claude/phase-11-model-evolution-7hpibr`, pre-merge):
**2787 passed, 0 failed** (up from ADR-0111's own 2756 -- the net
difference is this ADR's own 11 new tests plus whatever net change
other work already on the branch before this session contributed).
Re-run again on merged `main` HEAD after the PR merge -- see this
session's own `docs/PROJECT_STATUS.md` entry for that final count.
