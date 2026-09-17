# ADR-0138: `quantstats` HTML Tearsheet for Paper Trading's Real Equity Curve

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0136-wire-paper-performance-report-into-daily-cycle.md`
(the equity-curve source this ADR's script reuses unchanged)

---

## Context

One of the account owner's own uploaded external-resource-recommendation
reports named `quantstats`/`quantstats-reloaded` as a zero-cost way to
turn this project's already-computed equity curve into a real, readable
HTML tearsheet, recommending the "actively maintained" `quantstats-
reloaded` fork over the original. Continuing the account owner's
"쉬운거부터 순서대로" (easiest-first) pass through these reports'
findings.

## Decision 1 -- `quantstats`, NOT `quantstats-reloaded`, after finding a real crash in the fork

Before adopting either, both were installed and run against a real,
representative single-strategy/no-benchmark returns series (this
project's own actual case -- no S&P 500 data has been ingested,
ADR-0005) -- never assumed to work from documentation alone. Result:
`quantstats-reloaded==0.1.0`'s own `reports.metrics()` raises a real,
reproducible `ValueError` ("Length of values (2) does not match length
of index (1)") for exactly this case, confirmed at multiple series
lengths (39, 299 points) and traced to its own source
(`reports.py:802`, `blank = ["", ""]` unconditionally overwrites an
earlier, correct `blank = [""]` for the single-Series/no-benchmark
branch a few lines above, then `metrics["~"] = blank` tries inserting
a 2-element list into what is, in that branch, a genuinely 1-row
DataFrame). The ORIGINAL `quantstats==0.0.81` was tested identically
(series lengths 1 through 300) and does not have this bug -- confirmed
by producing real, non-empty HTML tearsheets in every case except the
genuinely-insufficient 0-real-return case (1 raw price point), which it
fails on with a real, honest `IndexError` rather than fabricating a
report -- exactly the case this ADR's own script guards against before
ever calling `quantstats` (Decision 3). Adopting the "actively
maintained" fork sight-unseen, as the external report suggested, would
have shipped a script that crashes on this project's own single most
common real usage pattern.

## Decision 2 -- optional `[reporting]` extra, never a core dependency; the equity curve is reused, not recomputed

`quantstats` requires `pandas`/`numpy`/`matplotlib`/`scipy`/`seaborn` --
none of which `src/` has ever imported (confirmed by a repo-wide
search: zero real `import pandas`/`import numpy` under `src/` before
this ADR). Added as a new `reporting` entry under `[project.optional-
dependencies]` in `pyproject.toml`, never `dependencies` -- the base
install stays exactly as pandas/numpy-free as it always was.
`scripts/generate_paper_performance_tearsheet.py` imports `pandas`/
`quantstats` itself, lazily, inside `main()`, with a clear "install
with `pip install -e '.[reporting]'`" message on `ImportError` rather
than a raw traceback if the extra was never installed.

The equity curve this script reads is the exact same real, durable
source `scripts/run_paper_trading_cycle.py`'s own `_equity_history()`
already established (ADR-0136): `RiskCheckedPosition.as_of_time`/`.
risk_state.portfolio_value`, one real snapshot per checkpoint,
queried directly from a real `--paper-store`'s own `DuckDBRiskRepository`
-- never `PortfolioAccounting.value_series` (real only within one
process, per that ADR's own Decision 2), and never a second,
independently-computed equity curve that could silently drift from the
one `compute_paper_performance_report` itself uses.

## Decision 3 -- fails cleanly, never fabricates, on insufficient data

Direct testing found `quantstats.reports.html()` raises a raw
`IndexError` on a zero-return series (a single real portfolio-value
checkpoint) -- confirmed, not guessed. The script checks `len(equity_
history) < 2` itself first and exits 1 with a clear message before
ever calling `quantstats`, matching this project's own "never let
insufficient data crash something obscurely; fail closed with a clear
reason" discipline (the same one `compute_paper_performance_report`
itself already applies via its own `reasons` dict).

## Consequences

### Positive

- A real, first-of-its-kind visual performance tearsheet for this
  project's Paper Trading track record, reusing (not duplicating) the
  exact equity curve ADR-0136 already made durable and authoritative.
- A real, documented, source-traced bug report for `quantstats-
  reloaded`'s maintainer, produced as a side effect of this project's
  own "verify before adopting" discipline -- available if a future
  session wants to file it upstream.
- `src/` remains free of `pandas`/`numpy` as a hard dependency; the new
  extra is fully opt-in.

### Negative / Trade-offs

- `quantstats==0.0.81` is not under active development (last release
  predates the `-reloaded` fork's own creation) -- a future pandas/
  numpy release could introduce a similar incompatibility; this ADR's
  own direct-testing method (run it against this project's real data
  shape before trusting it) is the documented way to re-check that,
  not a promise it will never break.
- Only wired as a standalone, manually-invoked script -- not yet added
  to `.github/workflows/paper_trading_cycle.yml`'s own scheduled run
  (that workflow's `ubuntu-latest` runner would need the `[reporting]`
  extra installed, and the resulting HTML would need somewhere to go,
  e.g. an artifact upload or the Discord webhook (ADR-0146) sending a
  link) -- left as a natural next step, not done here, since this
  session's own scope was "wire the library up and prove it works,"
  not "add a second scheduled workflow step."

## Tests

`tests/scripts/test_generate_paper_performance_tearsheet_cli.py` (7
tests: a real end-to-end HTML tearsheet from a real seeded
`DuckDBRiskRepository`, a custom title appearing in the real output,
fewer-than-2/zero-checkpoint/missing-store failure modes, module
syntax validity) -- `pytest.importorskip("quantstats")`/`("pandas")`
guard every test so the suite skips cleanly (not fails) wherever the
optional `[reporting]` extra was never installed. Full suite re-run
clean after these changes, with the extra installed in this session's
own sandbox.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed. Not wired into
any scheduled GitHub Actions workflow -- see Consequences above.
