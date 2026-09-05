# Oracle Cloud Always Free VM: scheduler deployment guide

**Decision record:** ADR-0081. **Status:** guide for the account owner
to execute manually; no cloud resources have been created by any
Claude session.

This guide has two kinds of steps, clearly separated:

- **Part A (you do this, in a browser)** -- Oracle account/VM creation
  requires your own identity/payment verification and browser access
  that no automated agent has or should have.
- **Part B (the VM does this, via a script)** -- once you can SSH into
  the VM, `scripts/deploy/oracle_vm_bootstrap.sh` automates the rest.

## Part A: create the VM (manual, in your browser)

1. Sign up at https://www.oracle.com/cloud/free/ if you don't already
   have an Oracle Cloud account. Identity verification requires a
   payment card; Oracle's stated "Always Free" tier does not charge it
   for Always-Free-eligible resources, but **verify Oracle's current
   terms yourself before proceeding** -- free-tier terms and eligible
   shapes change over time and this guide cannot guarantee what you'll
   see is identical to what's described here.
2. In the OCI Console, create a Compute instance:
   - Shape: an "Always Free eligible" shape (at the time this guide
     was written, Oracle offered either an `VM.Standard.E2.1.Micro`
     x86 shape or an Ampere `VM.Standard.A1.Flex` ARM shape as
     Always-Free options). Pick whichever your account shows as
     Always Free eligible -- check the eligibility label in the
     console yourself; it is not this guide's place to promise a
     specific shape will still be free when you read this.
   - Image: a recent Ubuntu LTS (the bootstrap script below assumes
     Ubuntu/Debian's `apt` package manager; if you pick Oracle Linux
     instead, adapt the package-install lines to `dnf`).
   - Add your SSH public key during creation (or upload one) -- you'll
     need the matching private key to log in.
3. Under the instance's attached VCN, confirm the default security
   list allows outbound traffic (default) and inbound SSH (port 22)
   from your own IP, or from anywhere if you don't have a static IP.
   No other inbound ports are needed -- this VM only needs to reach
   *out* to fetch market data and does not serve anything.
4. Note the instance's public IP address once it's running.
5. SSH in to confirm access before continuing:
   ```
   ssh -i /path/to/your/private_key ubuntu@<public-ip>
   ```
   (username is `ubuntu` for Ubuntu images; `opc` for Oracle Linux.)

## Part B: set up the VM (scripted)

Once you can SSH in, copy the bootstrap script over and run it. From
your own machine (not the VM):

```
scp -i /path/to/your/private_key scripts/deploy/oracle_vm_bootstrap.sh ubuntu@<public-ip>:~/
ssh -i /path/to/your/private_key ubuntu@<public-ip>
```

Then, on the VM itself:

```
chmod +x oracle_vm_bootstrap.sh
./oracle_vm_bootstrap.sh
```

The script will:
1. Install system packages (`git`, `python3`, `python3-venv`).
2. Ask for the repository URL and clone it. If the repository is
   private, it will prompt you for a GitHub Personal Access Token
   (classic or fine-grained, `repo`/read-only scope is enough) --
   generate one at https://github.com/settings/tokens, and treat it
   like a password: the script never writes it to disk or to shell
   history, only into the one-time `git clone` URL for that command.
3. Create a Python virtual environment inside the clone and install
   the project (`pip install -e .`).
4. Create the `data/` directories the paper trading store and market
   data catalog need.
5. Print the exact crontab line to register (matching ADR-0075,
   with the paths substituted for this VM), and remind you to run
   `scripts/ingest_real_market_data.py` once manually first so the
   market-data catalog is populated before the first scheduled cycle
   runs.

## Registering the crontab line

The bootstrap script prints a ready-to-use line. Register it with:

```
crontab -e
```

Paste the printed line, save, and exit. Confirm it's registered with:

```
crontab -l
```

## Ongoing operation (things Oracle's free tier doesn't do for you)

- **Updating the code**: this VM's clone does not auto-update. To
  pull in new commits, SSH in and run `git pull` inside the repo
  directory, then re-run `pip install -e .` if dependencies changed.
- **Disk space**: `data/paper_trading_cycle.log` and the DuckDB store
  will grow over time. Check `df -h` occasionally; log rotation is not
  set up by the bootstrap script.
- **The VM going away**: if Oracle reclaims or suspends the instance
  (Oracle has, at various points, reclaimed idle Always-Free resources
  or suspended accounts flagged for suspected abuse -- verify Oracle's
  current policy yourself, this guide cannot track it for you), the
  scheduled runs simply stop; there is no automatic failover. Checking
  in on the VM periodically is a real, manual operational burden this
  option carries that a fully managed service would not.
