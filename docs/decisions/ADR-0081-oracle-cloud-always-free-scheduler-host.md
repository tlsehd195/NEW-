# ADR-0081: Oracle Cloud Always Free VM chosen as the scheduler host

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0075 documented the crontab line needed to run
`scripts/run_paper_trading_cycle.py --resume` on a schedule, but
deliberately left "where does this crontab actually run" out of scope
("this project has no server of its own to run one on"). Two free
options were compared with the account owner: a GitHub Actions
scheduled workflow, and an Oracle Cloud "Always Free" tier VM.

The deciding factor was **state persistence**. `--paper-store` is a
DuckDB file that must accumulate real history across every scheduled
run. GitHub Actions runners are ephemeral -- each scheduled run starts
from a fresh checkout with no disk left over from the previous run --
so using it would require a new, currently-undesigned mechanism to
carry the DuckDB file between runs (committing it back to the repo,
Actions artifacts/cache, or an external store), on top of known
scheduling-precision and 60-day-inactivity auto-disable caveats.

A real VM has a persistent disk by construction: the file just stays
where the crontab line already assumes it stays. The account owner
chose this option.

## Decision

Host the scheduler on an Oracle Cloud "Always Free" tier compute
instance, running the exact crontab line ADR-0075 already documents,
unchanged.

**What this session can and cannot do:** creating the Oracle Cloud
account, verifying identity/payment method, and provisioning the VM
instance itself are steps only the account owner can perform (they
require interactive web-console access and account credentials this
agent does not have and must not ask for). This session's part is:
document those human steps precisely (`docs/operations/
ORACLE-CLOUD-DEPLOYMENT.md`), and provide an automated bootstrap script
(`scripts/deploy/oracle_vm_bootstrap.sh`) for everything on the VM that
*can* be scripted -- package install, repository clone, Python
environment setup, and printing the exact crontab line to register.

## What this does NOT do

Does not provision any cloud infrastructure (no API calls to Oracle
Cloud were made or could be made from this session). Does not change
`run_paper_trading_cycle.py` or its documented crontab line -- the
scheduler's own behavior is unchanged, only its hosting. Does not
activate Live trading (still blocked by item B, `TOSS-API-GAP-
ANALYSIS.md`, unrelated to this decision).

## Tests

The bootstrap script itself cannot be executed here (it runs on a VM
this session cannot reach), so its actual VM-side behavior is verified
manually by the account owner. What `tests/deploy/
test_oracle_vm_bootstrap_script.py` does check without a VM: the
crontab line the script prints stays byte-for-byte consistent with the
one ADR-0075 already documents in `run_paper_trading_cycle.py`'s
docstring (shared flag values, `flock -n` usage, log redirection) --
catching drift if either is edited without the other.
