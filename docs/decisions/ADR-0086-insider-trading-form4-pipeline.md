# ADR-0086: Insider trading (SEC Form 4) data pipeline + insider_buying_score, wired blind before any real result

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0084 covered the first of two research directions the account
owner asked to pursue in the same instruction: (1) Standardized
Unexpected Earnings (done, ADR-0084 -- real raw IC came back weak,
walk-forward result `ROBUSTNESS_PENDING`), and (2) insider trading
signals (SEC Form 4), deferred at the time pending a data-feasibility
check. This ADR covers (2).

A feasibility check was run manually by the account owner in their own
environment (this session's own network is blocked from `sec.gov`,
same long-standing constraint every earlier EDGAR-dependent ADR
documents): real EDGAR Atom-feed, `index.json`, and `form4.xml`
responses were fetched successfully for a real AAPL filing (accession
`0001140361-26-035636`). Reading that real sample surfaced a concrete
methodology requirement, not assumed in advance: the filing turned out
to be a Rule 10b5-1 pre-scheduled sale (`aff10b5One: true`), not a
genuinely discretionary trade -- see "Decision" below for why this
changes the factor's own definition.

## Decision

**Data model + storage** (`src/data_infra/insider_models.py`,
`src/storage/insider_repository.py`, `src/storage/schema.py`): a new
`InsiderTransaction` dataclass, parallel in structure to
`FundamentalRecord` -- same point-in-time discipline
(`available_time` = the real SEC filing date, never `transaction_date`,
enforced by an identical `__post_init__` ordering guard) and the same
idempotent-natural-key persistence pattern (`DuckDBInsiderRepository`,
`ON CONFLICT (provenance_source_record_id) DO NOTHING`) every other
repository in this project already uses. One new field beyond what
`FundamentalRecord` needs: `is_10b5_1_plan` (bool), directly motivated
by the real sample above.

**Provider** (`src/data_infra/providers/sec_edgar.py`): 5 new methods
on `SecEdgarFundamentalsProvider` -- `fetch_form4_filing_list` (Atom
feed), `fetch_form4_index`/`select_form4_primary_document`
(`index.json` + heuristic for picking the ownership-document XML out
of it), `fetch_form4_document` (raw XML), `normalize_form4_document`
(parses `nonDerivativeTable` only -- `derivativeTable` is a
structurally different signal, compensation mechanics rather than a
discretionary market trade, deliberately out of scope). Unlike every
other method in this class (Tier 2, documentation-only), these 5 are
Tier 1: verified this session against the real captured AAPL sample,
byte-for-byte, before being committed. Two real, directly-observed
facts baked into the code rather than assumed: the Form 4 Atom feed and
`Archives/edgar/data/...` paths live on `www.sec.gov`, not
`data.sec.gov`; that path's CIK is NOT zero-padded, unlike the XBRL
`companyfacts` path's CIK.

**Factor** (`strategy_research.factor_scores.insider_buying_score`):

```
NET_PURCHASE_RATIO = (buy_shares - sell_shares) / (buy_shares + sell_shares)
```

over the trailing 6 calendar months of `transaction_date`, counting
only transaction code `P` (open-market purchase) or `S` (open-market
sale) AND only `is_10b5_1_plan == False` -- Lakonishok & Lee 2001
("Are Insider Trades Informative?," Review of Financial Studies) /
Seyhun 1986 ("Insiders' profits, costs of trading, and market
efficiency," Journal of Financial Economics). Every other transaction
code (`A` grants, `M` option exercises, ...) and every 10b5-1-flagged
transaction is excluded for the same underlying reason: this
literature is specifically about discretionary trading conveying
private information, which compensation mechanics and pre-scheduled
plan trades structurally cannot. **This exclusion rule was decided
directly because of the real Form 4 sample this session captured**
(the AAPL sample was exactly this kind of transaction) -- stated here,
before any real IC result exists, per RULE 0.8, so this ADR cannot
later be read as having tuned the definition after seeing a result.

**Ingestion CLI** (`scripts/ingest_insider_transactions.py`): mirrors
`ingest_fundamentals_data.py`'s structure and per-symbol/per-filing
error-degradation discipline exactly, adapted for a single host
(`www.sec.gov`, unlike the fundamentals script's two hosts) and two
layers of granularity (a filing-list fetch failure degrades the whole
symbol; a single bad filing degrades only that filing).

**Wired blind, before any real result** (RULE 0.8, same discipline
ADR-0051/ADR-0053/ADR-0054/ADR-0084 already established): `--score
insider_buying` in `compute_fundamentals_ic_from_catalog.py` (via a new
`--insider-db-path` flag and `_INSIDER_SCORES` dict, since this score's
repository is a distinct catalog from `--fundamentals-db-path`), and
the walk-forward candidate pool in `run_long_horizon_validation.py`
(`_INSIDER_FACTOR_CANDIDATES`, gated on a new `--insider-db-path` flag
independent of `--fundamentals-db-path`). Both call paths reuse the
existing `compute_fundamentals_ic_series`/`_fundamentals_factor_factory`/
`FundamentalsFactorStrategy` plumbing unchanged -- `insider_buying_score`'s
signature is `(security_id, as_of_time, repository)`, identical in
shape to every fundamentals-only score, so no new IC-computation
function or Strategy class was needed, only a repository of a
different concrete type passed through the same generic `object`-typed
parameter.

## What this does NOT do

Does not run raw IC screening or walk-forward/PBO/DSR against real
data -- this session's own outbound network is blocked to SEC EDGAR.
The account owner needs to run `scripts/ingest_insider_transactions.py`
in an environment with real network access before `--score
insider_buying` can compute anything against real data. Does not
decide or predict whether `insider_buying_score` will match its
literature-predicted sign -- stated here, before that real run,
specifically so this ADR cannot later be read as having cherry-picked
the hypothesis after seeing a result. Does not parse `derivativeTable`
transactions (option exercises, RSU vesting) -- a deliberate scope
limit, not an oversight (see `normalize_form4_document`'s own
docstring). Does not touch the separate ML factor-combination task
("stronger regularization + more data") the account owner asked to
proceed with in the same instruction -- tracked and worked separately.

## Tests

All fixture-based, no real network calls, mirroring this project's
existing SEC EDGAR test discipline:

- `tests/data_infra/test_insider_models.py` (13 tests) --
  `InsiderTransaction` construction/validation, including the
  `available_time < transaction_date` point-in-time guard.
- `tests/storage/test_insider_repository.py` (12 tests) --
  persistence/restart, idempotency, the point-in-time look-ahead guard,
  and date-range filtering, mirroring `test_fundamentals_repository.py`.
- `tests/data_infra/test_sec_edgar_form4.py` (24 tests) -- all 5 new
  provider methods against a stub transport; `normalize_form4_document`
  verified against the actual real captured AAPL XML byte-for-byte
  (reporting owner, transaction fields, `is_10b5_1_plan`, `available_time`
  vs `transaction_date`), plus malformed/missing-field/derivative-table
  edge cases.
- `tests/strategy_research/test_insider_buying_score.py` (13 tests) --
  pure buying/selling/balanced ratios, `None` on no qualifying activity,
  10b5-1 and non-P/S codes correctly excluded, the 6-month window
  boundary, the point-in-time look-ahead guard, share-count (not
  transaction-count) weighting, and security-id isolation.
- `tests/data_infra/test_ingest_insider_transactions_wiring.py` (14
  tests, AST/source-text only -- this script is never imported or
  executed by the automated suite, identical discipline to
  `test_ingest_fundamentals_data_wiring.py`).
- `tests/strategy_research/test_compute_fundamentals_ic_from_catalog_cli.py`
  and `tests/strategy_research/test_run_long_horizon_validation_factor_wiring.py`
  extended with end-to-end/factory-level coverage of the new
  `--insider-db-path` wiring in both scripts.

Full repository test suite re-run after all of the above; every
pre-existing test still passes.
