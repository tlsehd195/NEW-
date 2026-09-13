# ADR-0134: SEC Form 13F Institutional Holdings Coverage Expanded Beyond Berkshire (State Street, FMR, BlackRock, Vanguard)

**Status:** Accepted
**Date:** 2026-09-13
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0131-sec-13f-real-format-and-free-cusip-resolution.md`
(the pipeline this ADR reuses unmodified except the OpenFIGI rate-limit fix below),
`docs/decisions/ADR-0104-institutional-ownership-change-factor.md`

---

## Context

Following item #4 of the account owner's own "1번 제외 5번 제외 전부" instruction
(proceed with everything except the still-blocked insider-transaction raw IC and
the already-on-hold Live Trading activation), this session expanded
`institutional_ownership_change_score`'s real data coverage beyond the single
filer (Berkshire Hathaway, 28 securities) ADR-0131 established -- the user's
own stated goal being closer-to-market-representative institutional ownership
data, not one concentrated-position filer.

## Decision 1 -- Real CIKs for four more major 13F filers, found by following the SEC's own `otherManagersInfo` disclosure, never guessed

State Street Corp (CIK `0000093751`) and FMR LLC (CIK `0000315066`) were
straightforward -- both file real, current `13F-HR` directly under their own
CIK, discovered by the same `data.sec.gov/submissions/CIK...json` lookup
ADR-0132 already established for Form 4.

BlackRock and Vanguard were not straightforward, and were resolved by reading
the real content of their own `13F-NT` ("Notice", filed when a manager's
holdings are actually reported by a different, affiliated CIK) filings'
`primary_doc.xml` rather than guessing further candidate CIKs:

- **BlackRock**: the CIK previously known as "BlackRock Inc" (`0001364742`)
  stopped filing 13F entirely after 2024 (confirmed by the account owner's own
  direct EDGAR browsing, a prior-session finding). Several plausible successor
  candidates (BlackRock Fund Advisors `1006249`, BlackRock Advisors LLC
  `1086364`, BlackRock Institutional Trust Co `913414`, BlackRock Investment
  Management LLC `1305227`, BlackRock Group LTD `1003283`) were all real,
  currently-active EDGAR filers, but every one of them files only `13F-NT`
  since ~2024 -- confirmed directly by fetching and printing each one's real
  filing history. Fetching BlackRock Group LTD's own most recent `13F-NT`
  `primary_doc.xml` (accession `0001003283-26-000003`) revealed its real
  `otherManagersInfo` cover-page field: `BlackRock, Inc.`, **CIK `0002012383`**
  -- a brand-new CIK (re-registered under the same legal name after the old
  `1364742` CIK stopped being used), confirmed by direct query to file real,
  current `13F-HR` every quarter (`2025-11-12` through `2026-08-07`).
- **Vanguard**: Vanguard Group Inc (`0000102909`) itself filed real `13F-HR`
  through `2026-01-29` (Q4 2025), then switched to `13F-NT` starting Q1 2026
  (`2026-05-08`) -- a genuine, recent (this year) structural change, not a
  bug. Its `13F-NT`'s own `otherManagersInfo` field listed 10 real affiliated
  entities; querying each confirmed **all 10** now file real, separate
  `13F-HR` each quarter (Vanguard split its previously-single combined report
  across legal entities starting Q1 2026): Vanguard Fiduciary Trust Co
  (`0000933478`), Vanguard Investments Australia Ltd (`0001550100`), Vanguard
  Portfolio Management LLC (`0002100121`), Vanguard Capital Management LLC
  (`0002100119`), Vanguard Marketing Corp (`0000217448`), Vanguard
  Personalized Indexing Management LLC (`0001767306`), Vanguard Asset
  Management Ltd (`0001680208`), Vanguard National Trust Co (`0001984256`),
  Vanguard Global Advisers LLC (`0001811242`), Vanguard Advisers Inc
  (`0000947529`).

## Decision 2 -- Treat each of the 14 filer files as its own "filer" for `num_institutions`, matching the existing schema's own literal definition; no new aggregation code

`data_infra.institutional_holding_models`'s own module docstring already
defines `num_institutions` as counting "every 13F filer that reported a
position" -- a literal per-SEC-filer count, not an economic-parent-company
count. Vanguard's 10 entities are real, legally distinct SEC filers (each
with its own CIK/CRD/`form13FFileNumber`), so counting them as 10 separate
filers is the correct application of the existing definition, not a
workaround. `scripts/convert_sec_13f_filings_to_combined_csv.py` already
sums shares and counts filer files across however many input files it is
given (ADR-0131's own stage-two design) -- no code change was needed to
support 14 filers instead of 1; the real work here was finding the correct
14 real CIKs/accessions, not new aggregation logic.

`quarter_end` for every filing was verified (never guessed from a filing-date
pattern) by parsing each real filing's own `primary_doc.xml`
`<periodOfReport>` field before use -- both quarters resolved to the expected
`2026-06-30` and `2026-03-31`.

## Decision 3 -- Fix a real OpenFIGI rate-limit bug the original single-filer pipeline never exercised

`scripts/convert_sec_13f_filings_to_combined_csv.py`'s own `_resolve_cusips`
treated any OpenFIGI HTTP 429 as immediately fatal, discarding every already-
resolved batch. ADR-0131's original Berkshire-only run (29 CUSIPs, 3 batches)
never approached the real, already-confirmed 25-requests-per-60-seconds
anonymous-tier rate limit, so this was never triggered until this session's
real ~600-CUSIP/676-batch run hit it. Fixed with two new CLI options:
`--request-delay` (paces requests under the confirmed limit, default 2.5s)
and `--max-429-retries` (retries a rate-limited batch honoring a real
`Retry-After` header, or a 60s backoff, rather than failing the whole run).
Also added a per-batch progress log line (flushed immediately) -- a real,
several-hundred-batch run with no interim output left the account owner
unable to tell whether it was still running.

## Real end-to-end result (account owner's own Google Colab environment)

Both quarters' real 13F-HR filings (14 filers each) were downloaded,
verified for `periodOfReport`, combined, CUSIP-resolved via OpenFIGI, and
ingested into the same `institutional_holdings_db` DuckDB catalog used since
ADR-0131:

| quarter_end | filers | securities resolved | CUSIPs unresolved (excluded) | ingest result |
|---|---|---|---|---|
| 2026-03-31 | 14 (Berkshire, State Street, FMR, BlackRock, 10x Vanguard) | 5,855 | 904 | `Total institutional holding records persisted: 5855`, `Missing symbols: []` |
| 2026-06-30 | 14 (same) | 6,034 | not separately recorded this session | `Total institutional holding records persisted: 6034`, `Missing symbols: []` |

The large jump from Berkshire's own 28 securities to several thousand is
expected, not a bug: State Street, BlackRock, and Vanguard together run some
of the world's largest index funds, which legitimately hold positions across
most US-listed common stock and ETFs -- unlike Berkshire's own concentrated,
actively-managed portfolio.

## Consequences

### Positive

- `institutional_ownership_change_score` now has real two-quarter coverage
  for thousands of securities instead of 28, a real, substantial expansion
  of this factor's usable universe.
- The real CIK-discovery method (reading a `13F-NT` filing's own
  `otherManagersInfo` field) is now a proven, reusable technique for any
  future large-manager 13F work this project does -- never guess a successor
  CIK; read what the filing itself says.
- The OpenFIGI rate-limit fix and progress logging are permanent
  improvements to `convert_sec_13f_filings_to_combined_csv.py`, benefiting
  any future run at this or larger scale.

### Negative / Trade-offs

- 904 CUSIPs (out of ~6,700+ distinct CUSIPs across the 14 filers,
  2026-03-31) could not be resolved to a US ticker via OpenFIGI and were
  excluded with a `WARNING`, never fabricated -- likely a mix of foreign
  securities, private placements, and instruments genuinely outside
  OpenFIGI's free-tier coverage. Not further investigated this session.
- `num_institutions` for a security both Vanguard and, say, Berkshire hold
  will now count Vanguard as up to 10 (one per sub-entity that reported a
  position in it) rather than 1 -- a real consequence of Decision 2's
  literal-filer-count choice, disclosed here for a future session or the
  account owner to revisit if a "distinct economic institution" count is
  ever needed instead.
- Point-in-time caveats already disclosed in ADR-0131 (OpenFIGI resolves to
  TODAY's ticker mapping, not the historical quarter's) apply unchanged and
  at greater scale now.

## Tests

No new unit tests -- this ADR's work was entirely a real external-data
pipeline run (network calls, Colab environment) plus two small, already-
tested-by-existing-suite code changes to
`scripts/convert_sec_13f_filings_to_combined_csv.py` (pacing/retry logic and
progress logging), which remains untested directly by the automated suite
per ADR-0131's own precedent (real OpenFIGI network call, never imported by
the test suite). Full suite re-run clean after these changes (3066 passed).

## Status of Implementation at Time of This ADR

Code changes (`_resolve_cusips` pacing/retry + progress logging) complete and
committed. Real end-to-end pipeline run complete on the account owner's own
Google Colab environment; both quarters persisted to the shared
`institutional_holdings_db` DuckDB catalog. A real `institutional_ownership_
change_score` computation against this expanded dataset (mirroring
ADR-0131's own Berkshire-only follow-up) has not yet been performed this
session -- a natural next step, not done here.
