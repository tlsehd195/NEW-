# ADR-0198: External Audit P2 Findings — Batch G (Stage 7 Broker)

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195/ADR-0196/ADR-0197's audit pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`,
`docs/decisions/ADR-0196-external-audit-p2-batch-abc-2026-09-24.md`,
`docs/decisions/ADR-0197-external-audit-p2-batch-de-2026-09-24.md`,
`docs/operations/LIVE-RISK-POLICY.md`,
independent 13-stage audit report of commit `76ab684`

---

## Context

Continues the batch-by-batch processing of the audit's remaining scope.
This ADR covers Stage 7 (broker), under the same discipline: every
finding independently reproduced before being called a bug; a finding
already correctly documented as a deliberate, known limitation is
recorded as such rather than re-fixed.

## Decision

- **Alpaca paper-domain guard was a substring check, not a real domain
  check (real bug, fixed):** `scripts/verify_alpaca_paper_broker.py`'s
  `_is_paper_endpoint` used `_PAPER_DOMAIN in base_url`, which the
  module's own docstring relies on being a real guard ("a misconfigured
  `ALPACA_BASE_URL` pointing at the real live-trading domain can never
  reach this code path"). A substring check is not one: it is satisfied
  by `_PAPER_DOMAIN` appearing anywhere in the URL — as a query string
  or path component of an entirely different host
  (`https://evil.example.com/?x=paper-api.alpaca.markets`), or as a
  prefix of a look-alike hostname
  (`https://paper-api.alpaca.markets.evil.com`). Fixed by parsing the
  URL and checking the real hostname is exactly `_PAPER_DOMAIN` or a
  genuine subdomain of it.
- **`TossBrokerAdapter.submit_order` had no idempotent-replay guard
  (real bug, fixed):** `broker.mock.MockBrokerAdapter.submit_order`
  already treats a repeated `client_order_id` as "idempotent replay --
  never resubmits a logically identical order" (its own comment), but
  the real adapter used for actual Toss orders had no equivalent — a
  retried `submit_order` call (e.g. after a network timeout where Toss
  actually received and processed the first request but the response
  was lost) would place a SECOND real order against a real account.
  Fixed by adding the identical cache-and-replay pattern, keyed by
  `client_order_id`, mirroring the mock's own behavior exactly. Same
  in-process-only caveat as the adapter's pre-existing `_order_id_map`
  (a process restart loses it too — both are candidates for the same
  documented future rehydration-from-`storage/broker_repository.py`
  follow-up).
- **`required_capabilities=()` vacuously passes the broker-capability
  gate (not a new bug, already documented):** re-verified against
  `docs/operations/LIVE-RISK-POLICY.md`'s own "Batch H, independent
  audit item 2" correction, which already states plainly that the
  capability check only fails for a capability the CALLER chooses to
  require, and that no real Live driver exists yet to make that choice
  for real. Already transparently disclosed, not a silent gap.
- **`TossBrokerAdapter._order_id_map` is in-process only, lost on
  restart (not a new bug, already documented):** the adapter's own
  constructor comment already states this is a "Known limitation,
  deliberately not solved this phase," explains why (no documented Toss
  endpoint resolves `orderId` by `clientOrderId`), names the correct
  future fix (rehydrate from `storage/broker_repository.py`'s already-
  persisted `broker_responses` table), and confirms the fail-safe
  behavior (an unmapped `client_order_id` honestly reports `UNKNOWN`,
  never guessed). Nothing to fix here — already correctly documented.
- **`toss-openapi-spec-v1.2.14.json` placeholder issue:** this is a
  documentation-vs-code mismatch, not a code defect — deferred to the
  Batch K (문서 vs 코드 불일치) pass rather than fixed here.
- **`workflow_dispatch` shell interpolation (real bug, fixed, broader
  than the one file the audit named):** `verify_alpaca_paper_broker.yml`
  interpolated `${{ inputs.symbol }}`/`${{ inputs.qty }}` directly into
  a `run:` block — GitHub expands `${{ }}` BEFORE the shell ever parses
  the script, so a crafted `workflow_dispatch` input becomes literal
  shell code, not a quoted argument, with that job's real
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` secrets in scope. A repo-wide
  sweep for the same pattern (`${{ inputs.<name> }}` inside a `run:`
  block for a free `type: string` input — `type: choice`/`type:
  boolean` inputs are excluded, since GitHub itself constrains those to
  a fixed, non-attacker-controlled value set before the workflow ever
  runs) found the identical gap in 5 more workflows:
  `append_symbols_to_insider_catalog.yml`,
  `ingest_insider_transactions_full.yml`,
  `ingest_stockanalysis_wayback_delisted_prices.yml`,
  `run_full_validation.yml` (which additionally has
  `permissions: contents: write` and pushes commits, making it the
  most consequential of the six), and
  `verify_insider_transactions_ingestion.yml`. All six fixed the same
  way: the input is passed via `env:` and referenced as a shell
  variable (`$VAR`), never interpolated into the `run:` block's own
  text.

## Consequences

- A misconfigured or maliciously-crafted `ALPACA_BASE_URL` can no
  longer bypass the paper-domain guard via a substring trick.
- A retried `submit_order` call against the real Toss adapter can no
  longer place a duplicate real order.
- Six `workflow_dispatch` workflows (one named by the audit, five found
  by extending the same check repo-wide) can no longer have a
  collaborator-supplied input string executed as shell code — a real
  hardening gap given at least one of the six has write access and push
  credentials.
- A new generic regression test
  (`test_no_run_block_interpolates_a_free_string_workflow_dispatch_input_directly`
  in `tests/deploy/test_workflow_run_block_hygiene.py`) now catches this
  vulnerability class for every current and future workflow file in one
  place, mirroring the same file's existing "one consolidated scan"
  precedent for the P1-5 leaked-YAML-key bug.
- Two findings (`required_capabilities=()`, `_order_id_map` in-process
  only) were re-verified and found to already be correctly, honestly
  documented — recorded here rather than re-fixed, per this session's
  established verification discipline.
- One finding (`toss-openapi-spec-v1.2.14.json` placeholder) is a
  documentation issue, deferred to the Batch K doc-vs-code pass.
- Regression tests added: 5 (Alpaca domain-guard bypass scenarios), 1
  (Toss `submit_order` dedup), 1 generic + 4 existing-test updates
  (workflow shell-interpolation hygiene) — full suite (3734 tests)
  passes.
