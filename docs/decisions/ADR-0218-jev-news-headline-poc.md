# ADR-0218: Jev (TypeSafe AI) news-headline PoC, pre-registered pass rule

**Status:** Accepted (PoC harness only; Jev stays unwired from every pipeline)
**Date:** 2026-09-26
**Deciders:** account owner (obtained a Jev API key, asked to run the PoC that `docs/PROJECT_STATUS.md` made a precondition), Claude Code session

**Related documents:** `docs/PROJECT_STATUS.md` (Jev on hold: "never wire
in before a PoC measures accuracy"), CLAUDE.md "Grounding Gate 배선 보류
결정" (no AI provider is wired into `ai_gateway` callers),
`scripts/run_ai_prediction_experiment.py` (same "research-only, separate
from the trading pipeline" boundary), `src/strategy_research/locked_windows.py`.

## Context

Jev is not a forecaster. Its own docs describe a "System One" classifier:
send state plus typed questions (`noul` yes/no probability, `choice`
among named options, `score` on ordered levels) to
`POST https://api.typesafe.ai/v1/systemone`, get calibrated probabilities
back. It does no multi-step reasoning, is unreliable at comparing dates,
and its training cutoff is not published. Input costs $0.042 per million
tokens, output is free, so a PoC's API cost is negligible.

The only place it could fit this project is reading text, e.g. the news
sentiment input the macro filter (ADR-0217) left without a point-in-time
source. So the question the PoC answers is: does Jev's reading of a
headline carry information about the stock's return, without leaking
what happened afterwards?

## Decision

`scripts/run_jev_news_poc.py` + `.github/workflows/jev_news_poc.yml`
(`workflow_dispatch`, key from the `JEV_API_KEY` Actions secret only):

- **Data:** FNSPID `All_external.csv` (Hugging Face, 1999-2023 news with
  UTC timestamps and ticker), streamed, filtered to
  `RESEARCH_UNIVERSE_STAGE4`, event days 2010-01-01 .. first locked
  window start minus 30 days, one headline per (symbol, event day),
  seeded year-stratified sample (default 2,000). Headlines never leave
  the runner; only aggregates are committed.
- **Point in time:** a headline at/after 20:00 UTC rolls to the next
  day. The tradable *forward* window is close(first trading day after
  the event day) to 5 trading days later, so an after-hours or date-only
  stamp can never fall inside it. A *reaction* window (close before to
  close after the event day) is reported too, but it is not tradable.
  Returns are excess over the equal-weight universe mean, from
  `adjusted_close` in the release price catalog; >50% window moves are
  dropped as bad data.
- **Three framings, separate requests:** `masked` (company names and
  tickers replaced, no date), `unmasked` (ticker + headline), `probe`
  (ticker + date + headline, asking directly whether the stock beat the
  market the next week). Jev is a 2026 model looking at 2010-2020 news,
  so any skill on the probe is memorised outcomes, i.e. look-ahead.

**Pre-registered pass rule** (all three, on the forward window):
1. masked Spearman IC, bootstrap 95% CI lower bound > 0;
2. probe IC 95% CI contains 0;
3. unmasked-minus-masked IC gap 95% CI lower bound <= 0.

PASS only makes Jev a candidate input to the news-sentiment design; it
does not wire anything. FAIL keeps it on hold. Either way the result and
this rule are recorded before anyone looks at the numbers.

## Consequences

- No provider adapter is added to `src/ai_gateway`; the script uses the
  standard library over HTTPS and imports nothing from predict/decision/
  risk/broker/ai_gateway (a test enforces this).
- The market proxy is the universe itself, not SPY, so it measures
  stock-vs-peers, which is what a selection signal needs.
- Known limits: FNSPID's publisher mix and coverage vary by year;
  headlines only (no article body); one sample of ~2,000 gives a CI
  roughly ±0.045 around the IC, so a small real effect may read as FAIL.
