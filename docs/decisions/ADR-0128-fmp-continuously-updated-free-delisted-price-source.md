# ADR-0128: Financial Modeling Prep — A Second, Continuously-Updated Free Delisted-Price Source (Covering the Post-2018 Window)

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0126-quandl-wiki-prices-free-delisted-price-source.md`,
`docs/decisions/ADR-0127-post-2018-delisted-price-data-still-blocked.md`

---

## Context

`ADR-0127` concluded Yahoo Finance and Stooq were both empirically
rejected as free sources for tickers delisted after WIKI Prices'
2018-03-27 freeze (`ADR-0126`). Continuing the search, `Financial
Modeling Prep` (FMP) turned up two real, free-tier, API-key-based
endpoints (no anti-bot browser gate, unlike Stooq/Macrotrends -- both
of which were also tried this round and rejected for the same
Cloudflare/proof-of-work reasons as `ADR-0127`):

- `stable/delisted-companies` -- a list of recently delisted companies.
- `stable/historical-price-eod/full?symbol=...` -- real EOD OHLCV.

## Decision 1 -- Empirically verify real coverage, not just documentation, before trusting it

The account owner tested both endpoints directly with a real, free
API key. Real, observed results (not guessed from FMP's docs):

- `delisted-companies` (legacy `v3` version): **`404`-equivalent
  `Error Message` -- legacy endpoints were retired 2025-08-31.** The
  current path is under `stable/`.
- `stable/delisted-companies?page=0`: real, current data (entries dated
  as recently as 2026-09-09/2026-12-30 -- this list is continuously
  updated, unlike WIKI Prices' 2018 freeze). **`page` is capped at `0`
  on the free plan** (`HTTP 402 Payment Required` for `page=1`) --
  confirmed real, not guessed -- so the free tier can only see the
  ~100 MOST RECENT delistings this way, not the full historical list.
- `stable/historical-price-eod/full?symbol=ATVI` (Activision Blizzard,
  acquired by Microsoft, delisted 2023-10-18): **real price data
  returned.** Real last trade **2023-10-12, close $94.42, volume
  7,323,451** -- Microsoft's acquisition closed **2023-10-13**, one day
  later, an even tighter match than `DELL`'s own confirming evidence in
  `ADR-0126`. Rows after that are an IDENTICAL `open=high=low=close=
  94.42, volume=0` flat-fill -- the exact same dummy-tail artifact
  `ADR-0126` found in WIKI Prices, confirmed independently in a second,
  unrelated data source.
- Without explicit `from`/`to` params, the endpoint defaults to
  roughly the last 5 years from TODAY's date (not from the ticker's own
  history) -- confirmed by the returned window starting almost exactly
  5 years before the request date (2026), not near the company's real
  founding. Passing `from=1990-01-01&to=2023-10-20` returned **5,000
  rows, real data 2003-12-10 through 2023-10-20** -- ~20 years of
  history, evidently truncated at a fixed row cap (5,000) rather than
  the ticker's true full history, but still far more than what
  `ADR-0126`'s window (frozen at 2018) alone can offer for this ticker.
- Free plan: 250 requests/day, 500MB/30-day rolling bandwidth cap
  (confirmed via FMP's own current FAQ).

## Decision 2 -- Don't rely on FMP's own delisted-companies list; reuse this project's own S&P 500 removal data instead

Because `page` is capped at `0` on the free plan (Decision 1), FMP's
own list endpoint cannot enumerate the full historical population of
delisted tickers for free. This is not actually a blocker: this
project already has a real, comprehensive candidate list for exactly
this purpose -- `data/sp500_ticker_start_end.csv` (`fja05680/sp500`,
`ADR-0120`), the same source `ADR-0126`'s bulk coverage check used.
`scripts/fetch_fmp_delisted_prices.py` (new) takes `--since` (intended
as `2018-03-28`, the day after WIKI Prices' own freeze) and checks
every S&P 500 ticker with a real `end_date` on/after that date -- 195
such tickers, per this session's own earlier count -- directly against
FMP's `historical-price-eod/full` endpoint, one real HTTP request per
candidate (well under the 250/day budget).

## Decision 3 -- Classify genuine delisting the same way `ADR-0126` Decision 5 does, for consistency across sources

FMP's dummy-tail artifact (Decision 1) is filtered by the identical
`volume == 0` rule `ADR-0126` established, and the same "is the real
data's last date within 90 days of a real S&P 500 removal date"
heuristic (`ADR-0126` Decision 5) classifies genuine delistings vs.
tickers that simply left the index and kept trading -- implemented in
`data_infra.providers.fmp_delisted_price_import.is_likely_genuine_
delisting`, sharing its exact threshold and semantics with `check_wiki_
prices_delisted_coverage.py`'s own function so the two sources'
results are directly comparable, never silently using a different bar
for one source than the other.

## Decision 4 -- No adjusted-price columns; reuse the existing `LocalFileDataProvider` schema unmodified

FMP's response has no split-adjusted price fields at all (`vwap`/
`change`/`changePercent` instead, none of which is a split-adjusted
price) -- `to_file_import_row` leaves `adj_close`/`adj_high`/`adj_low`
blank, never fabricating them from `vwap`, the same "never mislabel a
different metric as an optional field" discipline `ADR-0125` applied
to FINRA's `averageShortShareNumber`. As with `ADR-0126`, no changes
were needed to `data_infra/providers/file_import.py` or `scripts/
import_external_market_data.py` -- both already support this exact
per-symbol CSV shape.

## Decision 5 -- Real bulk result: FMP's free tier gates historical price by a PER-SYMBOL whitelist, not by request count

The account owner ran `scripts/fetch_fmp_delisted_prices.py` for real
against all 191 checkable post-2018 candidates (191, not 195 -- a
handful of the originally-counted 195 tickers turned out to be
duplicate intervals for tickers that re-entered and re-left the
index). Real result: **184 of 191 requests failed with `HTTP 402`.**

Investigated rather than assumed: fetching one of the failing tickers
(`AGN`) directly returned the real error body **`"Premium Query
Parameter: 'Special Endpoint': This value set for 'symbol' is not
available under your current subscription"`** -- this is NOT a
request-count/rate-limit rejection (the 250/day budget was nowhere
close to exhausted; successes and failures are interleaved throughout
the run, not clustered at the end). **FMP's free tier restricts
`historical-price-eod/full` to a specific, undocumented whitelist of
symbols** -- most likely a small set of well-known large-cap tickers
kept free for onboarding/demo purposes -- unrelated to whether a
symbol is delisted. This materially corrects Decision 1's implicit
assumption (that any symbol could be queried, subject only to the
daily request budget) with real evidence.

Of the 191 candidates, only **7 happened to be on that free
whitelist**: `AAL`, `ATVI`, `ETSY`, `MRO`, `TWTR`, `VIAC`, `WBA`. Of
those 7, **5 classify `likely_genuine_delisting`** (`ATVI`, `MRO`,
`TWTR`, `VIAC`, `WBA`); `AAL` and `ETSY` correctly classify as
still-trading-after-index-removal (both are real, currently-listed
companies that simply left the S&P 500 -- a correct negative,
confirming the classifier works as designed on real data, not only on
the positive `DELL`/`ATVI` cases). The remaining 184 candidates'
TRUE FMP coverage is **unknown, not confirmed absent** -- the paywall
blocked the check itself, unlike `ADR-0126`'s WIKI Prices check where
absence was directly observed.

## Decision 6 -- Real ingestion of the 5 confirmed genuine tickers, merged into the same DuckDB catalog as `ADR-0126`

The account owner converted and ingested all 5 (`ATVI`, `MRO`, `TWTR`,
`VIAC`, `WBA`) into the SAME DuckDB catalog `ADR-0126` Decision 6
already populated (`--db-path ./data/wiki_prices_delisted_db`,
`--source-name fmp_free_tier` to keep `Provenance.source` honestly
distinct from `quandl_wiki_prices_kaggle_mirror`). Real result:
**`Ingestion status: SUCCESS`, 17,807 bars persisted, 0 missing
symbols, real data spanning 2003-12-10 to 2025-08-27** (`WBA`'s real
last trade, only weeks before this ADR's date -- the most recent real
delisted-ticker data this project has ever persisted).
`DataQualityFramework` reported `PASSED_WITH_WARNINGS` (11 issues, 0
`ERROR`) -- triaged the same way as `ADR-0126` Decision 6: all 6
`missing_timestamp_gaps` land on the identical real market-holiday
dates already explained there (2006-12-29/2007-01-03 New Year's +
President Ford's state funeral, 2012-10-26/10-31 Hurricane Sandy), and
all 5 `stale_data` warnings are the same structurally-expected
"delisted ticker's real last observation predates the `--end`
checkpoint" pattern. **Zero real problems, identical to `ADR-0126`.**

Combined running total across both free sources: **59 genuinely
delisted tickers with real, verified price data** (54 from WIKI Prices,
1962-2018; 5 from FMP, spanning into 2025), all in one DuckDB catalog.

## Consequences

### Positive

- A second, real, free, **continuously-updated** source for delisted-
  ticker prices -- unlike `ADR-0126`'s WIKI Prices (frozen 2018-03-27),
  this source can in principle cover delistings up to and including
  the present day, closing exactly the gap `ADR-0127` left open.
- Confirmed via two independent real corporate events now (`DELL`'s
  2013-10-29 LBO close in `ADR-0126`, and `ATVI`'s 2023-10-13
  Microsoft acquisition close here) that the "real data ends within
  days of the real delisting event" signature reliably distinguishes
  genuine free-tier delisted-ticker coverage from a currently-listed-
  tickers-only snapshot -- this project's empirical test methodology
  (established rejecting `pystock-data` and the Kaggle "Huge Stock
  Market Dataset" mirror) generalizes cleanly to a new source.
- Reuses this project's own already-real S&P 500 removal data
  (`ADR-0120`) as the candidate list, avoiding the free tier's `page`
  cap on FMP's own delisted-companies endpoint entirely.

### Negative / Trade-offs

- **The dominant limitation, discovered only by running for real
  (Decision 5): FMP's free tier gates `historical-price-eod/full` by
  an undocumented PER-SYMBOL whitelist, not merely a request-count
  budget.** Only 7 of 191 checked candidates (3.7%) were even queryable
  at all; the other 184 returned `HTTP 402` with an explicit "this
  symbol is not available under your current subscription" message.
  This is a far more restrictive real-world ceiling than Decision 1's
  evidence (a single successful `ATVI` call) suggested -- recorded
  here precisely so a future session does not assume FMP's free tier
  can be pointed at an arbitrary ticker list.
- **Net yield: 5 genuinely new delisted tickers** (`ATVI`, `MRO`,
  `TWTR`, `VIAC`, `WBA`) out of 191 real candidates checked -- a small
  but real, free, and continuously-fresh (`WBA`'s data reaches
  2025-08-27) addition on top of `ADR-0126`'s 54, not a general
  solution to the post-2018 gap `ADR-0127` identified. The other 184
  candidates' true FMP coverage remains genuinely **unknown** (blocked,
  not confirmed absent) -- a materially different, more honest status
  than "not covered."
- **Coverage is still bounded to S&P 500 constituents that later left
  the index**, exactly like `ADR-0126`'s own candidate set -- a
  delisted ticker that was never an S&P 500 member is not checked by
  this script either. A more exhaustive search would need a broader
  candidate list this project does not currently have.
- **History per ticker is capped (observed 5,000 rows without an
  explicit narrower `from`/`to`), not necessarily a company's true full
  history** -- acceptable for this project's purposes (which need
  prices up to and through the delisting event, not necessarily the
  company's entire multi-decade history), but disclosed here rather
  than assumed unlimited.
- The account owner's real FMP API key was pasted into this
  conversation multiple times while testing. It is a free-tier,
  read-only-scoped key (no write/billing capability), so the practical
  risk is low, but as with the FINRA OAuth token earlier this session
  (`ADR-0125`'s related conversation), rotating it via FMP's dashboard
  is a reasonable precaution -- this session never stored or reused
  the key itself beyond relaying it back in example commands.

## Tests

13 new tests (`tests/data_infra/test_fmp_delisted_price_import.py`),
using fixture rows shaped exactly like the real ATVI response the
account owner fetched this session (real values, not invented).
`scripts/fetch_fmp_delisted_prices.py` itself makes real network
calls and is therefore not exercised by the automated test suite,
matching `fetch_sp500_index_history.py`'s own precedent -- its
argument parsing and no-API-key fail-closed path were manually
verified this session (`--help` output, and confirmed `FATAL: no API
key given` with a nonzero exit when no key is supplied).

## Status of Implementation at Time of This ADR

`src/data_infra/providers/fmp_delisted_price_import.py` (new, pure, no
network) and `scripts/fetch_fmp_delisted_prices.py` (new, real network
calls, never test-suite-executed). No changes to `data_infra/providers/
file_import.py` or `scripts/import_external_market_data.py`.

Real bulk result (account owner's own environment, this session): 191
post-2018 S&P 500 removal candidates checked against FMP; 7 covered
(free-tier symbol whitelist, not a coverage measurement -- see Decision
5), 5 classified `likely_genuine_delisting` (`ATVI`, `MRO`, `TWTR`,
`VIAC`, `WBA`). Those 5 were converted and ingested for real into the
same DuckDB catalog `ADR-0126` populated: `Ingestion status: SUCCESS`,
17,807 bars persisted, real data through 2025-08-27,
`DataQualityFramework` status `PASSED_WITH_WARNINGS` (11 issues, 0
`ERROR`, all triaged as expected/benign per Decision 6). Combined with
`ADR-0126`, this project now holds real, verified price data for **59
genuinely delisted securities** across both free sources.
