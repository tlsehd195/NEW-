# ADR-0225: Half-new exam on locked windows using never-evaluated S&P 500 names

**Status:** Accepted (mechanism built; no exam taken yet). Verdict baseline amended by ADR-0228: candidate net vs buy-and-hold gross
**Date:** 2026-09-27
**Deciders:** account owner (approved the idea, 2026-09-27), Claude Code session

## Context

ADR-0222 locked 2016-07-11..2026-08-27 as TEST-1/2/3, so new research
only has 2000..2016-07-11 and the one held-out run it reserves for
finalists. ADR-0224 is adding prices for names that left the S&P 500.
Many of those names were members during the locked windows but were
never evaluated there: every locked-window run so far used the 87- or
203-name research universes, which hold today's large survivors only.

For those names, a backtest over a locked window has not been seen.
The market's overall path in that window is known, so it is not a fully
fresh test, but it is much closer to one than re-running the 203 names.
The account owner agreed to use this as a "half-new exam", on condition
that it does not weaken ADR-0222 and the 203-name results stay locked.

## Decision

`src/strategy_research/unseen_exam.py` and a new exam mode in
`scripts/run_long_horizon_validation.py`
(`--unseen-names-exam TEST-n --exam-candidates a,b`, workflow inputs
`unseen_names_exam` and `exam_candidates` in `run_full_validation.yml`).

1. **Seen names.** A name is seen for a window if it is in any named
   research universe (`data_infra.universe`), is SPY, or appears in
   `security_ids` of any committed report in `docs/research/reports/`
   whose range overlaps the window (a report with no range counts as
   overlapping every window). A renamed company counts as seen under its
   new ticker too (`sp500_ticker_renames.csv`).
2. **Exam universe.** The window's point-in-time S&P 500 members that
   have prices (ADR-0224 plumbing, each date seeing only that date's
   members, delisted holdings settled at last close), minus the seen
   names. The run refuses when nothing is left.
3. **Exam run.** `--start/--end` are replaced by the window's own
   bounds. Only the pre-registered candidates run, next to an
   equal-weight `buy_and_hold` of the same unseen names (ADR-0223
   fractional baseline), each backtested once gross and net over the
   whole window. There is no walk-forward and no tuning.
4. **Verdict**, fixed now: a candidate PASSes only if its net CAGR and
   net Sharpe both beat that same-names buy-and-hold; otherwise FAIL,
   and INVALID if either run fails the integrity checks. SPY is reported
   for context only, because the unseen names exclude today's winners
   and would make an SPY comparison unfair in both directions.
5. **Once per window.** The report carries `unseen_names_exam.window`,
   `security_ids` and the window's range. `run_full_validation.yml`
   commits it to `docs/research/reports/`, which makes a second exam on
   that window refuse and makes those names seen from then on.
6. **Everything else is unchanged.** Every other overlap with a locked
   window is still refused with no override. The exam is the one
   sanctioned use and it pins itself to the window's exact bounds.

## Consequences

- A PASS is a half-new result, not a DSR-backed validation, and it may
  not be used to tune the candidate. A FAIL is strong evidence against
  the candidate, because the names were unseen.
- The exam can only run once there are finalists (today every candidate
  is INCONCLUSIVE, see ADR-0222/0224) and once the catalog holds the
  removed names. The current Tiingo extension (ADR-0224) fetches members
  up to 2016-07-11 only, so names that joined later are missing and the
  TEST-1/TEST-2 exams would be thin; a later run with
  `member_end=2026-08-27` fills them in.
- The exam universe is smaller and skews to names that left the index,
  so its buy-and-hold will usually trail SPY. That is why the verdict is
  against the same names.
- If a run crashes before writing its report, the window is not marked
  taken. Nobody saw a result in that case, so a re-run is allowed.

## Verification

`tests/strategy_research/test_unseen_exam.py` covers the seen-name
rules, the once-per-window check and the verdict rule. The wiring tests
check that the exam refusals happen before any catalog is opened.
Locally, on the Stage 5 catalog, TEST-3 exam mode refused because all
203 catalog names are seen. A harness that treated only SPY as seen ran
the full exam path on already-seen names and an already-locked window,
so nothing new was revealed.
