# ADR-0127: Free Price Data for Post-2018 Delistings — Still Blocked (Yahoo Finance and Stooq Both Empirically Rejected)

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0126-quandl-wiki-prices-free-delisted-price-source.md`,
`docs/decisions/ADR-0123-delisted-price-data-deep-search-still-blocked.md`

---

## Context

`ADR-0126` found a real, free, partial solution to the delisted-ticker
price problem (Quandl WIKI Prices via its Kaggle mirror), but that
source is frozen at 2018-03-27 -- it has no data for any ticker
delisted after that date. This project's own `data/sp500_ticker_
start_end.csv` (`fja05680/sp500`, ADR-0120) shows **195 S&P 500
tickers removed since 2018** (e.g. `ATVI` 2023-10-18, `AVB`
2026-08-18, `AAL` 2024-09-23, `ABC` 2023-08-30, `CERN` 2022-06-08),
none of them covered by ADR-0126's source. The user explicitly asked to
push from "partially solved" to "fully solved" and, having ruled out
every paid option earlier this session, asked to keep searching free
options for this remaining window.

## Decision 1 -- Yahoo Finance's chart API: empirically tested, rejected

Tested directly (account owner's own environment; this sandbox cannot
reach `finance.yahoo.com`) against `ATVI` (Activision Blizzard,
acquired by Microsoft, delisted 2023-10-18) using the real undocumented
chart endpoint `query1.finance.yahoo.com/v8/finance/chart/{symbol}`,
with a real browser `User-Agent` header (the first attempt without one
was rate-limited by Yahoo's edge, `Edge: Too Many Requests` -- not
itself evidence of anything, just a missing-header block):

- `AAPL` (a currently-listed control): real, current data returned.
- `ATVI`: `{"chart":{"result":null,"error":{"code":"Not Found",
  "description":"No data found, symbol may be delisted"}}}` -- an
  explicit, unambiguous rejection from Yahoo's own backend, not a
  network or formatting problem. Yahoo has evidently purged (or at
  minimum, made permanently inaccessible via this endpoint) the
  historical price series for a ticker once it delists. **Rejected**,
  same empirical-test-before-trust discipline as `ADR-0123`'s `DELL`
  test against `pystock-data`.

## Decision 2 -- Stooq: empirically tested across multiple rounds, rejected

Stooq's plain CSV download endpoint (`stooq.com/q/d/l/?s={symbol}.us&i=d`,
the same endpoint `StooqDataProvider`, ADR-0025/ADR-0028, has always
assumed but never verified against a live response) is now gated by a
client-side proof-of-work + headless-browser-detection system, tested
directly with Playwright (Chromium) in the account owner's environment:

1. A plain `curl` request (even with a real `User-Agent`) returns an
   HTML page with an inline `<script>` that computes a SHA-256
   proof-of-work (`d=4` leading zero hex digits) and POSTs the result
   to `/__verify`, then calls `location.reload()` -- this happens
   identically for `AAPL` (currently listed) and `ATVI` (delisted),
   confirming the gate is NOT delisting-specific; it blocks all
   scripted access equally.
2. Running this in a real headless Chromium via Playwright: the
   proof-of-work genuinely executes, `/__verify` genuinely returns
   `200`, and a real `auth` cookie IS issued (`httpOnly`, `secure`,
   `sameSite=Lax`) -- the challenge itself is solvable by a real
   browser engine, not merely detected-and-blocked at that layer.
3. Despite the valid cookie, reloading (or a fresh navigation in the
   same cookie-carrying browser context) up to 5 rounds never returned
   the real CSV -- it either re-presented a brand-new, unsolved
   challenge, or (once the resource's `Content-Type` triggered a
   Playwright `download` event instead of an in-page navigation)
   returned a file whose entire content was the literal text
   **`Access denied`**.
4. Conclusion: Stooq layers a SECOND defense (very likely headless-
   browser fingerprinting -- `navigator.webdriver` and related signals
   real headless Chromium exposes) on top of the proof-of-work gate.
   Passing the first layer is not sufficient; this project has no
   further, non-fragile way to defeat browser fingerprinting from here.
   **Rejected** -- and notably, this means `StooqDataProvider`'s own
   long-standing Tier-2 assumption about its endpoint shape (`ADR-0025`)
   remains completely unverified against a live response to this day;
   this session did not get far enough to even test whether Stooq
   would have served delisted-ticker data at all had the gate been
   passable.

## Decision 3 -- Stop pursuing browser-automation bypasses; document, don't keep escalating

Per this project's established cost/benefit discipline (`ADR-0123`'s
`pystock-data` rejection: "the engineering cost... does not clear the
bar set by how little it would actually unblock"), further escalation
(browser-fingerprint spoofing libraries, residential proxies, longer
challenge-solving loops) was explicitly declined, with the account
owner's agreement, after this Decision-2 result:

- Even a successful bypass would still be unverified as to whether
  Stooq's data would actually include delisted tickers at all --
  Decision 2 never got far enough to test that question.
- Any successful bypass would be inherently fragile: an anti-bot system
  actively defending against automation can change its defenses at any
  time, turning this into an ongoing maintenance burden rather than a
  one-time integration, unlike the stable, static Kaggle-hosted file
  `ADR-0126` already integrated successfully.

## Consequences

- The 195 S&P 500 tickers removed since 2018 (and any non-S&P-500
  ticker delisted since then) remain **`ENVIRONMENT_BLOCKED`** for real
  free price data, exactly as `ADR-0123` originally concluded for the
  full problem -- `ADR-0126` narrowed the blocked window (now
  post-2018-03-27 only, previously the entire history), it did not
  close it.
- `StooqDataProvider`'s Tier-2, never-verified endpoint-shape assumption
  (`ADR-0025`) remains exactly as unverified as before this session --
  this investigation did not reach the point of testing it.
- No code changes result from this ADR -- a pure, documented negative
  research outcome, matching `ADR-0123`'s own precedent of recording a
  thorough "still blocked" finding (including concrete attempted
  bypasses and why they failed) rather than silently repeating the same
  brief conclusion if asked again later.

## Status of Implementation at Time of This ADR

No code changed. All temporary test scripts (`/tmp/stooq_test*.py`,
`/tmp/AAPL_download.csv`) live only in the account owner's own
environment and were never committed to this repository.
