# ADR-0123: Deep Search for Delisted-Ticker Price Data — Still No Viable Source

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0122-avb-real-delisting-and-left-censoring-query.md`,
`docs/decisions/ADR-0033-real-historical-us-equity-data-source-decision-tree.md`,
`docs/decisions/ADR-0034-real-data-acquisition-strategy.md`

---

## Context

`ADR-0122`'s Decision 1 concluded item 1 (real historical price data for
delisted securities) was "still `ENVIRONMENT_BLOCKED`, no new
alternative found" after a brief check. The user asked for a deeper
search specifically on this item. This ADR documents that deeper
search, including one candidate that was actually downloaded and
empirically tested against real data (not just read about), and is
worth a dedicated record because the earlier, briefer conclusion in
ADR-0122 did not yet reflect this depth of evidence.

## Decision 1 -- Network re-verification, widened

Re-tested outbound HTTPS reachability to a much wider set of hosts
this pass, beyond `ADR-0034`'s original list: `query1.finance.yahoo.com`,
`query2.finance.yahoo.com`, `finance.yahoo.com`, `eodhistoricaldata.com`,
`api.marketstack.com`, `cloud.iexapis.com`, `api.twelvedata.com`,
`data.alpaca.markets`, `macrotrends.net`, `wsj.com`, `kaggle.com` --
**every single one** returns `connect_rejected` through this sandbox's
egress proxy, identically to the commercial providers already tested.
Only GitHub-family hosts (`github.com`, `raw.githubusercontent.com`,
`objects.githubusercontent.com`) and `pypi.org` (per `ADR-0034`) are
reachable. This confirms the earlier finding is not an artifact of
which specific vendors were tried -- this environment's egress is a
strict allowlist of a handful of hosts, GitHub included, everything
resembling a market-data API excluded.

## Decision 2 -- `JeniGal/Quandl-API-Coding-Test`'s `WIKI-PRICES.csv`: rejected, too small to matter

Found via search and directly fetched (`raw.githubusercontent.com` is
reachable). Real, downloadable, but a 19KB coding-test fixture: 4
tickers, a narrow 2017 date window. Not usable at any scale.

## Decision 3 -- `eliangcs/pystock-data`: downloaded and empirically tested; rejected with concrete evidence

This was the most promising candidate found: a real, git-committed
(not paid, not LFS-gated) daily crawl of NASDAQ-listed tickers' prices
from Yahoo Finance, running 2009-01-01 through frozen at 2017-03-31
(unmaintained since). Its own README describes exactly the mechanism
that would matter here: each day's archive crawls whatever tickers
`NASDAQ.com` listed AS OF THAT DAY -- in principle, a genuine
point-in-time snapshot mechanism, the same shape that made
`hanshof/sp500_constituents`/`fja05680/sp500` (ADR-0037/ADR-0120)
actually useful for this project's survivorship-bias problem.

Downloaded and inspected the real "initial" backfill archive
(`2015/0001_initial.tar.gz`, 42MB, genuinely fetched over HTTPS, not a
placeholder): 2,584,866 price rows, 1,980 distinct symbols, real dates
2009-01-02 through 2015-03-20.

**Empirically tested the actual hypothesis, not just read the README**:
searched this archive for `DELL` -- Dell Inc. (NASDAQ: `DELL`) went
private via a well-documented leveraged buyout that completed October
2013, delisting from NASDAQ. **Zero rows found; the ticker is entirely
absent from `symbols.txt` and `prices.csv`.** This directly disproves
the hopeful reading of the README: this "initial" batch is a March
2015 snapshot of *then-currently-listed* NASDAQ tickers, backfilled to
2009 -- exactly the same "today's survivors projected backward" bias
every other candidate this project has evaluated already has, just
anchored to a 2015 vantage point instead of a 2026 one. A name that
delisted before the crawl's own start date is not recoverable from it
at all.

The only theoretical residual value is narrower than the README
suggests: a ticker that delisted DURING the daily-incremental-update
era (roughly 2015-03-23 through 2017-03-31, ~2 years) would have real
price history up through its last trading day in whichever daily
archive last included it, even though later archives' `symbols.txt`
would drop it. Extracting that would require downloading and parsing
potentially hundreds of individual daily `.tar.gz` archives (this
project has no visibility into exactly how many exist or their naming
scheme beyond the `README`'s description) to reconstruct a real
point-in-time symbol history the same way `sp500_pit_membership.py`
reconstructs S&P 500 membership from sparse snapshots -- for a payoff
that is (a) NASDAQ-only, excluding NYSE-listed names entirely, (b)
frozen at March 2017, 9+ years stale relative to today, and (c) only
genuinely covers delistings within that narrow ~2-year window, not the
2009-2015 bulk of the archive. **Rejected**: the engineering cost of
building a new provider/ingestion path to reconstruct that narrow
window does not clear the bar set by how little it would actually
unblock -- this project's real need is continuous 2010-2026 coverage,
and this candidate cannot supply the 2017-2026 majority of that window
under any interpretation of its data.

## Decision 4 -- No further candidates pursued

`FirstRateData`/`EODHD`'s dedicated delisted-ticker products (found via
search, ~7,000-11,000 tickers, real coverage) are paid commercial
services with no free tier for this use case, and their hosts are
`connect_rejected` in this environment regardless (Decision 1) --
consistent with `ADR-0033`'s own classification of every such option as
requiring a licensing decision this session cannot make unilaterally.

## Consequences

- `ADR-0033`/`ADR-0034`'s conclusion is now backed by a materially
  deeper search, including one candidate actually downloaded and
  empirically disproven with a concrete, named test case (`DELL`),
  rather than only desk research from documentation. The conclusion
  itself is unchanged: CRSP/WRDS remains the only `REALISTIC`,
  survivorship-aware source, and it requires an institutional
  subscription this project has no path to acquire autonomously.
- No code changes result from this ADR -- a pure, documented research
  outcome, matching this project's practice of recording a thorough
  "still blocked" finding rather than silently repeating the same
  brief conclusion each time it is asked.

## Status of Implementation at Time of This ADR

No code changed. All temporary files from this investigation (the
downloaded `pystock-data` archive and its extracted contents, and the
`JeniGal` sample CSV) were deleted after inspection -- nothing from
this search was persisted to the repository.
