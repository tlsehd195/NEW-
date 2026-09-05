# GitHub Actions scheduler: setup guide

**Decision record:** ADR-0082 (supersedes ADR-0081's Oracle Cloud VM as
the active choice). Workflow file: `.github/workflows/
paper_trading_cycle.yml`.

This is the only manual step required -- everything else runs
automatically once it's done:

## 1. Add the `MARKET_DATA_API_KEY` secret

1. In the repository on github.com: **Settings -> Secrets and
   variables -> Actions -> New repository secret**.
2. Name: `MARKET_DATA_API_KEY`. Value: your real Tiingo API key (the
   same one you've already been using to run
   `scripts/ingest_real_market_data.py` manually).
3. Save. GitHub encrypts it; it is never visible again in the UI, only
   usable by workflow runs via `${{ secrets.MARKET_DATA_API_KEY }}`.

**Never paste this key into a chat with Claude, an issue, a commit, or
anywhere else in the repository.** The workflow file only ever
references it by name.

That's the entire manual setup -- no VM, no SSH, no account
verification. The workflow is already committed; once the secret
exists, it starts firing on its own schedule (weekdays, 22:00 UTC), or
you can trigger it immediately without waiting.

## 2. (Optional) Run it once manually to confirm it works

On the repository's **Actions** tab, select "Paper Trading Daily
Cycle" in the left sidebar, then **Run workflow** (this uses the
`workflow_dispatch` trigger already in the file) -- no need to wait for
the schedule to test it.

## 3. Checking on it later

- **Actions tab -> Paper Trading Daily Cycle**: run history, whether
  the last few runs succeeded or failed.
- Each run uploads three artifacts (visible at the bottom of that
  run's page): `market-data-catalog`, `paper-trading-store` (both
  carried forward to the next run), and
  `paper-trading-cycle-report-<run id>` (that day's own JSON report,
  downloadable directly -- no SSH needed, unlike the Oracle VM option).
- If a run fails (e.g. the provider was temporarily unreachable), the
  next scheduled run tries again from wherever the last *successful*
  artifact upload left off -- `--resume` means nothing is double
  submitted.

## Known limitations (see ADR-0082 for the full list)

- GitHub artifacts expire after 90 days; if the workflow goes that
  long without a successful run, the next run restores nothing and
  silently restarts the paper trading history from empty rather than
  erroring. Check in on the Actions tab occasionally.
- A repository with zero commits for 60 days has its scheduled
  workflows auto-disabled by GitHub; any commit resets this.
- Scheduled firing time is not exact-to-the-minute (a GitHub platform
  characteristic, not specific to this workflow).
