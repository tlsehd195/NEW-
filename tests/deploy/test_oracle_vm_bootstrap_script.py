"""Consistency checks for the Oracle VM bootstrap script (ADR-0081).

This script runs on an external VM this test suite has no access to,
so there is no way to execute it here. What IS checkable without a VM:
the crontab line the script prints must stay in lockstep with the one
ADR-0075 already documents in `run_paper_trading_cycle.py`'s own
docstring -- if either drifts (e.g. a flag renamed in one but not the
other), a human copying either one verbatim would run something
subtly different from what was actually tested.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "oracle_vm_bootstrap.sh"
CYCLE_SCRIPT = REPO_ROOT / "scripts" / "run_paper_trading_cycle.py"

# Flags whose *value* must be identical between the ADR-0075 docstring
# example and this script's printed crontab line. Path-bearing flags
# (--db-path/--paper-store/--out) legitimately differ, since one is a
# generic example path and the other is a real VM path -- those are
# checked only for presence, not value equality.
SHARED_VALUE_FLAGS = ("--universe", "--start")
PRESENCE_ONLY_FLAGS = (
    "--db-path",
    "--paper-store",
    "--resume",
    "--out",
    "--end",
)


def _read(path: Path) -> str:
    assert path.exists(), f"expected file not found: {path}"
    return path.read_text()


def test_bootstrap_script_exists_and_is_executable():
    assert BOOTSTRAP_SCRIPT.exists()
    assert BOOTSTRAP_SCRIPT.stat().st_mode & 0o111, "script must be executable"


def test_bootstrap_script_invokes_the_real_cycle_script():
    text = _read(BOOTSTRAP_SCRIPT)
    assert "run_paper_trading_cycle.py" in text


def test_bootstrap_script_uses_flock_matching_adr_0075():
    text = _read(BOOTSTRAP_SCRIPT)
    assert "flock -n" in text
    assert "/tmp/paper_trading_cycle.lock" in text


def test_bootstrap_script_redirects_output_to_a_log_file():
    text = _read(BOOTSTRAP_SCRIPT)
    assert ">> " in text and "2>&1" in text


def _crontab_section(bootstrap_text: str) -> str:
    # The script prints an unrelated manual-ingest example earlier
    # (with placeholder values like <YYYY-MM-DD>) before the actual
    # crontab line -- isolate the crontab line itself so flag-value
    # comparisons don't accidentally match the placeholder example.
    marker = "Then register this crontab line"
    idx = bootstrap_text.index(marker)
    return bootstrap_text[idx:]


def _cycle_docstring_crontab_section(cycle_text: str) -> str:
    # Isolate the ADR-0075 crontab example inside the module docstring
    # rather than matching an argparse `--start` flag definition later
    # in the same file.
    marker = "30 21 * * 1-5"
    idx = cycle_text.index(marker)
    return cycle_text[idx : idx + 600]


def test_shared_flag_values_match_the_documented_crontab_line():
    bootstrap_text = _crontab_section(_read(BOOTSTRAP_SCRIPT))
    cycle_text = _cycle_docstring_crontab_section(_read(CYCLE_SCRIPT))
    for flag in SHARED_VALUE_FLAGS:
        assert flag in bootstrap_text, f"{flag} missing from bootstrap script"
        assert flag in cycle_text, f"{flag} missing from ADR-0075 docstring"

    def _value_after(text: str, flag: str) -> str:
        idx = text.index(flag) + len(flag)
        return text[idx : idx + 40].split()[0].lstrip("\\")

    for flag in SHARED_VALUE_FLAGS:
        assert _value_after(bootstrap_text, flag) == _value_after(
            cycle_text, flag
        ), f"{flag} value drifted between bootstrap script and ADR-0075 docstring"


def test_presence_only_flags_appear_in_both_places():
    bootstrap_text = _read(BOOTSTRAP_SCRIPT)
    cycle_text = _read(CYCLE_SCRIPT)
    for flag in PRESENCE_ONLY_FLAGS:
        assert flag in bootstrap_text, f"{flag} missing from bootstrap script"
        assert flag in cycle_text, f"{flag} missing from ADR-0075 docstring"


def _extract_private_clone_command(text: str) -> str:
    marker = "git -c http.extraheader"
    idx = text.index(marker)
    end = text.index("\n", idx)
    return text[idx:end]


def test_private_clone_never_embeds_the_token_in_the_clone_url():
    # ADR-0115: `git clone https://<token>@host/...` makes git persist
    # that URL, token included, into the clone's .git/config
    # permanently -- contradicting this script's own promise (and
    # ORACLE-CLOUD-DEPLOYMENT.md's) that the token is never written to
    # disk. The token must only ever reach git as a one-off `-c` value.
    clone_line = _extract_private_clone_command(_read(BOOTSTRAP_SCRIPT))
    assert "GH_TOKEN}@" not in clone_line
    assert '"$REPO_URL"' in clone_line


def test_private_clone_command_does_not_persist_the_token_to_git_config(tmp_path):
    # Real local git repo standing in for a real private GitHub remote
    # -- proves the actual clone command line this script runs never
    # writes the token to .git/config, by actually running it.
    source = tmp_path / "source"
    source.mkdir()
    for args in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(args, cwd=source, check=True)
    (source / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=source, check=True)

    dest = tmp_path / "clone"
    fake_token = "FAKE_SECRET_TOKEN_12345"
    clone_line = _extract_private_clone_command(_read(BOOTSTRAP_SCRIPT))
    script = (
        f'REPO_URL="file://{source}"\n'
        f'REPO_DIR="{dest}"\n'
        f'GH_TOKEN="{fake_token}"\n'
        f"{clone_line}\n"
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    config_text = (dest / ".git" / "config").read_text()
    assert fake_token not in config_text
