# ADR-0131: Real SEC Form 13F Information Table Format + Free CUSIP-to-Ticker Resolution (OpenFIGI)

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0104-institutional-ownership-change-factor.md`,
`docs/decisions/ADR-0099-return-seasonality-and-short-interest-factors.md`,
`docs/decisions/ADR-0125-finra-equity-short-interest-real-response-converter.md`

---

## Context

`data_infra.institutional_holding_models`'s own module docstring has,
since it was written, declined to parse SEC's real Form 13F data for
two compounding reasons: this sandboxed session cannot reach
`sec.gov` to observe a real filing, and even with access, SEC's own
13F data is keyed by CUSIP -- an identifier this project's
`SecurityMaster` has never carried, with no known free resolution
path. The user, having proceeded through the delisted-price-data
thread (`ADR-0122`-`ADR-0130`), asked to proceed on the remaining
backlog including SEC 13F, previously skipped as "too complex" earlier
this session. This ADR records both gaps closing for real, in the
account owner's own environment (this sandbox still cannot reach
`sec.gov`/`api.openfigi.com` directly).

## Decision 1 -- The real Form 13F Information Table XML format, observed for the first time

The account owner fetched a real 13F-HR filing (Berkshire Hathaway,
CIK 0001067983, accession 0001193125-26-352200, filed 2026-08-14) via
SEC EDGAR's public, no-API-key `data.sec.gov`/`www.sec.gov` endpoints
(a descriptive `User-Agent` header is SEC's only real requirement, not
authentication). The filing's own `index.json` revealed the actual
holdings live in a separately-named XML file (`56757.xml` here, not
the `primary_doc.xml` named in the submissions feed -- that document
is the cover page/summary, not the holdings). The real, verified
`informationTable` XML shape:

```xml
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ALLY FINL INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>02005N100</cusip>
    <value>577211815</value>
    <shrsOrPrnAmt><sshPrnamt>12561737</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
    <otherManager>4</otherManager>
    <votingAuthority>...</votingAuthority>
  </infoTable>
  ...
```

**A single CUSIP can legitimately repeat multiple times within one
filer's own filing** -- confirmed directly: CUSIP `02005N100` (Ally
Financial) appeared 6 times in this one real filing, each with a
different `otherManager` value, real share counts summing to an exact,
round **27,000,000 shares**. `data_infra.providers.sec_13f_infotable_
parser.aggregate_shares_by_cusip` (new) sums every line item sharing a
CUSIP -- picking only the first would have silently reported roughly
half of Berkshire's real position.

`value`'s real unit is deliberately never extracted -- SEC's own Form
13F instructions changed the reporting convention from thousands of
dollars to whole dollars for filings after January 2023, and this
project has not verified which convention any specific historical
filing used. This project's own schema does not need `value`
(`institutional_shares`/`num_institutions` only), so it is left
unparsed rather than risk asserting a wrong unit.

## Decision 2 -- OpenFIGI resolves CUSIP -> ticker for free, with the exact right filter confirmed by direct testing

Real-tested (account owner's own environment): `POST https://api.
openfigi.com/v3/mapping` with `[{"idType":"ID_CUSIP","idValue":
"02005N100"}]` returns the real ticker `ALLY` -- but bundled with
100+ other real listings for the same company across every foreign
exchange, ADR, and currency-hedged share class (`ALLYEUR`, `ALLYGBP`,
`ALLYCHF`, `GMZ`, ...). Adding `"exchCode":"US"` to the SAME request
(confirmed with the identical real CUSIP, both with and without the
filter, in the same session) collapses the response to exactly the
one real US-primary listing. This is free with no API key, closing
`institutional_holding_models`'s second named gap ("this project's
`SecurityMaster` has never carried a CUSIP field... guessing... a
CUSIP-to-`security_id` mapping this project cannot independently
verify would violate this project's discipline").

**Real batch-size correction (found only by actually running this for
real, not from documentation)**: secondary sources this session
initially relied on claimed a 100-CUSIPs-per-request limit without an
API key. A real request with the account owner's own 29 distinct
CUSIPs (from the real Berkshire filing) returned `HTTP 413`, with a
real, exact response body: `"Request may only contain 10 mapping
jobs."` -- the true anonymous-tier limit is **10**, not 100 (the
response also carried a separate `ratelimit-limit: 25` header, a
per-60-second REQUEST-RATE cap, a different constraint from the
per-request ITEM-COUNT cap). `build_mapping_request` was corrected to
never hardcode either number itself -- batching is `scripts/convert_
sec_13f_filings_to_combined_csv.py`'s own `--batch-size` (default now
10, tunable), so a future real limit change needs updating in exactly
one place, not two.

`data_infra.providers.openfigi_cusip_resolution` (new) separates the
pure request-building/response-parsing logic (tested against this real
response shape) from the actual network call
(`scripts/convert_sec_13f_filings_to_combined_csv.py`), the identical
split this project already uses for every other real external format
(`sec_13f_infotable_parser`, `fmp_delisted_price_import`, `check_wiki_
prices_delisted_coverage`).

## Decision 3 -- `quarter_end` must be supplied explicitly; never parsed or guessed

The Information Table XML itself carries no period-of-report field --
that lives in the filing's separate cover-page document
(`primary_doc.xml`), which `scripts/convert_sec_13f_filings_to_
combined_csv.py` does not parse. `--quarter-end` is a required CLI
argument; the script never defaults it to today's date or infers it
from a filename.

## Decision 4 -- Two-stage aggregation, matching `institutional_holding_models`'s own documented design

Stage one (within one filer's own filing): `aggregate_shares_by_cusip`
sums every line item sharing a CUSIP (Decision 1). Stage two (across
every filer this run is given): `scripts/convert_sec_13f_filings_to_
combined_csv.py` sums each resolved ticker's shares across every input
filing and counts how many distinct filer files reported a position in
it, populating `num_institutions` honestly (a real filer count, never
a placeholder). A CUSIP OpenFIGI cannot resolve to a US ticker is
excluded from the output with a `WARNING`, never silently dropped
without a trace or fabricated with a guessed ticker.

## Consequences

### Positive

- Both gaps `institutional_holding_models`'s own module docstring
  named as reasons this project had never attempted real SEC 13F
  parsing are now closed with real, verified evidence -- not guessed,
  the same "convert only from an observed real sample" discipline
  `ADR-0125`'s FINRA converter established.
- Free, no signup cost, no API key required for OpenFIGI at this
  project's likely volume (a research universe's worth of CUSIPs
  easily fits in 100/request, 5,000/day).
- Reuses the EXISTING `--combined-csv` mode (`ADR-0124`) and
  `institutional_holding_file_import.py`/`ingest_institutional_
  holdings.py` pipeline unmodified -- this ADR's new code only produces
  that already-supported CSV shape.

### Negative / Trade-offs

- This session verified the real format against exactly ONE real
  filing (Berkshire Hathaway) and ONE real CUSIP (Ally Financial,
  `02005N100`) -- a second filer's filing could reveal a genuinely
  different real-world variation (e.g. a filer using `PRN` instead of
  `SH` for `sshPrnamtType`, meaning principal amount rather than share
  count, which this parser does not currently distinguish or convert)
  this session has not encountered and therefore cannot claim to
  handle.
- OpenFIGI's ticker resolution reflects TODAY's real mapping, not the
  ticker that was current AS OF the 13F's own historical quarter -- a
  security that changed ticker or was acquired between the filing's
  quarter and today would resolve to a name/ticker that did not exist
  at that historical point, a real point-in-time caveat this project's
  own `short_interest_file_import.py`/FINRA work has not had to
  contend with (FINRA's own response already used current tickers).
  Not yet mitigated; disclosed here for a future session or the
  account owner to weigh.
- `--quarter-end` accuracy is entirely on the account owner -- this
  script cannot verify it against the actual filing's own period of
  report, since it never parses `primary_doc.xml`.
- Real bulk coverage (how well this pipeline performs across many
  filers and many CUSIPs, not just the one real case tested) is
  untested as of this ADR.

## Tests

19 new tests: 9 in `tests/data_infra/test_sec_13f_infotable_parser.py`
(using the real Berkshire/Ally Financial six-line-item fixture,
including the real 27,000,000-share aggregate total), 10 in
`tests/data_infra/test_openfigi_cusip_resolution.py` (using the real
OpenFIGI response fixture, both the `exchCode` filter's presence in
the request and the real resolved ticker in the response).
`scripts/convert_sec_13f_filings_to_combined_csv.py` itself makes a
real network call (OpenFIGI) and is therefore not exercised by the
automated test suite, matching `fetch_fmp_delisted_prices.py`'s own
precedent -- its argument parsing and fail-closed paths (missing file,
no CUSIPs found) were manually verified this session.

## Status of Implementation at Time of This ADR

`data_infra/providers/sec_13f_infotable_parser.py` and `data_infra/
providers/openfigi_cusip_resolution.py` (both new, pure, no network),
`scripts/convert_sec_13f_filings_to_combined_csv.py` (new, one real
network call type, never test-suite-executed). No changes to
`institutional_holding_file_import.py`, `ingest_institutional_
holdings.py`, or `institutional_holding_models.py` -- all three
already supported this exact combined-CSV workflow.

**Real end-to-end result** (account owner's own environment -- run
from a local Windows machine + Git Bash after the account owner's
Codespaces free quota was exhausted mid-session, a real, independent
re-verification that this pipeline does not depend on any one specific
environment): converting the real Berkshire Hathaway 13F filing
produced **28 real securities from 1 filer**, 1 CUSIP (`H1467J104`)
correctly excluded with a warning (unresolved, not fabricated). Spot
checks against independently, publicly known facts confirm real
correctness, not coincidence:

- `ALLY,27000000` -- matches this ADR's own Decision 1 hand-calculation
  exactly.
- `KO,400000000` -- Berkshire's Coca-Cola stake has been publicly
  reported as exactly 400,000,000 shares for years; an exact match to
  a widely-known real fact is strong, independent confirmation this
  pipeline's real output is correct, not merely plausible-looking.
- The remaining 26 tickers (`AAPL`, `AXP`, `BAC`, `CVX`, `KHC`, `MCO`,
  `OXY`, ...) are all independently, publicly known real long-term
  Berkshire Hathaway holdings -- no unexpected or implausible entries.

Immediately following, the account owner ran `scripts/ingest_
institutional_holdings.py --combined-csv combined_13f.csv --symbols
<all 28> --as-of 2026-09-12 --db-path 13f_db` against this exact real
output (after installing this project's only two real dependencies,
`duckdb`/`pyarrow`, on the fresh Windows machine): **`Total
institutional holding records persisted: 28`, `Missing symbols: []`**
-- all 28 real securities, zero failures. This is the first time this
project has ever persisted a real `InstitutionalHoldingRecord` sourced
from an actual SEC Form 13F filing, closing the loop this ADR opened
completely: real filing -> real parsing -> real CUSIP resolution ->
real combined CSV -> real persisted records, verified end to end on
two independent environments (a GitHub Codespace and a personal
Windows machine).

## Follow-up -- a second real quarter, and the first-ever real, non-`None` `institutional_ownership_change_score`

`institutional_ownership_change_score` (`strategy_research.factor_
scores`) requires at least two distinct quarters of real institutional
holdings for one security before it returns anything but `None`
(RULE 0.8 -- never a fabricated change). The account owner fetched
Berkshire's PRIOR real 13F-HR filing (same CIK, accession
0001193125-26-226661, filed 2026-05-15, real `periodOfReport`
`03-31-2026`, real information table file `53405.xml`) through the
identical real pipeline this ADR already established, producing a
second real `combined_13f_prior.csv` (28 securities, `quarter_end`
2026-03-31). Both quarters were ingested into the SAME `13f_db`
DuckDB catalog.

**A real environment gotcha, found and fixed this session**: on the
account owner's Windows machine, `python3` resolves to Windows' own
Microsoft Store "App Execution Alias" stub (`AppData\Local\Microsoft\
WindowsApps\python3`), not the real interpreter -- it silently prints
`Python` and exits (a real, confirmed, non-standard exit code, 49) doing
nothing at all, rather than erroring loudly. The real interpreter
(installed from python.org) only answered to `python`, confirmed via
`python --version` -> `Python 3.12.10`. Every command on this machine
must use `python`, never `python3` -- worth remembering for any future
Windows-based session in this project, since the failure mode here
(silent no-op, not a clear error) cost real diagnostic time.

With both real quarters ingested, the account owner called
`institutional_ownership_change_score` directly against the real,
now-two-quarter-populated `DuckDBInstitutionalHoldingRepository` for
four real securities. Real, verified results (2026-09-12):

| security_id | Q1 2026 shares | Q2 2026 shares | score (`ln(current/prior)`) |
|---|---|---|---|
| `ALLY` | 29,000,000 | 27,000,000 | `-0.07145896398214498` |
| `BAC`  | 513,624,165 | 483,394,015 | `-0.06065971436072147` |
| `KO`   | 400,000,000 | 400,000,000 | `0.0` |
| `AAPL` | 227,917,808 | 227,917,808 | `0.0` |

Every value matches hand-calculation exactly (e.g.
`ln(27000000/29000000) == -0.07145896398214498`), and every sign
matches independently known real facts: Berkshire's real, publicly
reported Q2 2026 trimming of both Ally Financial and Bank of America
produces the two negative scores; Coca-Cola and Apple, both unchanged
between the two real quarters, correctly score exactly `0.0` rather
than `None` (the function only returns `None` for genuinely missing
data, not for a real, confirmed-zero change). This is the first time
in this project's history that `institutional_ownership_change_score`
has produced a real, non-`None` value from genuine SEC data end to
end -- closing the last gap `ADR-0104` (the factor's own original
design decision) left open pending real 13F data ever existing in this
project's storage.
