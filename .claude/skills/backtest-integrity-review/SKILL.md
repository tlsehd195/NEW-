---
name: backtest-integrity-review
description: Review backtest, strategy-research, and data-ingestion code for lookahead bias, survivorship bias, point-in-time violations, and corporate-action/calendar data-quality bugs. Use before trusting any backtest/strategy result, when writing or reviewing code in src/backtest, src/strategy_research, src/data_infra, or src/predict, or when a new data provider/bar source is wired in.
---

# Backtest & Data Integrity Review

Quant backtests fail silently: the code runs, produces a Sharpe ratio, and
is wrong. Generic code review (types, tests, style) does not catch this
class of bug. This skill is a checklist to run specifically against
`src/backtest`, `src/strategy_research`, `src/data_infra`, `src/predict`,
and any script that ingests or replays market data, before a result is
allowed to inform a decision.

Read `docs/decisions/` (ADRs) and `PROJECT_MASTER_PLAN.md` section on
backtest/validation rules first, so findings are framed against the
project's own stated rules, not generic quant folklore.

## 1. Lookahead bias

- Does any signal, feature, or label computation reach forward in time
  relative to the bar/timestamp it is attached to? Check `shift`/`rolling`
  boundary conditions, joins on date without an as-of/merge_asof
  discipline, and any place a full-history array is indexed before slicing
  to "as of T".
- Are train/validation/test splits time-ordered (no data from the future
  leaking into training via shuffled splits, k-fold CV on time series, or
  a scaler/normalizer fit on the full series before splitting)?
- Does execution assume fills at a price the strategy could not have
  known when it decided to trade (e.g. filling at the same bar's close
  when the decision was made using that same close)?

## 2. Survivorship & universe bias

- Is the trading universe built from a **current** constituent list
  applied to historical dates (survivorship bias), or from a
  point-in-time constituent history?
- Are delisted/bankrupt/acquired symbols represented in the historical
  universe, or silently dropped?
- Corporate actions (splits, dividends, ticker changes, mergers): are they
  applied to price/volume series consistently, and stored — not just
  applied in memory and discarded? (This repo has already hit this bug
  once: the ingestion script did not persist corporate actions at all —
  see `docs/PROJECT_STATUS.md` Phase 24-28 notes and
  `scripts/ingest_real_market_data.py`.)

## 3. Calendar & bar integrity

- Does the trading calendar match the actual exchange calendar for every
  symbol in the universe (holidays, half-days, DST transitions)? Check
  `src/data_infra/calendar.py` conventions before trusting any gap/missing
  bar count.
- Are gaps in the bar series distinguished from legitimate non-trading
  days? A calendar bug can silently look like "no lookahead bias" while
  actually just failing to test the strategy on the days that matter.
- Timezone consistency: is every timestamp in the pipeline attached to an
  explicit, consistent timezone (exchange-local vs UTC), especially across
  provider boundaries (Tiingo, Stooq, Toss)?

## 4. Statistical validity of results

- Is a single backtest window ever reported as conclusive? Per this
  project's own rules, a result needs train/validation/test (or
  walk-forward) separation before it can be called anything but
  **INCONCLUSIVE**. Flag any report, ADR, or status doc that states a
  performance number without naming its window and split.
- Overfitting surface: how many parameters/strategies were tried before
  this one was reported? An unreported search multiplies false-discovery
  risk even if the single backtest shown has no coding bug.

## 5. Real vs simulated data labeling

- Never let a backtest run against simulated/paper data be described as
  validating something about real market behavior. If unsure whether a
  result came from real ingested data or a fixture/mock, trace it back to
  the ingestion source before writing anything into `PROJECT_STATUS.md` or
  an ADR. (See the `validation-status-guard` skill for the exact language
  rules this project uses.)

## Output

Report findings the same way `code-review` does: file, line, the specific
mechanism (which of the above categories), and the concrete failure
scenario (what wrong number or decision it would produce and under what
data). Don't flag generic style issues here — this skill is scoped to the
categories above only.
