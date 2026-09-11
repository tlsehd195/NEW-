# ADR-0119: Complete the Deferred D-6 Dangling `§N` Reference Sweep Across Early ADRs

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session), pending project owner review
**Related documents:** `docs/decisions/ADR-0115-external-review-medium-severity-fixes.md`
(D-6), `PROJECT_MASTER_PLAN.md`

---

## Context

ADR-0115's D-6 fix corrected `PROJECT_MASTER_PLAN.md`'s own 12 dangling
`§N` self-references (and one companion reference in `ADR-0008`), but
explicitly deferred a broader scope: "많은 초기 ADR들" (many early ADRs)
were known to carry their own dangling citations to
`PROJECT_MASTER_PLAN.md` section numbers that do not exist in that
document's real structure (which, per D-6's own verification, tops out
at `§26` with specific `N.M` subsections only where the document
actually defines them). That sweep was "knowingly deferred rather than
guessed at under time pressure," since each reference requires the same
content-matching verification D-6 used, not a mechanical renumbering.

After the fourth verification round (ADR-0118) confirmed no further
externally-reported code issues remained, the project owner selected
this deferred documentation cleanup as the next task.

## Decision

Completed the sweep across every early ADR still carrying a dangling
`PROJECT_MASTER_PLAN.md` `§N` citation: `ADR-0002` through `ADR-0009`
and `ADR-0011` (verified via a full `docs/decisions/*.md` scan for any
`§N` with `N >= 27`, the master plan's real upper bound, plus manual
review of in-range-but-topically-wrong citations). Each fix follows
D-6's own methodology: read the citing sentence's actual claim, search
`PROJECT_MASTER_PLAN.md`'s real text for a genuine match, and only
assign a section number once that match is confirmed — never guessed
from proximity alone.

Corrections applied (old → new; `≈` marks a same-topic
chapter-level citation rather than an exact-quote match):

- **ADR-0002**: `§2.5, §18` → `§7, §18`; `§49` → `§1.2`; `§84` → `§1.3`;
  `§21, §85` → `§21, §20`; `§53` → `§1.3`.
- **ADR-0003**: `§15/§19/§28` → `§7.1/§7.5` (dropped `§28` — "Security
  Master" does not exist in the master plan; attributed instead to the
  Phase 1 initialization instruction); `§18` → `§7.4` (x2); `§84` →
  `§1.3` (x2); `§17.3 / §73` → `§17.3`; `§49` → `§1.2`.
- **ADR-0004**: `§16, §29` → `§7.2` (dropped "Look-ahead Guard" — no
  match anywhere in the master plan); `§53, §92` → `§1.1`; `§1.1, §16`
  → `§1.1, §7.3`; `§90` → `§1.4`.
- **ADR-0005**: `§21-22, §40-41` → `§21, §6.2 ≈, §1.4`; three further
  `§22` occurrences → `§6.2 ≈` (the master plan's provider-redundancy
  content is AI/LLM-provider-specific, `§6.2`; applying it to market
  data providers is a deliberate analogy, marked as such in the ADR
  text itself rather than presented as a literal match); `§41` → `§1.4`;
  `§40` → `§1.3`; `§84` → `§1.3`.
- **ADR-0006**: dropped dangling `§45` from `§9.3-9.4, §45` (the
  `§9.3-9.4` half was already a genuine match — §9.3/§9.4 describe the
  exact Broker-Interface-is-swappable-across-environments property this
  ADR cites); `§84` → `§1.3`; `§28` → `§9.3` (the "don't guess Toss
  endpoints" quote is verbatim in `§9.3`, not `§28`).
- **ADR-0007**: `§46` → `§13.2` (x3, the real Transaction Cost section);
  `§71` → `§17.1` (x1, where Almgren & Chriss is actually cited in the
  master plan's research-foundation table).
- **ADR-0008**: one remaining `§71` → `§17.1` (Purged K-Fold/Embargo's
  citation of López de Prado's work lives in the same research-
  foundation table as Almgren & Chriss, not at `§71`).
- **ADR-0009**: `§92` → `§24` (the exact "Trade Journal은 로그가 아니다.
  경험 메모리다" quote lives in `§24`, not `§92`); three `§11` citations
  about Raw-layer/Journal immutability → `§7 ≈` (the master plan has no
  section literally named "immutability"; `§7`, the general Data Layer
  section, is this project's own established citation point for the
  Raw-layer append-only pattern, per ADR-0002's precedent); `§30-36` in
  the Related-documents header dropped in favor of the two sections
  actually used in the body (`§7`, `§24`).
- **ADR-0011**: `§85-86` → `§13.6` (the real Baseline-first section);
  `§73` → `§1.2` (the real "complexity added only when needed"
  section).

No behavior, test, or non-documentation content changed. This is a
pure prose/citation fix, matching D-6's own precedent of requiring no
regression tests for a zero-code-impact documentation correction.

## Verification

A repository-wide scan (`grep -nE "§(2[7-9]|[3-9][0-9])(\.[0-9]+)?"
docs/decisions/*.md`) after all fixes above confirms zero remaining
out-of-range `§N` references anywhere in `docs/decisions/`, aside from
two historical mentions that explicitly document *already-completed*
prior corrections (ADR-0008's own "renumbered from the original
§48-49/§71" note, and ADR-0115's own D-6 narrative quoting the original
dangling numbers it fixed) — neither is a live dangling citation.

## Consequences

### Positive

- Every early ADR's citation of `PROJECT_MASTER_PLAN.md` now resolves
  to a real, content-verified section, closing out D-6's deferred scope
  completely.
- The "by analogy" (`≈`) markers introduced in `ADR-0005` and `ADR-0009`
  make explicit, rather than silently implying, the few places where an
  ADR's citation is topically adjacent rather than a literal quote —
  consistent with this project's fail-closed documentation discipline
  (never presenting an approximate match as an exact one).

### Negative / Trade-offs

- None — this is a zero-behavior-impact documentation correction.

## Status of Implementation at Time of This ADR

All `§N` corrections applied directly to `docs/decisions/ADR-0002`
through `ADR-0009` and `ADR-0011`. No source code, test, or
`PROJECT_MASTER_PLAN.md` content changed.
