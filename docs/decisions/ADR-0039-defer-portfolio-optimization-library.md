# ADR-0039: Defer adopting a portfolio-optimization library (PyPortfolioOpt / Riskfolio-Lib)

## Context

Earlier this session, GitHub research (at the user's request) surfaced
two portfolio-optimization candidates as the natural next architectural
gap: this project has a "signal generation -> position sizing -> order"
pipeline but no independent "portfolio construction" stage (deciding
how to allocate capital across multiple signals/securities, as opposed
to each strategy's own ad-hoc sizing logic).

- **PyPortfolioOpt** (~6.0k stars): efficient frontier, Black-Litterman,
  Hierarchical Risk Parity. Requires `numpy`/`scipy`.
- **Riskfolio-Lib** (~4.5k stars): broader risk-based portfolio
  optimization/risk-contribution analysis. Requires `numpy`/`scipy`,
  and `cvxpy` for some methods.

The user relayed independent ChatGPT advice on this same question:
adopt either only after the in-flight 40-symbol real walk-forward
result was known. That result is now recorded
(`docs/research/STRATEGY-VALIDATION-REPORT.md`, "40-Symbol
(RESEARCH_UNIVERSE Stage 2) Re-Validation").

## The result this decision is actually being made against

- All 4 existing strategies remain `ROBUSTNESS_PENDING` -- none reaches
  `CANDIDATE` (PBO/DSR bar). `trend_volatility` is closest (DSR 0.93 vs
  the 0.95 bar) but still a documented miss.
- Against the one held-out TEST window this project has ever evaluated
  these strategies on (2023-2026), **all 4 substantially underperformed
  simply holding SPY** (4.0%-40.4% net vs. SPY's 93.1%).
- The `risk_controlled_momentum` diagnosis in the same report section
  found that this project's *existing*, much simpler risk-allocation
  logic (inverse-volatility weighting + a position cap) actively hurt
  performance in this window, by leaving capital structurally idle
  during a persistent, narrow rally.

## Decision: do not adopt a portfolio-optimization library at this time

**Reasoning:**

1. **There is no validated signal to allocate capital across yet.**
   Portfolio optimization (mean-variance, HRP, Black-Litterman, or
   any risk-parity variant) takes expected-return/risk estimates as
   input and answers "how should capital be split across these
   candidates." Every input to that question is currently either
   `ROBUSTNESS_PENDING` or actively outperformed by doing nothing more
   sophisticated than holding SPY. Optimizing the allocation across
   signals that are not (yet) known to carry real edge does not create
   edge -- it can only reshape how a non-edge is distributed.
2. **This project only ever runs one strategy at a time.** Every
   backtest, walk-forward fold, and held-out TEST run in this project's
   history evaluates exactly one strategy's signal against the full
   universe -- there is no existing multi-strategy blending step for a
   portfolio optimizer to sit underneath. Adopting one now would be
   architecture built ahead of a concrete, present need, not in
   response to one.
3. **The `risk_controlled_momentum` finding is a direct, cautionary
   data point against introducing more allocation machinery
   right now.** The simplest form of "smarter" allocation this project
   has actually tried (inverse-vol weighting + a cap) made results
   *worse* in the one window tested, via a genuine implementation bug
   (uninvested cash from capped/not-topped-up weights) rather than a
   flaw in the concept of risk-weighting itself -- but it is direct
   evidence that added allocation sophistication is easy to get subtly
   wrong in ways that only show up against real, out-of-sample data,
   reinforcing point 1 rather than motivating a bigger optimizer sooner.
4. **Minimum-dependency discipline.** Both candidates require
   `numpy`/`scipy` (Riskfolio-Lib additionally `cvxpy` for some
   methods) against a project whose only current dependencies are
   `duckdb`/`pyarrow`, and whose PBO/Deflated Sharpe Ratio
   implementation was deliberately built stdlib-only rather than adopt
   a bigger dependency for a similar reason. That discipline is not an
   absolute rule (a genuinely justified need would outweigh it), but
   there is no such need demonstrated yet.

## Conditions for revisiting this decision

Not "never" -- specifically:

1. At least one strategy (rule-based or, later, ML-based) reaches
   `CANDIDATE` evidence against a real, not-yet-observed TEST window, AND
2. There is a concrete plan to run **more than one** validated signal
   concurrently, such that how capital is split across them becomes an
   actual open question this project needs to answer (rather than a
   capability added speculatively).

If and when both hold, PyPortfolioOpt is the more likely fit of the two
(narrower `numpy`/`scipy`-only dependency footprint vs. Riskfolio-Lib's
optional `cvxpy` requirement for some of its methods), but that
sub-choice is deliberately not finalized here since the precondition
for needing either has not been met.

## Consequences

- No new dependency added. No `src/` code changed by this ADR.
- The "signal generation -> position sizing -> order" pipeline stays
  as documented; a portfolio-construction stage remains a known,
  explicitly deferred future gap rather than a silently-forgotten one.
