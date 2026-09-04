# ADR-0066: AVB sector/exchange resolved (real re-run with CIK override)

**Status:** Accepted
**Session:** 36

## Context

ADR-0058/ADR-0059 fetched real SEC EDGAR sector/exchange data for 86
of `RESEARCH_UNIVERSE_STAGE4`'s 87 symbols; `AVB`'s ticker-map CIK
lookup did not resolve on that run and was left honestly `None`. The
user had already found AVB's real CIK (`0000915912`) for an earlier
fundamentals-ingestion gap, and this session re-ran
`scripts/fetch_sector_classifications.py --symbols AVB --cik-overrides
AVB:0000915912 ...` for real, getting:

```
sector='Real Estate Investment Trusts' exchange='NYSE'
```

## Decision

Added `"AVB": ("Real Estate Investment Trusts", "NYSE")` to
`_REAL_SEC_SECTOR_AND_EXCHANGE` in `src/data_infra/universe.py`. All
87 `RESEARCH_UNIVERSE_STAGE4` symbols now carry real, provider-
confirmed `sector`/`exchange`. Module docstrings and inline comments
that previously described AVB as "still unresolved" updated to reflect
the real outcome, not left stale.

## Tests

3 existing tests updated (not weakened) in `tests/data_infra/
test_universe.py::TestRealSymbolMetadata` -- two tests that used AVB as
their "unresolved" example now use a genuinely-never-fetched symbol
and MSFT (real sector, but left-censored in the S&P 500 PIT dataset so
no `listed_from`) instead; a third renamed to assert AVB's real,
resolved values directly. Full suite: 2297 passed (unchanged from
ADR-0065's own final count -- no new tests added, only real data
substituted for a previously-honest `None`).
