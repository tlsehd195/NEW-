# ADR-0100: Net Stock Issuance and Net Operating Assets factors

**Status:** Accepted
**Session:** 36 (continued)

## Context

Following completion of the 4-candidate batch from ADR-0098/ADR-0099,
the user asked to keep searching for more similar projects ("다른
프로젝트 더 찾아봐"). That search surfaced `bkelly-lab/ReplicationCrisis`
-- the official code/data repository for Jensen, Kelly & Pedersen
(2023), "Is There a Replication Crisis in Finance?," published in The
Journal of Finance -- the single highest-quality academic source found
this session (a top-tier peer-reviewed journal, not a blog aggregator),
clustering 153 characteristics into 13 themes across 93 countries.

**A real, stated limitation, not papered over**: that repository's own
exact factor constructions live in SAS scripts and a binary spreadsheet
(`Factor Details.xlsx`), and its supporting documentation is hosted at
`jkpfactors.com`/`nber.org` -- both blocked from this sandboxed
session's outbound network (confirmed this session, alongside the
already-known `finra.org` block from ADR-0099). Guessing that
repository's own exact formula would violate this project's "never
fabricate provider capabilities/formulas" discipline. Two of its 13
themes ("Net Issuance"/"debt issuance" and "Investment") map cleanly
onto two older, independently well-documented individual papers whose
own constructions are directly verifiable through multiple accessible
sources without needing that specific blocked repository at all -- this
ADR builds those two, from their own original papers, rather than from
JKP's aggregation of them.

## Decision

**`net_stock_issuance_score`** (Pontiff & Woodgate 2008, "Share
Issuance and Cross-Sectional Returns," The Journal of Finance 63(2);
Fama & French 2008, "Dissecting Anomalies," The Journal of Finance
63(4)): the change in LOG split-adjusted shares outstanding across the
two most recent fiscal years (Fama & French's own standard operational
definition), using `CommonStockSharesOutstanding` -- a concept already
ingested for `shareholder_yield_score`/`book_to_market_score`, needing
**zero new data**. Score is the NEGATIVE of the log change (net
buybacks score higher, net issuance scores lower). Structurally
identical to `asset_growth_score`/`dividend_growth_score`'s own
`_fy_records`-based year-over-year shape.

**`net_operating_assets_score`** (Hirshleifer, Hou, Teoh & Zhang 2004,
"Do Investors Overvalue Firms With Bloated Balance Sheets?," Journal of
Accounting and Economics 38): `NOA = Operating Assets - Operating
Liabilities`, scaled by the PRIOR fiscal year's Total Assets. Computed
as the algebraically equivalent `(StockholdersEquity - Cash +
LongTermDebtNoncurrent) / prior_fy_Assets` via the balance-sheet
identity `Assets - Liabilities == StockholdersEquity`. Two documented
simplifications of the original paper's fuller 5/6-line-item
construction: (1) "interest-bearing debt" uses only
`LongTermDebtNoncurrent` (already ingested), never a separate
short-term-debt concept this project does not have -- the same
simplification `leverage_score` already makes with total `Liabilities`;
(2) minority interest and preferred stock are omitted entirely rather
than approximated, since most of this project's large-cap non-financial
universe carries neither in material size (the same omission
`piotroski_f_score`/`leverage_score` already make). Score is the
NEGATIVE of the NOA ratio. Needs **one new XBRL concept**,
`CashAndCashEquivalentsAtCarryingValue`, added to
`ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS` (zero additional
real network requests, the same pattern every prior concept addition
here already established).

**Both wired in before any real result exists (RULE 0.8)**: into
`compute_fundamentals_ic_from_catalog.py`'s `_SCORES` dict (both are
fundamentals-only, single-repository, needing no new CLI flag) and
`run_long_horizon_validation.py`'s `_FUNDAMENTALS_FACTOR_CANDIDATES`.

## What this does NOT do

Does not build anything from `bkelly-lab/ReplicationCrisis`'s own SAS
code or exact factor specifications -- see the data-source limitation
above. Does not implement any of that repository's other 11 themes
(value, low risk, short-term reversal, seasonality, accruals, profit
growth, profitability, quality, momentum, low leverage, size) as new
factors -- this project's ~35 already-implemented factors already cover
those themes via their own, independently-verified constructions,
reviewed during this same search round and found to be genuinely
redundant rather than novel. Does not approximate minority interest or
preferred stock for `net_operating_assets_score` -- see the documented
simplification above.

## Tests

`tests/strategy_research/test_factor_scores.py::TestNetStockIssuanceScore`
(5 tests) and `::TestNetOperatingAssetsScore` (7 tests).
`test_run_long_horizon_validation_factor_wiring.py`'s `_EXPECTED_NAMES`
extended to 31 names across 6 candidate tables. Full suite re-run: 2601
tests pass (up from 2589 after ADR-0099).
