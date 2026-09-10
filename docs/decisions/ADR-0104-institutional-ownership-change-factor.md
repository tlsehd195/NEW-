# ADR-0104: Institutional Ownership Change factor (SEC Form 13F)

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner raised this idea directly: most large-cap stock price
movement is widely believed to come from institutional investors, not
individual retail traders -- can this project track institutional
positioning directly, rather than only inferring it from price/volume?
("대부분 투자에서 주가를 움직이는건 개미들이 아니라 기관들이라 생각하는데
기관들에 움직임을 추적할 순 없을까?")

**Research**: SEC Rule 13f-1 requires every institutional investment
manager with >= $100M in qualifying AUM to publicly disclose its US
equity long holdings quarterly on Form 13F. This is a real, well-known,
academically-studied data source (Gompers & Metrick 2001, "Institutional
Investors and Equity Prices," QJE; Chen, Jegadeesh & Wermers 2000, "The
Value of Active Mutual Fund Management," JFQA; Yan & Zhang 2009,
"Institutional Investors and Equity Returns," RFS). Per the account
owner's own follow-up request ("깃허브나 온라인에서 별점 높은걸로 찾아서
봐봐" / "아니면 논문" -- find a well-known GitHub project or paper),
verified the standard Form 13F field semantics against a real
open-source parser (`dgunning/edgartools`, its own `thirteenf` module
comment confirming the canonical field set: Issuer/Class/Cusip/Value/
SharesPrnAmount/Ticker) and an independent web-search summary of SEC's
own published structured-data-set column names (NAMEOFISSUER, CUSIP,
VALUE, SSHPRNAMT, SSHPRNAMTTYPE, etc.) -- the two agree.

**Two real, stated limitations, not papered over** (mirrors the
short-interest/FINRA precedent, ADR-0099, exactly):

1. This sandboxed session's outbound network is confirmed blocked to
   both `www.sec.gov` and `data.sec.gov` (re-verified this session),
   so SEC's real Form 13F structured data set has never been observed
   byte-for-byte here -- only secondary descriptions.
2. Even with access, that data set is keyed by CUSIP -- an identifier
   this project's `SecurityMaster` has never carried, and no verified
   CUSIP-to-`security_id` mapping exists. This is a genuinely NEW kind
   of gap: every other real-data integration this session (Form 4,
   fundamentals, short interest) is already keyed by CIK or
   `security_id` directly.

Guessing either the byte-level file format or a CUSIP mapping would
violate this project's "never fabricate provider capabilities"
discipline. Following the exact precedent `LocalFileDataProvider`/
`short_interest_file_import.py` already established, this project
instead defines its OWN simple, explicit, project-owned CSV schema and
defers the real acquisition/CUSIP-resolution/aggregation work to the
account owner's own environment (which has real `sec.gov` access and
already knows each of its own universe securities' identity).

## Decision

**Data model**: `InstitutionalHoldingRecord`
(`data_infra.institutional_holding_models`) -- one security's AGGREGATE
reported Form 13F position for one calendar quarter, summed across
every 13F filer that reported a position in it that quarter (`security_id`,
`quarter_end`, `institutional_shares`, `num_institutions`,
`available_time`, `ingestion_time`, `provenance`). `available_time` is
SEC Rule 13f-1's own hard 45-calendar-day filing deadline after each
quarter's end -- a real regulatory deadline, not an estimated
dissemination schedule the way FINRA's short-interest lag is.

**Storage**: `institutional_holding_records` DuckDB table +
`DuckDBInstitutionalHoldingRepository`, mirroring
`DuckDBShortInterestRepository`'s exact shape (idempotent insert on
natural key, `available_time <= as_of_time` point-in-time guard on
every read).

**Local CSV import** (no network call, ever):
`data_infra.providers.institutional_holding_file_import` -- one CSV per
`security_id` (`quarter_end,institutional_shares,num_institutions`),
`scripts/ingest_institutional_holdings.py` CLI. The account owner's own
workflow: fetch SEC's real Form 13F structured data set (own network
access), resolve each universe security's CUSIP, sum `SSHPRNAMT` across
every filer reporting a position in it that quarter, write one row per
quarter into this schema.

**Factor: `institutional_ownership_change_score`** (Chen, Jegadeesh &
Wermers 2000): the RAW log change in aggregate institutional shares
held between the two most recent known quarters,
`ln(current_quarter_shares / prior_quarter_shares)` -- structurally the
same `_fy_records`-based YoY log-change shape `net_stock_issuance_score`
already uses, applied to institutional 13F holdings across quarters
instead of total shares outstanding across fiscal years. NOT negated:
the hypothesized relation is that institutions increasing their
aggregate position ("smart money" buying) predicts HIGHER subsequent
returns. `None` (never fabricated) unless at least two distinct
quarters are known, or the prior quarter's aggregate shares are
non-positive.

**Wired in before any real result exists (RULE 0.8)**: a FIFTH/SIXTH
distinct DuckDB catalog (`--institutional-db-path`) in both
`compute_fundamentals_ic_from_catalog.py` (`--score
institutional_ownership_change`) and `run_long_horizon_validation.py`
(`_INSTITUTIONAL_FACTOR_CANDIDATES`, the pool's 44th candidate),
mirroring `_SHORT_INTEREST_SCORES`/`_SHORT_INTEREST_FACTOR_CANDIDATES`'s
exact single-repository reuse pattern (same `(security_id, as_of_time,
repository)` call shape, no new plumbing needed in `signal_ic.py`).

## What this does NOT do

Does not parse SEC's real Form 13F structured data set or XML directly
-- see the two stated limitations above. Does not build or guess a
CUSIP-to-`security_id` mapping. Does not attempt a LEVEL-based
institutional-ownership factor (Gompers & Metrick 2001's own primary
construction, `institutional_shares / shares_outstanding`) -- that
would need a second repository (fundamentals, for
`CommonStockSharesOutstanding`) and a new two-repository CLI wiring
shape this module does not otherwise need for a single-repository
candidate; the CHANGE-based construction chosen here needs only the one
new repository, the same engineering-simplification tradeoff
`short_interest_score`'s own docstring already made for `days_to_cover`
over a shares-outstanding-scaled ratio.

## Tests

`tests/data_infra/test_institutional_holding_models.py` (10 tests),
`tests/storage/test_institutional_holding_repository.py` (13 tests),
`tests/data_infra/test_institutional_holding_file_import.py` (9 tests),
`tests/data_infra/test_ingest_institutional_holdings_cli.py` (3 tests),
`tests/strategy_research/test_institutional_ownership_change_score.py`
(7 tests) -- 42 new tests total.
`test_run_long_horizon_validation_factor_wiring.py`'s `_EXPECTED_NAMES`
extended to 36 names across 7 candidate tables. Full suite re-run:
2675 passed (2633 pre-existing + 42 new).
