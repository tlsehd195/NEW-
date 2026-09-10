# ADR-0101: Operating Leverage and Abnormal Corporate Investment factors

**Status:** Accepted
**Session:** 36 (continued)

## Context

After ADR-0100's amendment resolved the original data-source limitation
for `net_operating_assets_score` (the account owner supplied
`bkelly-lab/jkp-data`'s "Global Factor Data Documentation" PDF, extracted
via `pdftotext` into a 7332-line local text file), the user explicitly
instructed continuing to mine that same document for further new factor
candidates ("2번 진행해" -- "proceed with option 2," from a two-item list
this session offered: (1) send the still-outstanding Codespace validation
results whenever convenient, (2) keep mining the JKP documentation).

Unlike `net_stock_issuance_score`/`net_operating_assets_score` (built from
the original underlying papers because JKP's own aggregated formula could
not be verified at the time), this document itself is now the verified
source -- so factors below are wired directly from JKP's own construction,
each traceable to a SINGLE, well-cited underlying paper (not JKP's own
aggregation across many papers), the same standard this project's other
~39 factors already hold themselves to.

Two candidates were selected from the document's ~150-factor catalogue
for this round, both fundamentals-only, both needing exactly one new
XBRL concept, both requiring no data this project cannot already fetch
from `SecEdgarFundamentalsProvider`:

## Decision

**`operating_leverage_score`** (Novy-Marx 2011, "Operating Leverage,"
Review of Finance 15(1): 103-134): `opex_at = OPEX*_t / AT*_t`, where
`OPEX* = COGS + XSGA` (JKP's own documented fallback for its preferred
`XOPR` tag, which this project has never ingested). Needs one new XBRL
concept, `SellingGeneralAndAdministrativeExpense` --
`CostOfGoodsAndServicesSold`/`Assets` are already ingested.

**This factor's sign convention is deliberately the OPPOSITE of every
other "risk" factor already in this module.** Novy-Marx's own central
finding is a POSITIVE risk-return relation: firms with more fixed-cost
intensity bear more operating risk and are compensated with higher
expected returns. `leverage_score` (financial leverage) is negated
because more debt there reflects lower quality, not a priced risk
premium -- `operating_leverage_score` is the RAW ratio, decided from the
paper's own stated finding before any result exists for this factor,
not inferred from wanting a particular sign.

**`abnormal_investment_score`** (Titman, Wei & Xie 2004, "Capital
Investments and Stock Returns," Journal of Financial and Quantitative
Analysis 39(4): 677-700): `capex_abn_t = CAPX_SALE_t / avg(CAPX_SALE
3 prior periods) - 1`, where `CAPX_SALE = CAPX / SALE*`. JKP samples this
monthly (`t-12/t-24/t-36`); this project substitutes the 3 fiscal years
immediately prior to the current one, the same monthly-to-FY
substitution this module already makes throughout (e.g.
`residual_momentum_score`, `sue_score`). Needs one new XBRL concept,
`PaymentsToAcquirePropertyPlantAndEquipment` (CAPX) -- `Revenues`
(SALE*) is already ingested. Score is the NEGATIVE of `capex_abn`
(overinvestment predicts lower subsequent returns per the paper).

**Both wired in before any real result exists (RULE 0.8)**: into
`ingest_fundamentals_data.py`'s `_DEFAULT_CONCEPTS` (2 new concepts,
zero additional real network requests -- `SecEdgarFundamentalsProvider.
fetch_company_facts` already fetches one company's entire company-facts
JSON per request regardless of concept count), `compute_fundamentals_ic_
from_catalog.py`'s `_SCORES` dict (`--score operating_leverage` /
`--score abnormal_investment`), and `run_long_horizon_validation.py`'s
`_FUNDAMENTALS_FACTOR_CANDIDATES` (the pool's 40th and 41st candidates).

## What this does NOT do

Does not implement `age` ("Firm age"), which the same document's own
construction is "age of the firm in months" -- a DATA-AVAILABILITY
measure specific to JKP's own database coverage window, not a
citable formula this project's own SEC EDGAR ingestion (with no clean
IPO-date/first-CRSP-date equivalent) could faithfully replicate. Does
not implement the document's many "growth in X scaled by AT" mechanical
transformations (e.g. `debt_gr3`, `fnl_gr1a`, `ncol_gr1a`, `oa_gr1a`) --
these are JKP's own systematic transformation methodology applied
uniformly across balance-sheet line items, not each individually a
distinct academic finding with its own citation, unlike every other
factor in this module. Does not implement the `dsale_dinv`/`dsale_drec`/
`dsale_dsga`/`dgp_dsale` Abarbanell & Bushee (1998)-style "Profit Growth"
family -- deferred, not rejected, pending closer reading of that paper's
own construction (not yet done this round).

## Tests

`tests/strategy_research/test_factor_scores.py::TestOperatingLeverageScore`
(6 tests) and `::TestAbnormalInvestmentScore` (6 tests).
`test_run_long_horizon_validation_factor_wiring.py`'s `_EXPECTED_NAMES`
extended to 33 names across 6 candidate tables. Full suite re-run: see
`PROJECT_STATUS.md` for the exact count.
