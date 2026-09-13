# ADR-0032: External Quant Library Evaluation (Kronos, skfolio, NautilusTrader, Vibe-Trading)

## Context

Four external tools were proposed for adoption into this project: Kronos
(a financial time-series foundation model), skfolio (a portfolio
optimization library), NautilusTrader (a complete algorithmic trading
platform), and Vibe-Trading (an autonomous AI trading agent). Each was
evaluated against this project's actual code (not just its stated
purpose) and against `PROJECT_MASTER_PLAN.md`'s priority order (Capital
Safety > Data Integrity > Reproducibility > Validation > Risk Control >
...).

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

## Consequences

- `pyproject.toml` gains one new optional extra
  (`portfolio-optimization` -> `skfolio>=1.2.1`); the core install is
  unchanged, so existing environments are unaffected until someone
  explicitly opts in.
- No change to `src/`. Using skfolio inside `src/risk/` (or wherever a
  future portfolio-level allocator lands) is separate, scheduled Phase
  work, not part of this ADR.
- Kronos stays out until the pre-training-leakage question in Decision 2
  is answered with evidence, not assumption.
