# ADR-0170: Verify a real Alpaca paper broker account via an actual buy->sell round trip

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued), account owner (obtained
a real Alpaca paper-trading key/secret/endpoint and asked for
verification "level 2": a real buy/sell round trip, not just a
connectivity check)
**Related documents:** `docs/PROJECT_STATUS.md`'s 2026-09-17 backlog
entry #5 ("alpaca-py 실브로커 페이퍼 계좌 검증"), `docs/decisions/ADR-0169-automate-quantstats-tearsheet-defer-alphalens.md`
(same session's prior backlog item)

## Context

The account owner obtained real Alpaca paper-trading credentials and,
when offered three scope options (connectivity-only, a real buy/sell
round trip, or a full production-grade broker adapter matching the
existing Toss adapter's shape), chose the middle option: prove the
whole order lifecycle (submit -> fill -> submit closing order -> fill)
actually works against a real account, without building a permanent,
production-wired broker integration this project does not yet need.

This session's own egress cannot reach `paper-api.alpaca.markets`
(same class of restriction as every other external API this project
has hit), so the verification itself must run as a GitHub Actions
`workflow_dispatch` job -- the same pattern ADR-0168's repair workflow
already established for reaching production resources this session
cannot touch directly.

## Decision

**New `scripts/verify_alpaca_paper_broker.py`** (network-real,
`workflow_dispatch`-only, never scheduled):

1. Reads `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` only from environment
   variables (never a CLI flag, so a real secret is never visible in a
   process list or shell history); `ALPACA_BASE_URL` is optional.
2. Refuses to run (`_is_paper_endpoint`) against anything but Alpaca's
   own paper domain (`paper-api.alpaca.markets`) -- a misconfigured
   `ALPACA_BASE_URL` pointing at the real live-trading domain can never
   reach the order-submission code path. `None`/unset is treated as
   "use alpaca-py's own default paper domain," not rejected.
3. Fetches the real account and refuses to proceed if it reports
   trading/account blocked.
4. Checks the real market clock (`get_clock().is_open`) before
   submitting anything -- a market order submitted while the market is
   closed would just sit unfilled for hours; the script exits cleanly
   (exit code 2, distinct from a real failure) with the real next-open
   time rather than waiting or claiming a fill that didn't happen.
5. Submits a real market BUY, polls (`_poll_until_terminal`) for a
   terminal order status, and only claims success if it actually
   reaches `filled` -- never assumes a fill from a non-terminal status.
6. Submits a real market SELL for the **actual filled quantity**
   (`filled_buy.filled_qty`, never the originally requested `--qty`) to
   correctly close out even a partial fill, and polls the same way.
7. Only prints "round trip verified" once both fills are real and
   confirmed -- any other outcome is reported plainly (which leg
   failed, at what status) rather than glossed over.

**Uses `alpaca-py` (the official SDK) directly**, added as a new
`broker-verification` optional extra in `pyproject.toml` -- unlike
`src/data_infra/providers/`'s config/auth/transport-split, stdlib-only
discipline (which exists because those providers are permanent,
production-wired components), this is a one-off, manually-triggered
verification tool with no ongoing integration into the live/paper
trading pipeline, so the pragmatic official SDK is the right choice
here and does not set a precedent for `src/`.

**New `.github/workflows/verify_alpaca_paper_broker.yml`**,
`workflow_dispatch`-only (never a schedule, since every run places real
paper orders), with `symbol`/`qty` inputs defaulting to `AAPL`/`1`.
Credentials come from `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`/
`ALPACA_BASE_URL` repository secrets, mirroring every other provider
credential already wired into this project's other workflows.

## Consequences

### Positive

- Closes backlog item #5 from the 2026-09-17 session-status entry for
  real, not just claimed.
- The account owner's Alpaca credentials get exercised end to end
  (auth, account state, order submission, fill polling, a second order
  to unwind the first) without committing to building or maintaining a
  full broker adapter this project does not yet use anywhere.
- The paper-domain guard and the market-clock check make accidental
  misuse (a live-domain override, or a run outside market hours that
  would otherwise leave a confusing indefinitely-pending order) fail
  safely and legibly instead of silently.

### Negative / Trade-offs

- This is verification only -- no `AlpacaBrokerAdapter` conforming to
  this project's own broker Protocol exists yet. If a future session
  decides to actually trade through Alpaca, that is new, separate work
  (the "정식 브로커 어댑터 구축" option the account owner did not choose
  this time).
- `main()`'s real-network path (account/clock/order calls) cannot be
  exercised by the automated test suite (same real-network limitation
  as `scripts/ingest_real_market_data.py`) -- covered by real,
  executable unit tests for its two pure helpers
  (`_is_paper_endpoint`/`_poll_until_terminal`) plus source/AST
  structural checks for the parts that need a live connection. Real
  end-to-end confirmation requires an actual `workflow_dispatch` run
  during US market hours, which this ADR's own "Status of
  Implementation" section below tracks separately from the code being
  merged.

## Tests

`tests/scripts/test_verify_alpaca_paper_broker.py` (12 tests): real,
executable coverage of `_is_paper_endpoint` (paper/live/arbitrary/None)
and `_poll_until_terminal` (immediate terminal, multi-poll terminal,
timeout with a fake, duck-typed client -- using an advancing fake clock
for `time.monotonic`/`time.sleep`, the same pattern this project's own
`TwelveDataRateLimiter` tests already had to fix after a real hang
caused by a fixed-clock fake earlier in this project's history);
source/AST checks for `main()`'s network-dependent wiring (credentials
env-only, paper-endpoint guard runs before client construction, market
clock checked before any order, exactly one buy then one sell in that
order, sell quantity reads the real filled quantity not the requested
one). `tests/deploy/test_verify_alpaca_paper_broker_workflow.py` (5
tests): workflow is `workflow_dispatch`-only with no schedule,
read-only permissions, secrets wired correctly with no hardcoded
credential, the `broker-verification` extra is installed, and the
script runs with the configurable `symbol`/`qty` inputs.

## Status of Implementation at Time of This ADR

Code, tests, and workflow complete and merged. The account owner still
needs to register `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (and
`ALPACA_BASE_URL` if not using Alpaca's own default paper domain) as
GitHub repository secrets before this workflow can be triggered for
real -- this session cannot register secrets on the account owner's
behalf. Once registered, triggering `workflow_dispatch` during real US
market hours and reading the job's own logs is the next step to get
the actual, real "verified" outcome this ADR's own script is designed
to produce.
