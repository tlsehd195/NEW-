# ADR-0050: Bake the verified XOM CIK override into the ingestion script's default, not just a CLI flag

**Status:** Accepted
**Session:** 36

## Context

ADR-0042 already found and fixed, once, a real data-correctness bug:
SEC EDGAR's *current* ticker->CIK map resolves `XOM` to a
newly-registered holding-company CIK (`entityName: "ExxonMobil
Holdings Corp"`, a handful of filings) instead of the operating
company's actual CIK (`0000034088`, `entityName: "Exxon Mobil
Corporation"`, the real multi-decade filing history) -- a corporate
reorganization orphaned the old CIK from ticker-based lookup. The fix
at the time was `--cik-overrides XOM:0000034088`, a CLI flag the
caller must remember to pass on every run.

That is exactly what happened: this session, the user ran the 63-symbol
`ingest_fundamentals_data.py --universe RESEARCH_UNIVERSE` command I
gave them, without `--cik-overrides` (I omitted it from the command in
my own instructions). The real output confirms the exact bug recurred:

```
[15/63] XOM (CIK 0002115436, source=ticker_map): fetching company facts...
    -> 30 record(s) persisted
```

`0002115436` is the same wrong holdco CIK from ADR-0042; every other
symbol persisted hundreds to low thousands of records, XOM persisted
30. A CLI flag that depends on a human remembering it every single run
is not a durable fix for a correction that is already fully verified
(confirmed by direct `curl` against SEC EDGAR in ADR-0042, not a
guess) -- this is not "the model might resolve differently next time
and we should stay flexible," it is a known-wrong mapping for a known
symbol.

## Decision

Added `_KNOWN_CIK_OVERRIDES = {"XOM": "0000034088"}` to
`scripts/ingest_fundamentals_data.py`, applied automatically:
`cik_overrides` is now seeded from this dict before `--cik-overrides`
parsing runs, so XOM resolves correctly on every run with zero extra
flags. An explicit `--cik-overrides XOM:...` entry still overrides the
default (in case, e.g., another reorganization requires updating it
later) -- the seed happens first, the parsing loop's assignment into
the same dict happens after and wins.

This is not a new mechanism -- `--cik-overrides` (ADR-0042) already
existed and already does exactly this override; the only change is
*where the XOM entry lives* (baked into the script, not dependent on
being retyped correctly by whoever runs it next). No other symbol is
added to `_KNOWN_CIK_OVERRIDES` -- XOM is the only one with a
confirmed, curl-verified wrong mapping; the general problem (some of
the other 38 original symbols could have a less extreme version of the
same issue) remains an open, explicitly documented caveat from
ADR-0042, unchanged by this ADR.

## Why this is not a RULE 0.8 violation

Nothing here touches a factor formula, a strategy's logic, or which
candidates are promoted. This is a data-correctness plumbing fix for
an already-verified (not newly-observed-and-reacted-to) mapping error
-- the same category of fix as ADR-0048/ADR-0049's wiring bugs.

## Consequence: the just-reported raw IC results are provisional

The 63-symbol ingestion the user ran, and all 13 fundamentals-based
raw IC checks run against it (`asset_growth`, `piotroski`,
`shareholder_yield`, `sloan_accruals`, `dividend_growth`,
`earnings_yield`, `quality_minus_junk`, `value_composite`, `size`,
`gross_profitability`, `altman_z`, `book_to_market`, `sales_yield`,
`cashflow_yield`), used a `data/fundamentals_data` catalog where XOM
has only 30 records under the wrong CIK -- almost entirely missing
correct data for one symbol out of 63, plus (unlike a clean "missing
data" case) 30 real but *wrong-entity* records sitting in the catalog
under the `XOM` symbol, which the pipeline has no way to distinguish
from genuine Exxon Mobil data. These 13 results should be treated as
provisional, not used for any pool-admission decision, until re-run
against a corrected catalog (see PROJECT_STATUS.md's updated checklist).

The 6 price/volume-only signal IC checks (`long_term_reversal`,
`short_term_reversal`, `low_beta`, `illiquidity`,
`fifty_two_week_high`, `max_effect`, via
`compute_signal_ic_from_catalog.py --db-path ./data/real_2010_latest`)
never touch the fundamentals catalog at all -- they are unaffected and
their reported results stand as-is.

## Tests

3 new tests in `tests/data_infra/test_ingest_fundamentals_data_wiring.py`
(`TestKnownCikOverridesAppliedByDefault`): the dict exists with the
correct XOM entry, `cik_overrides` is seeded from it before argument
parsing, and the seed happens before (so can be overridden by) the
explicit `--cik-overrides` assignment. Same source-text/AST-only
discipline as every other test in this file (the script itself is
never imported or executed, since it makes real network calls).

Full suite: 2192 passed (up from 2189).

## What this does NOT do

- Does not re-run ingestion or IC checks itself -- still requires real
  network access only available in the user's own environment.
- Does not attempt to detect the same class of bug automatically for
  any other symbol -- ADR-0042's caveat that other symbols could have
  a less extreme version of this problem remains open and unaddressed.
- Does not change any factor score, split, or evaluation logic.
