# ADR-0125: Real FINRA Equity Short Interest API Response Converter

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** Claude Code (documentation cleanup session, continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0124-combined-csv-mode-for-short-interest-and-13f-import.md`,
`docs/decisions/ADR-0099-short-interest-factor.md`

---

## Context

Following up on ADR-0124's `--combined-csv` mode, the user (in their
own environment, which this sandbox cannot reach) successfully:

1. Discovered FINRA's actual API Data Access platform (`group=
   otcMarket`, `dataset=EquityShortInterest`, `https://api.finra.org/
   data/group/otcMarket/name/EquityShortInterest`).
2. Authenticated via OAuth2 client-credentials against `https://
   ews.fip.finra.org/fip/rest/ews/oauth2/access_token` and obtained a
   real Bearer token.
3. Called the real endpoint and got back a REAL response.

This is the first time in this project's history that a real FINRA
short-interest API response has actually been observed -- every prior
session could only reach FINRA's documentation via web search (never
the live API itself, since this sandbox's egress blocks
`finra.org`/`api.finra.org` entirely -- re-confirmed this session).
`short_interest_file_import.py`'s own module docstring has, since
ADR-0099, explicitly declined to build a parser for FINRA's real
format for exactly this reason. That reason no longer applies to a
converter built directly from an observed real response (as opposed to
guessed from documentation).

## Decision 1 -- Build the converter from the REAL response, not from documentation guesses

The real response the account owner shared:

```json
{"issueSymbolIdentifier":"AAALF","issueName":"Aareal Bank AG AKT",
 "marketCategoryDescription":"Other OTC","marketCategoryCode":"u",
 "changePercent":20.07,"currentShortShareNumber":131471,
 "daysToCoverNumber":999.99,"settlementDate":"2018-09-14",
 "previousShortShareNumber":109497,"averageShortShareNumber":0,
 "percentageChangefromPreviousShort":21974}
```

This immediately corrected two guesses this session had made earlier
from documentation search alone (recorded in the prior conversation,
not a prior ADR): the real field for the short position is
`currentShortShareNumber`, not `currentShortPositionQuantity`; and
there is **no `averageDailyVolumeQuantity` field at all** -- the real
payload instead carries `averageShortShareNumber`, a different concept
entirely (an average SHORT POSITION over some window, not average
DAILY TRADING volume). This is exactly the kind of mistake this
project's "never guess an external format" discipline exists to
prevent, and exactly why this converter was only built once a real
response was in hand.

`scripts/convert_finra_short_interest_response.py` maps:

| Real FINRA field | This project's column |
|---|---|
| `issueSymbolIdentifier` | `security_id` |
| `settlementDate` | `settlement_date` |
| `currentShortShareNumber` | `short_interest_quantity` |
| `daysToCoverNumber` | `days_to_cover` |
| *(none)* | `average_daily_volume` -- always blank |

## Decision 2 -- The `999.99` sentinel is converted, never passed through as a literal ratio

Cross-verified via FINRA's own public "Short Interest" investor
documentation (found via web search, corroborating what the real
response's data pattern already suggested -- multiple real records
returned exactly `999.99`, an implausible coincidence for a real
computed ratio): `999.99` is FINRA's documented sentinel for an
undefined days-to-cover ratio (typically a security with no trading
volume to divide by), not a literal "999.99 days" figure. Converting
it to blank (`None`) rather than passing it through avoids silently
feeding a misleading precision into `short_interest_score`
(`strategy_research.factor_scores`) downstream.

## Decision 3 -- `average_daily_volume` stays honestly blank, never backfilled from a different metric

`averageShortShareNumber` was deliberately NOT mapped to
`average_daily_volume` despite the tempting field-name proximity --
they measure different things. Mapping them would be exactly the kind
of value-mislabeling this project's fail-closed discipline forbids
elsewhere (the same reasoning `ADR-0043`/multiple factor ADRs have
applied when a "close enough"-sounding field turned out to be a
different metric). `average_daily_volume` is already an optional
column in this project's own schema (`ADR-0099`), so leaving it blank
is a fully supported, honest outcome, not a workaround.

## Tests

12 new tests (`tests/data_infra/test_convert_finra_short_interest_
response.py`), using fixture records shaped exactly like the real
response (every field the real payload carries, not a guessed subset)
-- including one true end-to-end test that pipes this script's output
directly into `ingest_short_interest_data.py --combined-csv`
(ADR-0124), proving the two scripts' schemas actually agree in
practice, not just in isolation.

## Consequences

### Positive

- The account owner can now go from a real FINRA API response (saved
  as one or more JSON files) to a fully ingested `ShortInterestRecord`
  set with two commands total: this converter, then `ingest_short_
  interest_data.py --combined-csv`.
- Corrects, with real evidence, two guesses this session had made
  earlier purely from documentation search -- a concrete example of
  why this project insists on verifying against a real response before
  committing to a field mapping.

### Negative / Trade-offs

- This is a NEW real external source. The user acquired the
  credentials and made the actual call in their own environment --
  this session never touched FINRA's live API directly and cannot
  independently re-verify the mapping against a second real response.
  If FINRA's response shape changes in the future, this converter
  would need re-verification against a fresh real response, the same
  as any other external-format-dependent code in this project.
- `Institutional Holdings` (Form 13F) has no equivalent converter yet
  -- the account owner has not yet obtained a real 13F API response to
  verify a mapping against. Left as future work, not guessed at here.

## Status of Implementation at Time of This ADR

`scripts/convert_finra_short_interest_response.py` (new, no network
call, pure JSON->CSV transform). 12 new tests. Manually verified this
session against the real sample response end-to-end (converted, then
successfully ingested via `ingest_short_interest_data.py
--combined-csv`) before being committed as an automated test fixture.
