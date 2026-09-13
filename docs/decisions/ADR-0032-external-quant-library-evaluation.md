# ADR-0032: External Quant Library Evaluation (Kronos, skfolio, NautilusTrader, Vibe-Trading, purgedcv)

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

## Decision 1 -- Adopt skfolio as an optional dependency

`src/risk/sizing.py` (Phase 8, read in full for this evaluation) sizes
one security at a time from `PortfolioView` + `PredictionOutput`; there
is no covariance-aware, multi-asset allocation step anywhere in the
codebase, despite the package docstring calling Phase 8 a "Portfolio Risk
Engine." skfolio (BSD-licensed, built on `scikit-learn`'s
fit-predict-transform API, mean-variance/risk-parity/clustering-based
allocators) is a mature, transparent fit for that specific, verified gap
-- it is not a black box, and every allocator it ships is a
well-documented, auditable optimization, consistent with this project's
"no code path may claim results it cannot justify" standard.

Added as an optional dependency group (`portfolio-optimization`) in
`pyproject.toml`, not a core dependency and not yet wired into
`src/risk/`: adopting the library and designing how a multi-asset
allocator plugs into the existing single-security `PositionSizer`
Protocol are two different decisions. The latter needs its own Phase
work (a new `PortfolioAllocator`-shaped Protocol, or an extension of
`PositionSizer`, plus tests) and is out of scope here -- this ADR only
clears the library for use once that Phase is scheduled.

## Decision 2 -- Do not adopt Kronos yet; the blocking question is pre-training data leakage

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
cover -- `AsOfDataView` only prevents a strategy from querying rows
outside `[start, current_time]` in this system's own data store; it has
no visibility into what an externally pre-trained model already
memorized.

Before Kronos can be adopted: (1) obtain Kronos's pre-training data
cutoff date and, ideally, the exact exchange/symbol coverage, from the
model card or paper; (2) restrict any backtest of a Kronos-based
predictor to a window strictly after that cutoff, or treat any
overlapping-window result as contaminated and non-evidentiary per
`backtest-integrity-review`'s standard; (3) get this reviewed under its
own ADR once (1) and (2) are actually done, not assumed. Not installed;
no code added.

### Decision 2 addendum -- deeper check confirms the blocker, and adds a second one

Read `shiyu-coder/Kronos`'s README (the maintained upstream, MIT-licensed)
and its open issue tracker directly, rather than relying on secondary
summaries:

- **Requirement (1) above currently cannot be satisfied.** The README
  states training used "over 45 global exchanges" but publishes no
  cutoff date or exchange/symbol list anywhere in the repo or model
  cards. The pre-training-leakage risk is not merely unverified, it is
  presently unverifiable from public information. This is a stronger
  blocker than originally recorded, not a weaker one.
- **A second, independent reliability concern**: open issue
  `shiyu-coder/Kronos#168` (filed 2025-10-25, no maintainer response as
  of this check) reports that Kronos's temporal embeddings do not
  distinguish exchange/session context -- "hour = 9" is encoded the same
  way whether it means Tokyo's open or New York's pre-market -- which
  the reporter argues introduces "structured noise" and degrades
  transfer to markets outside the dominant training distribution. This
  project's live-path exposure is Korean equities via `src/broker/toss`
  (ADR-0027) and US equities (ADR-0028) -- exactly the kind of
  non-dominant-market usage this issue flags as weakest.
- License is MIT (no commercial-use obstacle). Input is OHLCV bars
  (max context 512) plus separate timestamp series; `predict()` returns
  a **point forecast** DataFrame, not a distribution -- `PredictionOutput`
  needs `expected_volatility`/`uncertainty`/`confidence`, so a
  `KronosPredictor` would need repeated stochastic sampling to derive
  those, adding inference cost this evaluation did not size.
- The upstream README itself states the reference pipeline is "a
  simplified example and not a production-ready quantitative trading
  system" -- the authors' own framing agrees with this ADR's caution.

Conclusion unchanged (not adopted), on firmer evidence.

## Decision 3 -- Reject NautilusTrader

NautilusTrader is a complete, independent algorithmic trading platform
(Rust-core event-driven backtester plus live execution engine) --
not a library that composes with this project's architecture, but a
second, competing implementation of exactly what Phases 1-14 already
built and validated with their own ADRs (`src/backtest`,
`src/broker/{paper,live,toss}`). Adopting it means either discarding that
already-built and tested infrastructure, or running two independent
systems that can each reach a broker -- the second of which is a direct
Capital Safety violation on its own (two independent order-placement
paths is a coordination hazard this project's kill-switch/safety-gate
design was built specifically to avoid). Not installed.

## Decision 4 -- Reject Vibe-Trading

Vibe-Trading is a natural-language-driven agent that generates strategies
and places orders autonomously through a connected broker ("bounded,
mandate-gated order placement"). Its own safety model (user-set limits,
instant halt) does not change what it fundamentally is: an AI deciding
and executing real trades from a prompt, with no human approval gate per
decision. This is the exact shape `PROJECT_MASTER_PLAN.md`'s constitution
rules out -- `src/broker/live` requires the kill switch clear and
explicit human approval on every path into it, with no exception for a
tool that claims to be "bounded." Not installed.

## Decision 5 -- Adopt purgedcv as an optional dependency

Two separate files in this codebase each explicitly document the same gap
as deliberately reserved, not an oversight:

- `src/backtest/validation.py` (Phase 2, ADR-0008): "Purged K-Fold /
  Embargo are reserved via `ValidationSplitter` but not implemented" --
  ADR-0008 explicitly defers this to "whenever Phase 9's Learning Engine
  needs it."
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
citation, not just an absence this evaluation inferred.

Four candidate libraries were checked directly against source/PyPI
metadata, not assumed from name alone:

- **`pypbo`** (esvhd/pypbo) -- implements PBO/PSR/MinTRL/MinBTL/DSR
  directly from the cited papers, but is **AGPL-3.0** (network-use
  copyleft -- a real obligation this project has not evaluated or
  accepted for any other dependency) and shows no recent maintenance
  activity (open issues, no PRs, incomplete TODOs, an odd `seaborn`
  hard dependency for a stats library). Rejected.
- **`quant-integrity`** -- same capability area, also **AGPL-3.0**.
  Rejected for the same licensing reason.
- **`sharpebench`** -- MIT/Apache-2.0 (no license issue), but a
  compiled Rust kernel via PyO3 bindings from a commercial vendor
  (General Liquidity, Inc.), pre-1.0 with rapid week-over-week releases
  (0.18.1 -> 0.25.0 observed within the evaluation window). A compiled,
  fast-moving binary is a materially worse fit than skfolio's pure-Python
  sklearn-style API against this project's "no code path may claim
  results it cannot justify" standard -- harder to audit, and pre-1.0
  churn from a single vendor is a reproducibility risk this project has
  not needed to accept for any dependency so far. Rejected for now, not
  ruled out permanently.
- **`purgedcv`** (eslazarev/purged-cross-validation, PyPI `purgedcv`) --
  **MIT-licensed**, scikit-learn-compatible (`PurgedKFold`,
  `PurgedGroupKFold`, `CombinatorialPurgedCV`, matching skfolio's
  precedent of favoring sklearn-API libraries), and is the only candidate
  that fills *both* named gaps at once: `purge()`/`apply_embargo()`/
  `CombinatorialPurgedCV` for ADR-0008's reserved Purged K-Fold/Embargo,
  and `deflated_sharpe_ratio()`/`probability_of_backtest_overfitting()`/
  `probabilistic_sharpe_ratio()`/`min_track_record_length()`/
  `minimum_backtest_length()` for `evidence.py`'s deferred PBO/DSR
  computation. Confirmed by direct install and `dir(purgedcv)` inspection
  (not taken from documentation alone) -- all of the above names are
  real, present exports. Its own stated validation evidence (synthetic
  leakage tests showing naive K-Fold reports R^2 ~ 0.83-0.91 on an
  unpredictable target while purged K-Fold correctly collapses it to
  negative) demonstrates the exact failure mode Purged K-Fold exists to
  catch.

  **Caveat, stated plainly**: unlike skfolio (a mature 1.x release),
  `purgedcv` is PyPI classifier "Development Status :: 3 - Alpha" at
  version 0.1.6, from a single maintainer with modest adoption (33
  GitHub stars). This is a real maturity gap against skfolio's bar, not
  glossed over -- API surface should be re-verified against whatever
  version is current when integration work actually begins, not assumed
  stable from this evaluation.

Installed as an optional dependency (`pip install purgedcv==0.1.6`
verified; MIT license confirmed via package metadata, not just the
repository README) and added to `pyproject.toml` under a new
`backtest-integrity-stats` extra. **Not wired into `src/backtest/
validation.py` or `src/strategy_research/evidence.py`.** Wiring it in is
separate, scheduled Phase work (Phase 9's Learning Engine per ADR-0008,
and/or whichever phase first has multiple real-data walk-forward
candidates to compare per `assess_pbo_dsr_applicability`'s own trigger
condition) -- and that trigger condition itself cannot fire yet, since
`docs/PROJECT_STATUS.md` confirms this project still has no real market
data access (`BLOCKED_BY_ENVIRONMENT` / `BLOCKED_BY_DATA`). Adopting the
library now only removes the "does a suitable one exist" research step
from that future Phase; it does not schedule or start that Phase.

## Decision 6 -- Record statsmodels/darts/sktime as a future `MODEL_BASED` predictor candidate (not adopted)

`src/predict/enums.py` defines `PredictionMethodType.MODEL_BASED` as
"reserved -- no implementation ships in Phase 6"; every current
`Predictor` (`RandomWalkPredictor`, `DriftPredictor`,
`RegimeAwarePredictor`, all read in full for this evaluation) is
`DETERMINISTIC_BASELINE` and contains no statistical/ML forecasting code.
This is, by the same standard applied to Decision 5, a real and
explicitly reserved extension point -- but unlike Decision 5, no
concrete implementation work is scheduled against it in any current
Phase, so no library is adopted here. This entry exists only so a future
session opening a `MODEL_BASED` predictor Phase does not have to
re-research the landscape from zero.

Candidates worth checking first when that Phase opens, in rough order of
fit to this project's existing `Predictor.predict()` contract
(deterministic, versioned, `AsOfDataView`-sourced, returns
`PredictionOutput` with `expected_return`/`probability`/
`expected_volatility`/`uncertainty`/`confidence` -- not a raw point
forecast):

- **`statsmodels`** -- classical, transparent, in-sample-fit forecasting
  (ARIMA/SARIMAX, exponential smoothing, state-space models). BSD-3.
  Every model is a documented statistical procedure, not a black box --
  the same auditability bar skfolio cleared. Confidence
  intervals/prediction intervals map directly onto
  `PredictionOutput.uncertainty`/`confidence` without the sampling
  workaround Kronos would have needed (Decision 2 addendum). Likely the
  first one to actually evaluate in depth, precisely because it is the
  most conservative fit.
- **`sktime`** -- scikit-learn-style unified forecasting API (wraps
  statsmodels, exponential smoothing, and others behind one interface,
  similar in spirit to skfolio's role for portfolio optimization). BSD-3.
  Worth checking as a thinner integration layer once a specific
  statsmodels-based method is chosen, not as a replacement for reading
  the underlying model.
- **`darts`** -- broader forecasting library spanning classical and
  deep-learning models under one API. Apache-2.0. Its deep-learning
  models reintroduce a version of the Kronos pre-training-provenance
  question (a model with learned weights needs the same "what did it see
  during training" scrutiny) -- only its classical-model wrappers
  (ARIMA/Theta/exponential smoothing, effectively re-exposing
  statsmodels) are a clean fit today; its neural forecasters should be
  evaluated under the same standard Decision 2 applied to Kronos, not
  assumed safe by association with the rest of the package.

Not installed. No code added. This is a research pointer, not a
dependency decision.

## Consequences

- `pyproject.toml` gains two new optional extras:
  `portfolio-optimization` -> `skfolio>=1.2.1` (Decision 1) and
  `backtest-integrity-stats` -> `purgedcv>=0.1.6` (Decision 5). The core
  install is unchanged, so existing environments are unaffected until
  someone explicitly opts in.
- No change to `src/`. Using skfolio inside `src/risk/`, and using
  purgedcv inside `src/backtest/validation.py` /
  `src/strategy_research/evidence.py`, are both separate, scheduled Phase
  work, not part of this ADR.
- Kronos stays out until the pre-training-leakage question in Decision 2
  is answered with evidence, not assumption.
- statsmodels/darts/sktime are recorded (Decision 6) as the starting
  point for a future `MODEL_BASED` predictor Phase, not adopted now --
  no such Phase is currently open.
