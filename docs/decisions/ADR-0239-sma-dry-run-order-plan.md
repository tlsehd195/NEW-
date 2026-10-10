# ADR-0239: SMA signal dry-run order plan (print only)

**Status:** Accepted
**Date:** 2026-10-11
**Deciders:** account owner (동동), Claude Code session

**Related documents:** ADR-0235 (SMA overlay, observe-only log), `docs/operations/LIVE-TRADING-RUNBOOK.md`, `docs/operations/LIVE-RISK-POLICY.md`

## Context

The owner chose to start real trading small with SPY held under the 10-month SMA rule: 1.5M KRW, a per-order cap raised from $1,000 to $1,200 (approved 2026-10-11 KST), then a 2-3 month dry run, then a minimum-size first order. Nothing yet turns the monthly signal into share quantities, and the Toss adapter has never been used with a real account.

## Decision

Add `src/macro_filter/order_plan.py` (pure arithmetic) and `scripts/print_sma_order_plan.py`. The script reads the last line of `sma_10m.jsonl` and prints a plan: side, shares, estimated USD notional and per-order chunks that respect the cap. No network call, no broker import, `dry_run` is always True.

- Whole shares by default; `--fractional` only after Toss fractional orders are verified (ADR-0140 is still unverified).
- The price defaults to the logged month-end close, which is an estimate, not an order price.
- The KRW/USD rate is an input the operator supplies, never fetched.
- The $1,200 cap is a script default for planning only. It is not applied to `RiskConfig`; a human passes `max_order_notional` at activation (LIVE-RISK-POLICY).

## Consequences

- At SPY near $763 and 1.4k KRW/USD, 1.5M KRW buys one whole share (about 71% invested) until fractional orders are confirmed.
- Nothing is wired into any workflow or the paper loop. The plan is compared with a hand calculation during the dry run.
- Order placement, Toss credentials and kill-switch behaviour on SELL are untouched and still need their own steps.
