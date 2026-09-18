# ADR-0166: Send a real browser User-Agent on the Discord webhook POST

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0165-discord-notification-on-missing-report.md`
(the missing-report notification this fix sits next to), `docs/decisions/
ADR-0157-tiingo-stooq-rate-limit-and-retry-after.md` (the identical
root-cause class already found and fixed for Stooq)

## Context

The account owner registered `DISCORD_WEBHOOK_URL` as a real repository
secret (ADR-0146) and triggered a real `workflow_dispatch` run
(`35347561534`) -- the first real exercise of `send_discord_message`
ever, since no earlier run had the secret set. The ingestion/paper
trading steps themselves succeeded this time (ADR-0164's follow-up
correction), producing a real report -- but the Discord notification
step then failed with `FATAL: Discord webhook send failed: HTTP Error
403: Forbidden`. This is a real HTTP response from Discord's own
infrastructure (the connection succeeded; Discord's servers responded
403), not a network/connectivity failure.

`send_discord_message` (`src/notifications/discord_webhook.py`) sent no
`User-Agent` header at all, leaving Python's default
`Python-urllib/x.y` string -- a well-known bot signature. This project
has already found and fixed the identical root-cause class twice: Stooq
(ADR-0157, a real 404 traced to the same missing-User-Agent pattern,
fixed by sending a real browser UA) and SEC EDGAR (a required
descriptive UA by policy). A generic/absent User-Agent being blocked by
a Cloudflare-fronted service (Discord's API sits behind Cloudflare) is
the same category of failure, not a novel one.

**Honesty about evidence tier**: this session's own egress blocks
`discord.com` entirely (confirmed directly, `curl` returns a 403 CONNECT
rejection from this environment's own proxy, unrelated to Discord's real
response) -- the User-Agent hypothesis cannot be independently verified
from here the way ADR-0157's Stooq fix could eventually be re-verified
against a real run. This fix is applied on the strength of this
project's own precedent, not a confirmed root cause, and is recorded as
such rather than overstated.

## Decision

`send_discord_message` now sends a real, current desktop-browser
`User-Agent` header (the same string `StooqHttpTransport` already uses,
ADR-0157) alongside the existing `Content-Type: application/json`. No
other change to the request (method, body shape, timeout, error
handling all unchanged).

## Consequences

### Positive

- If the User-Agent hypothesis is correct, this closes the real gap
  found in the first real exercise of this code path: the one channel
  ADR-0146/ADR-0165 exist for was still failing to reach Discord even
  after both of those fixes landed.
- Reuses this project's own already-verified real browser UA string
  (`StooqHttpTransport`'s) rather than inventing a new one.

### Negative / Trade-offs

- **Not independently confirmed** -- see "Honesty about evidence tier"
  above. If a real re-run still returns 403 after this fix, the real
  cause is something else (e.g. the webhook URL/token itself being
  invalid, or a Discord/Cloudflare-side block unrelated to User-Agent)
  and must be re-diagnosed from the next real run's own error, not
  assumed to be this same fix applied incorrectly.

## Tests

New `test_sends_a_real_browser_user_agent_not_the_default_urllib_one` in
`tests/notifications/test_discord_webhook.py::TestSendDiscordMessage`:
confirms a real `User-Agent` header is sent and is not the default
`python-urllib` string. Full suite re-run: see `docs/PROJECT_STATUS.md`'s
session log for the exact before/after counts.

## Status of Implementation at Time of This ADR

Code and tests complete. Requires a real scheduled/`workflow_dispatch`
run against the real Discord webhook to confirm the 403 is actually
resolved -- this session's own egress cannot make that call directly.
