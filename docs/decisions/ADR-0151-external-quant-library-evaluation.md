# ADR-0151: External Quant Library Evaluation (Kronos, skfolio, NautilusTrader, Vibe-Trading, purgedcv, exchange_calendars)

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), account owner (chose to
recover this content and asked for independent re-verification rather
than a branch merge)
**Provenance note:** This ADR's Decisions 1-7 were originally written on
a separate branch, `claude/ruflo-features-review-hqrvqa`, as its own
`ADR-0032`. This note originally claimed that branch shared NO common
git ancestor with `main` (`git merge-base` returning empty — a
"disjoint history"), contradicting two earlier uploaded evaluation
reports that described it as an ordinary stale branch ("19 commits
behind, diverging at a shared point"), and went on to conclude from
that claim that `main`'s own history had been rewritten at some point.
The account owner chose to have this session read the branch's actual
final content directly and re-author it fresh on top of current `main`
rather than merge it, specifically because of that (as it turns out,
incorrect) disjoint-history claim.

**Correction (2026-09-17, later the same session, per an independently
uploaded third-party verification report):** The disjoint-history claim
above was wrong, and the two earlier reports it contradicted were
right. Root cause, confirmed directly in this session: the working
clone was a *shallow* clone (`git rev-parse --is-shallow-repository`
returned `true`) at the time the original claim was made — a shallow
clone can make `git merge-base` return empty and make a recent commit
look like a history root, exactly the two symptoms that led to the
wrong conclusion. After running `git fetch --unshallow`, re-running the
same checks gives: `git merge-base origin/main
origin/claude/ruflo-features-review-hqrvqa` = `61c9507` ("Phase 28:
document exhaustive real-data search + provenance-check fix",
2026-08-28) — a real, present common ancestor, not empty; `git rev-list
--max-parents=0` returns the SAME root commit (`c3abad0`, "Initial
commit") for both `main` and the ruflo branch, so `main`'s history was
never rewritten; and `git log --oneline
origin/claude/ruflo-features-review-hqrvqa ^origin/main` lists exactly
19 unmerged commits — matching the two earlier reports' description
precisely. `claude/ruflo-features-review-hqrvqa` is therefore an
ordinary stale feature branch, not a disjoint history.

This does NOT change the recovery decision itself: the account owner's
choice to re-author only the four `ADR-0032`/library-adoption commits
fresh on `main` (rather than merge the whole branch, which also carries
unrelated archify/task-observer/skill-tooling commits out of this
ADR's scope) remains sound on its own merits, and the content recovered
below was independently re-verified in this session regardless of the
branch-history question. What changes is only the REASON given at the
time for not doing a normal merge, and the false "main's history was
rewritten" suspicion, which is retracted here and must not be repeated
by a future session. The original 19 unmerged commits (reproducible via
`git log --oneline ruflo-features-review-backup ^origin/main` — pinned
to the backup branch's fixed tip `04e4481`, not the mutable
`claude/ruflo-features-review-hqrvqa` branch, which a sixth independent
verification report found had since moved and returns 20 commits
against this same command; re-confirmed 2026-09-18 per an independent
fourth verification report's own LOW-severity finding that this ADR
asserted "listed above" with no such list actually present anywhere in
this file):

```
04e4481 Adopt exchange_calendars; document almgren-chriss and factor-attribution as unfilled gaps (ADR-0032)
af29e2f Adopt purgedcv; record statsmodels/darts as future predictor candidate (ADR-0032)
a909f0c Strengthen ADR-0032's Kronos evidence with direct upstream verification
b629614 Adopt skfolio for future portfolio optimization; document evaluation of 4 external quant tools
e2ee5ce Remove decision/risk/predict workflow diagram
2298837 Add decision/risk/predict algorithm-level workflow diagram (archify)
f310141 Add full 16-package architecture diagram (archify)
5efa3a4 Translate core-trading-pipeline diagram to Korean
20eefa4 Add core trading pipeline architecture diagram (archify)
b6578b2 Add archify skill for evidence-verified architecture diagrams
29aa3a3 Add src/ module map to CLAUDE.md to cut codebase-orientation tokens
419f2f2 Initialize task-observer workspace and log first observation
e989ed2 Activate task-observer with a pinned workspace and enforced review-state hook
1f995e9 Add CLAUDE.md with tool-usage rules for the installed skills/MCP tools
6d86a77 Auto-reinstall machine-level tools on every session start
7d28b47 Add ponytail skill family for over-engineering discipline
416b96a Add task-observer skill for skill-improvement discovery
461776d Add safety-guardrail and session-context Claude Code hooks
ddcf562 Add curated Claude Code skills for this project's workflow
```

The top 4 (`04e4481`/`af29e2f`/`a909f0c`/`b629614`) are exactly this
ADR's own recovered content, already independently re-verified above.
The remaining 15 are the archify/task-observer/skill-tooling commits
this ADR's own Consequences section already disclosed as out of scope.
All 19 remain on `claude/ruflo-features-review-hqrvqa` and are
additionally preserved under the branch `ruflo-features-review-backup`
(created via the GitHub API pointing at the same tip commit, `04e4481`
— a direct `git push` of a new tag was refused by this session's own
push-scope policy) against accidental branch deletion, per the same
third-party report's recommendation.

The three ADOPTED libraries (skfolio, purgedcv, exchange_calendars)
were independently re-installed and re-verified in THIS session's own
environment rather than trusted from the original ADR's prose. The
REJECTED candidates (Kronos, NautilusTrader, Vibe-Trading,
almgren-chriss) are carried over as reasoning, not independently
re-checked against their current upstream state — rejections are
lower-risk to carry forward than adoptions, and the reasoning for each
does not depend on a moment-in-time fact likely to have flipped.

---

## Context

Four external tools were proposed for adoption into this project: Kronos
(a financial time-series foundation model), skfolio (a portfolio
optimization library), NautilusTrader (a complete algorithmic trading
platform), and Vibe-Trading (an autonomous AI trading agent). Each was
evaluated against this project's actual code (not just its stated
purpose) and against `PROJECT_MASTER_PLAN.md`'s priority order (Capital
Safety > Data Integrity > Reproducibility > Validation > Risk Control >
...).

A follow-up, broader search (beyond the original four) was run against
the same methodology: grep/read this project's own code first to confirm
a gap is real, not assumed, before evaluating any library against it. That
search produced Decision 5 (adopted) and Decision 6 (recorded as a future
candidate, not adopted).

## Decision 1 — Adopt skfolio as an optional dependency

`src/risk/sizing.py` (Phase 8) sizes one security at a time from
`PortfolioView` + `PredictionOutput`; there is no covariance-aware,
multi-asset allocation step anywhere in the codebase, despite the
package docstring calling Phase 8 a "Portfolio Risk Engine." skfolio
(BSD-licensed, built on `scikit-learn`'s fit-predict-transform API,
mean-variance/risk-parity/clustering-based allocators) is a mature,
transparent fit for that specific, verified gap — it is not a black
box, and every allocator it ships is a well-documented, auditable
optimization, consistent with this project's "no code path may claim
results it cannot justify" standard.

Added as an optional dependency group (`portfolio-optimization`) in
`pyproject.toml`, not a core dependency and not yet wired into
`src/risk/`: adopting the library and designing how a multi-asset
allocator plugs into the existing single-security `PositionSizer`
Protocol are two different decisions. The latter needs its own Phase
work (a new `PortfolioAllocator`-shaped Protocol, or an extension of
`PositionSizer`, plus tests) and is out of scope here — this ADR only
clears the library for use once that Phase is scheduled.

**Independently re-verified this session** (not merely re-stated):
`pip install "skfolio>=1.2.1"` succeeds (resolved to 1.2.8), and
`from skfolio.optimization import MeanRisk` /
`from skfolio.moments import EmpiricalCovariance` both import cleanly
with no conflict against the existing `duckdb`/`pyarrow` stack.

## Decision 2 — Do not adopt Kronos yet; the blocking question is pre-training data leakage

Kronos is a decoder-only foundation model pre-trained on 12B+ K-line
records across 45 exchanges (arXiv:2508.02739). It is a plausible future
`Predictor` implementation for `src/predict` (currently only
`RandomWalkPredictor`/`DriftPredictor`/`RegimeAwarePredictor`, all
explicitly documented as "no AI/ML" baselines). It is not adopted now
because of a specific, unresolved risk: if this project ever backtests
Kronos-based predictions over a historical window that overlaps Kronos's
own pre-training corpus, the model has already seen that period's actual
outcomes during training. That is a lookahead-bias channel this
project's own `AsOfDataView` point-in-time guarantees do not and cannot
cover — `AsOfDataView` only prevents a strategy from querying rows
outside `[start, current_time]` in this system's own data store; it has
no visibility into what an externally pre-trained model already
memorized.

Before Kronos can be adopted: (1) obtain Kronos's pre-training data
cutoff date and, ideally, the exact exchange/symbol coverage, from the
model card or paper; (2) restrict any backtest of a Kronos-based
predictor to a window strictly after that cutoff, or treat any
overlapping-window result as contaminated and non-evidentiary; (3) get
this reviewed under its own ADR once (1) and (2) are actually done, not
assumed. Not installed; no code added.

### Decision 2 addendum — deeper check confirmed the blocker, and added a second one (original evaluation, not re-checked this session)

Reading `shiyu-coder/Kronos`'s README (the maintained upstream,
MIT-licensed) and its open issue tracker directly, rather than relying
on secondary summaries, found:

- The pre-training cutoff date is not published anywhere in the repo or
  model cards — the leakage risk is not merely unverified, it was
  unverifiable from public information at evaluation time.
- Open issue `shiyu-coder/Kronos#168` (filed 2025-10-25, unanswered as
  of that check) reports Kronos's temporal embeddings do not
  distinguish exchange/session context, weakening reliability for
  non-dominant markets — which includes this project's actual live-path
  exposure (Korean equities via `src/broker/toss`, ADR-0027; US
  equities, ADR-0028).
- License is MIT (no commercial obstacle); `predict()` returns a point
  forecast, not a distribution, so a `KronosPredictor` would need
  repeated stochastic sampling to populate `PredictionOutput`'s
  `uncertainty`/`confidence`.
- The upstream README itself states its reference pipeline is "a
  simplified example and not a production-ready quantitative trading
  system."

Conclusion unchanged (not adopted).

## Decision 3 — Reject NautilusTrader

NautilusTrader is a complete, independent algorithmic trading platform
(Rust-core event-driven backtester plus live execution engine) — not a
library that composes with this project's architecture, but a second,
competing implementation of exactly what Phases 1-14 already built and
validated with their own ADRs (`src/backtest`,
`src/broker/{paper,live,toss}`). Adopting it means either discarding
that already-built and tested infrastructure, or running two
independent systems that can each reach a broker — the second of which
is a direct Capital Safety violation on its own (two independent
order-placement paths is a coordination hazard this project's
kill-switch/safety-gate design was built specifically to avoid). Not
installed.

## Decision 4 — Reject Vibe-Trading

Vibe-Trading is a natural-language-driven agent that generates
strategies and places orders autonomously through a connected broker
("bounded, mandate-gated order placement"). Its own safety model
(user-set limits, instant halt) does not change what it fundamentally
is: an AI deciding and executing real trades from a prompt, with no
human approval gate per decision. This is the exact shape
`PROJECT_MASTER_PLAN.md`'s constitution rules out — `src/broker/live`
requires the kill switch clear and explicit human approval on every
path into it, with no exception for a tool that claims to be "bounded."
Not installed.

## Decision 5 — Adopt purgedcv as an optional dependency

Two separate files in this codebase each explicitly document the same
gap as deliberately reserved, not an oversight:

- `src/backtest/validation.py` (Phase 2, ADR-0008): Purged K-Fold /
  Embargo are reserved via `ValidationSplitter` but not implemented —
  ADR-0008 explicitly defers this to "whenever Phase 9's Learning
  Engine needs it."
- `src/strategy_research/evidence.py` (Phase 25, ADR-0031):
  `assess_pbo_dsr_applicability()` only checks whether the PBO/Deflated
  Sharpe Ratio *adoption trigger* conditions are met; its own docstring
  says the actual computation is "deferred here, not computed
  speculatively... a future phase should implement the actual
  computation."

Both cite the same source (`PROJECT_MASTER_PLAN.md` §71, "López de
Prado-style validation"; Bailey/Borwein/López de Prado/Zhu, "The
Probability of Backtest Overfitting"; Bailey/López de Prado, "The
Deflated Sharpe Ratio"). This is a stronger, more concretely evidenced
gap than skfolio's (Decision 1): two independent modules name it by
citation, not just an absence inferred by this evaluation.

Four candidate libraries were checked directly against source/PyPI
metadata, not assumed from name alone:

- **`pypbo`** (esvhd/pypbo) — implements PBO/PSR/MinTRL/MinBTL/DSR
  directly from the cited papers, but is **AGPL-3.0** (network-use
  copyleft — a real obligation this project has not evaluated or
  accepted for any other dependency) and shows no recent maintenance
  activity. Rejected.
- **`quant-integrity`** — same capability area, also **AGPL-3.0**.
  Rejected for the same licensing reason.
- **`sharpebench`** — MIT/Apache-2.0 (no license issue), but a compiled
  Rust kernel via PyO3 bindings from a commercial vendor, pre-1.0 with
  rapid week-over-week releases. A compiled, fast-moving binary is a
  materially worse fit than skfolio's pure-Python sklearn-style API —
  harder to audit, and pre-1.0 churn from a single vendor is a
  reproducibility risk this project has not needed to accept for any
  dependency so far. Rejected for now, not ruled out permanently.
- **`purgedcv`** (eslazarev/purged-cross-validation, PyPI `purgedcv`) —
  **MIT-licensed**, scikit-learn-compatible (`PurgedKFold`,
  `PurgedGroupKFold`, `CombinatorialPurgedCV`), and is the only
  candidate that fills *both* named gaps at once:
  `purge()`/`apply_embargo()`/`CombinatorialPurgedCV` for ADR-0008's
  reserved Purged K-Fold/Embargo, and
  `deflated_sharpe_ratio()`/`probability_of_backtest_overfitting()`/
  `probabilistic_sharpe_ratio()`/`min_track_record_length()`/
  `minimum_backtest_length()` for `evidence.py`'s deferred PBO/DSR
  computation.

  **Caveat, stated plainly**: unlike skfolio (a mature 1.x release),
  `purgedcv` is PyPI classifier "Development Status :: 3 - Alpha" at
  version 0.1.6, from a single maintainer with modest adoption. This is
  a real maturity gap against skfolio's bar — API surface should be
  re-verified against whatever version is current when integration
  work actually begins, not assumed stable from this evaluation.

**Independently re-verified this session**: `pip install
"purgedcv>=0.1.6"` succeeds (resolved to 0.1.6, `pip show` confirms MIT
license), and `dir(purgedcv)` confirms every name cited above
(`PurgedKFold`, `probability_of_backtest_overfitting`,
`deflated_sharpe_ratio`, etc.) is a real, present export — not taken
from documentation alone.

Added to `pyproject.toml` under a new `backtest-integrity-stats`
extra. **Not wired into `src/backtest/validation.py` or
`src/strategy_research/evidence.py`.** Wiring it in is separate,
scheduled Phase work (Phase 9's Learning Engine per ADR-0008, and/or
whichever phase first has multiple real-data walk-forward candidates
to compare per `assess_pbo_dsr_applicability`'s own trigger condition).

## Decision 6 — Record statsmodels/darts/sktime as a future `MODEL_BASED` predictor candidate (not adopted)

`src/predict/enums.py` defines `PredictionMethodType.MODEL_BASED` as
reserved — no implementation ships; every current `Predictor` is
`DETERMINISTIC_BASELINE` and contains no statistical/ML forecasting
code. This is a real and explicitly reserved extension point — but
unlike Decision 5, no concrete implementation work is scheduled against
it in any current Phase, so no library is adopted here. This entry
exists only so a future session opening a `MODEL_BASED` predictor Phase
does not have to re-research the landscape from zero.

Candidates worth checking first when that Phase opens, in rough order
of fit to this project's existing `Predictor.predict()` contract:

- **`statsmodels`** — classical, transparent, in-sample-fit forecasting
  (ARIMA/SARIMAX, exponential smoothing, state-space models). BSD-3.
  Every model is a documented statistical procedure, not a black box.
  Confidence/prediction intervals map directly onto
  `PredictionOutput.uncertainty`/`confidence` without a sampling
  workaround. Likely the first to actually evaluate in depth.
- **`sktime`** — scikit-learn-style unified forecasting API (wraps
  statsmodels and others behind one interface, similar in spirit to
  skfolio's role for portfolio optimization). BSD-3.
- **`darts`** — broader forecasting library spanning classical and
  deep-learning models under one API. Apache-2.0. Its deep-learning
  models reintroduce a version of the Kronos pre-training-provenance
  question — only its classical-model wrappers are a clean fit today.

Not installed. No code added. This is a research pointer, not a
dependency decision.

## Decision 7 — Adopt exchange_calendars as an optional dependency

`src/data_infra/calendar.py`'s own docstring names this exact gap: its
hand-picked holiday sample is explicitly NOT production-accurate, and
sourcing a real one is deferred. Reading the actual data confirms how
small: `US_EQUITY` lists exactly 3 holiday dates and `KR_EQUITY` exactly
2, both for calendar year 2024 only — no Lunar New Year/Chuseok
(Korea's multi-day lunar holidays, which shift dates every year), no
MLK Day/Presidents Day/Memorial Day/Juneteenth/Labor Day/Thanksgiving
(US). This project's actual broker exposure is Korean equities
(`src/broker/toss`, ADR-0027) and US equities (ADR-0028) — the two
markets `TradingCalendar` exists to model.

**Independently re-verified this session**: `pip install
"exchange_calendars>=4.13.2"` succeeds (resolved to 4.13.2), and
`get_calendar("XKRX")`/`get_calendar("XNYS")` return real 2026
calendars — `XKRX`'s 2026 session list correctly excludes 2026-02-16
through 2026-02-18 (Seollal, Lunar New Year), confirmed by direct
`sessions_in_range` query, not merely re-stated from the original
evaluation's own claim.

A related candidate, **`almgren-chriss`** (for the "future, more
rigorous [market impact] model" ADR-0007 names as deferred from
`VolumeScaledSlippageModel`), was checked and rejected in the original
evaluation: single-author personal project, last released 2023-05-30,
PyPI license field an unclear, likely-copyleft license — matching the
same red flag that rejected `pypbo`/`quant-integrity` in Decision 5. No
other established Almgren-Chriss package was found. This gap stays
unfilled — a real gap exists, but no adoptable library was found for it
in this pass.

**Not adopted, checked but inconclusive**: `src/counterfactual/
attribution.py`'s reserved `sector`/`factor`/`timing` fields (ADR-0016
points 6-7) would need a factor-attribution library (e.g.
`alphalens-reloaded`, since ADR-0139, or a `statsmodels`-based
regression against Fama-French-style factor returns). Every option in
this space needs externally-sourced factor return data as an input —
a data-access problem, not a library-selection problem.

Added to `pyproject.toml` under a new `market-calendars` extra.
**Not wired into `src/data_infra/calendar.py`.** `TradingCalendar` is
already a `Protocol` specifically so a future
`ExchangeCalendarsAdapter`-style implementation is a drop-in addition;
building and swapping it in is separate, scheduled follow-up work, not
part of this ADR.

## Consequences

- `pyproject.toml` gains three new optional extras:
  `portfolio-optimization` → `skfolio>=1.2.1` (Decision 1),
  `backtest-integrity-stats` → `purgedcv>=0.1.6` (Decision 5), and
  `market-calendars` → `exchange_calendars>=4.13.2` (Decision 7). The
  core install is unchanged, so existing environments are unaffected
  until someone explicitly opts in.
- No change to `src/`. Using skfolio inside `src/risk/`, purgedcv inside
  `src/backtest/validation.py` / `src/strategy_research/evidence.py`,
  and exchange_calendars inside `src/data_infra/calendar.py`, are all
  separate, scheduled Phase work, not part of this ADR.
- Kronos stays out until the pre-training-leakage question in Decision
  2 is answered with evidence, not assumption.
- `almgren-chriss` stays out: stale, unclear-license, no established
  alternative found yet for ADR-0007's deferred market-impact model.
- Factor/sector/timing attribution (`src/counterfactual/attribution.py`,
  ADR-0016) remains unfilled — blocked on real factor-return data
  access, not on library choice.
- statsmodels/darts/sktime are recorded (Decision 6) as the starting
  point for a future `MODEL_BASED` predictor Phase, not adopted now —
  no such Phase is currently open.
- The `claude/ruflo-features-review-hqrvqa` branch itself (its own
  archify architecture-diagram commits and Claude Code tooling/skills
  commits, neither part of this ADR's scope) remains unmerged and
  untouched — this recovery deliberately took only this one ADR's
  documented content and the three `pyproject.toml` lines, per the
  account owner's own explicit choice, not the whole branch.

## Tests

No new tests — this ADR adds documentation and optional (not
core-installed) `pyproject.toml` extras only, matching the original
evaluation's own scope (none of the three adopted libraries are wired
into `src/`). Full suite re-run confirms no regression from the
`pyproject.toml` change alone.

## Status of Implementation at Time of This ADR

Documentation and `pyproject.toml` extras complete and committed. Wiring
any of the three adopted libraries into `src/` remains separate,
unscheduled future work, as the original evaluation also stated.
