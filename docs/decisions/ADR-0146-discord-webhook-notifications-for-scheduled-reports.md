# ADR-0146: Discord Webhook Notifications for Scheduled Reports

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `.github/workflows/paper_trading_cycle.yml` (ADR-0082,
the one workflow this ADR's new step is wired into)

---

## Context

The account owner uploaded 12 external AI-generated evaluation reports of
this project and, reading them, raised a list of their own ideas. Among
them: "페이퍼 트레이딩 데일리 사이클 이거 클로드앱으로 보내는게 아니라
디스코드로도 보넬 수 있으면 좋겠어 페이퍼 트레이딩 저거 말고도 다른 보고
같은거 전부 디스코드로 받을 수 있게 만들 고 싶어" (send the Paper Trading
Daily Cycle report to Discord, not only through the Claude app -- and route
every other report to Discord too). Confirmed against the actual pipeline
before writing anything: `scripts/run_paper_trading_cycle.py` already
writes a real per-run JSON report (`--out`), and
`.github/workflows/paper_trading_cycle.yml` already uploads it as a
GitHub Actions artifact on its own daily schedule -- but nothing then
pushes it anywhere; the account owner has been reaching it only by asking
this conversation to fetch/read that artifact. No other report in this
repository runs on its own unattended schedule yet (`.github/workflows/`
has exactly one report-producing workflow) -- every other report the
account owner mentioned (paper performance, weekly evaluation, learning
cycle) is still run interactively, so there is no second report file to
wire up today.

## Decision 1 -- One pure formatter per report shape, one real network call, kept separate

`src/notifications/discord_webhook.py` splits into:
- `format_paper_trading_cycle_report(report: dict) -> str` -- pure,
  reads every field with `.get()` and skips the corresponding line when
  absent, never defaulting to `0`/`"unknown"` (matches this project's
  "never fabricate a missing value" rule; the report's own `--resume`
  "nothing new to process" early-exit shape genuinely carries fewer
  keys than a full run, and the formatter must render that honestly).
- `truncate_for_discord` -- pure, enforces Discord's own real documented
  webhook `content` limit (2000 characters; exceeding it is a real HTTP
  400 from Discord's API, not a style choice this module invented).
- `send_discord_message(webhook_url, content)` -- the one real network
  call (a POST to a real Discord webhook URL, via `urllib.request`,
  matching this project's existing no-extra-dependency convention for
  small outbound HTTP calls -- see `scripts/convert_sec_13f_filings_to_
  combined_csv.py`'s OpenFIGI call). Raises on any transport error or
  unexpected response rather than swallowing it, so a failed
  notification is a real, visible failure for the caller.

`scripts/send_discord_notification.py` is the CLI: reads a report JSON
file, dispatches to the right formatter by `--report-type`, and sends
the result. Its `_FORMATTERS` dict is deliberately the one place a
future report type gets registered -- adding Discord delivery for
another scheduled report later needs one new formatter function plus
one new dict entry, never a new network path.

## Decision 2 -- Wired into `paper_trading_cycle.yml` only, guarded by the secret's own presence

Added one new step, `Send Discord notification`, after the existing
report-upload step, gated on `secrets.DISCORD_WEBHOOK_URL != ''` so
merging this change does not require the secret to already exist --
the step is silently skipped (not failed) until the account owner
creates a real Discord webhook (Discord's own channel "Integrations ->
Webhooks" UI) and adds it as a `DISCORD_WEBHOOK_URL` repository secret.
Both of those are actions only the account owner can take (a browser
UI on Discord's own site and GitHub's own repo settings) -- recorded as
a deferred, account-owner-only action item, not something this session
can do on their behalf.

Not wired into any other workflow: no other workflow exists yet to wire
it into (Decision statement above).

## Consequences

### Positive

- The Paper Trading Daily Cycle report now has a real, code-complete
  path to Discord -- the account owner no longer needs to ask this
  conversation to fetch the GitHub Actions artifact by hand, once the
  one remaining account-owner action (webhook + secret) is done.
- The formatter/network split and the `_FORMATTERS` registry make
  adding the next scheduled report (once one exists) a small, isolated
  change.

### Negative / Trade-offs

- Still gated on an account-owner action this session cannot perform
  (creating the Discord webhook, adding the repo secret) -- until then
  the new workflow step is a documented no-op, not a completed delivery
  path.
- Every other report the account owner mentioned (paper performance,
  weekly evaluation, learning cycle) has no unattended schedule to hang
  a Discord step off of yet -- this ADR only adds the one channel this
  repository can actually exercise today.

## Tests

`tests/notifications/test_discord_webhook.py` (formatter shapes,
truncation, mocked-`urlopen` send success/failure -- `urllib.request.
urlopen` monkeypatched exactly as `tests/data_infra/test_sec_edgar_
transport.py` already does, per ADR-0025's "no automated test may call
a real external provider" rule) and `tests/scripts/test_send_discord_
notification_cli.py` (CLI argument/exit-code behavior, same mocking).
43 new tests. Full suite re-run clean after these changes.

## Status of Implementation at Time of This ADR

Code, tests, and the workflow wiring are complete and committed. The
account-owner-only remaining step (create the Discord webhook, add
`DISCORD_WEBHOOK_URL` as a repository secret) has not been done this
session -- recorded for the account owner, not performed here.
