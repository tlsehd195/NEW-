"""Real, executable tests for `scripts/adr_number.py` (ADR-0221).

Each test builds a throwaway bare "origin" plus two clones standing in
for two parallel Claude sessions, so the collision scenarios are the
real git ones (two branches, same number, different file names) rather
than mocks. No network call."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "adr_number.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("adr_number", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


adr = _load_module()

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str, when: int | None = None) -> str:
    env = {**os.environ, **_GIT_ENV}
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True,
                          text=True, check=True).stdout


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit_push(repo: Path, message: str, when: int = 1_700_000_000) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message, when=when)
    _git(repo, "push", "-q", "origin", "HEAD")


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """(origin, session_a, session_b); main holds ADR-0001 and ADR-0002."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    _write(seed, "docs/decisions/ADR-0001-first.md", "# ADR-0001\n")
    _write(seed, "docs/decisions/ADR-0002-second.md", "# ADR-0002\nsee ADR-0001\n")
    _write(seed, "notes.md", "intro cites ADR-0002\n")
    _commit_push(seed, "seed")

    clones = []
    for name in ("a", "b"):
        clone = tmp_path / name
        _git(tmp_path, "clone", "-q", str(origin), str(clone))
        _git(clone, "checkout", "-q", "-b", f"claude/{name}")
        clones.append(clone)
    for key, value in _GIT_ENV.items():
        monkeypatch.setenv(key, value)
    return origin, clones[0], clones[1]


def test_next_number_counts_other_sessions_pushed_branches(sessions):
    _, a, b = sessions
    assert adr.next_number(a) == 3
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _commit_push(a, "claim 3")
    adr.fetch(b)
    # Main still tops out at 0002, but A's pushed claim is visible.
    assert adr.next_number(b) == 4


def test_create_writes_a_stub_with_a_status_field(sessions):
    _, a, _ = sessions
    path = adr.create(a, "my-thing", "My thing")
    assert path.name == "ADR-0003-my-thing.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# ADR-0003: My thing") and "**Status:** Proposed" in text


def test_check_fails_when_main_already_has_the_number(sessions):
    _, a, b = sessions
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _commit_push(a, "claim 3")
    _git(a, "push", "-q", "origin", "HEAD:main")  # A merges first
    _write(b, "docs/decisions/ADR-0003-from-b.md", "# ADR-0003\n")  # B picked from stale main
    adr.fetch(b)
    problems = adr.find_collisions(b)
    assert len(problems) == 1 and "already on main" in problems[0]
    assert adr.find_collisions(a) == []


def test_between_two_open_branches_the_earlier_claim_wins(sessions):
    _, a, b = sessions
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _commit_push(a, "claim 3", when=1_700_000_100)
    _write(b, "docs/decisions/ADR-0003-from-b.md", "# ADR-0003\n")
    _commit_push(b, "claim 3 too", when=1_700_000_200)
    adr.fetch(a)
    adr.fetch(b)
    assert adr.find_collisions(a) == []
    assert "claimed first by origin/claude/a" in adr.find_collisions(b)[0]


def test_same_file_name_on_own_or_merged_branch_is_not_a_collision(sessions):
    _, a, b = sessions
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _commit_push(a, "claim 3")
    adr.fetch(a)
    assert adr.find_collisions(a) == []


def test_duplicate_numbers_inside_one_checkout_are_reported(sessions):
    _, a, _ = sessions
    _write(a, "docs/decisions/ADR-0002-again.md", "# dup\n")
    problems = adr.find_collisions(a)
    assert any("used twice in this checkout" in p for p in problems)


def test_renumber_moves_the_file_and_only_this_branchs_citations(sessions):
    _, a, b = sessions
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _commit_push(a, "claim 3")
    _git(a, "push", "-q", "origin", "HEAD:main")

    _write(b, "docs/decisions/ADR-0003-from-b.md", "# ADR-0003: B\nsee ADR-0002\n")
    _write(b, "src_new.py", "# per ADR-0003\n")
    # A modified file: keep the pre-existing line untouched, rewrite only B's added line.
    _write(b, "notes.md", "intro cites ADR-0002\nB adds ADR-0003\n")
    _commit_push(b, "B work")
    _write(b, "uncommitted.md", "draft ADR-0003\n")
    adr.fetch(b)

    assert adr.renumber(b, 3) == 4
    decisions = sorted(p.name for p in (b / "docs/decisions").iterdir())
    assert decisions == ["ADR-0001-first.md", "ADR-0002-second.md", "ADR-0004-from-b.md"]
    assert (b / "docs/decisions/ADR-0004-from-b.md").read_text() == "# ADR-0004: B\nsee ADR-0002\n"
    assert (b / "src_new.py").read_text() == "# per ADR-0004\n"
    assert (b / "notes.md").read_text() == "intro cites ADR-0002\nB adds ADR-0004\n"
    assert (b / "uncommitted.md").read_text() == "draft ADR-0004\n"
    assert adr.find_collisions(b) == []


def test_renumber_leaves_main_citations_of_the_same_number_alone(sessions):
    _, a, b = sessions
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _write(a, "notes.md", "intro cites ADR-0002\nmain cites ADR-0003\n")
    _commit_push(a, "claim 3")
    _git(a, "push", "-q", "origin", "HEAD:main")

    _write(b, "docs/decisions/ADR-0003-from-b.md", "# ADR-0003\n")
    adr.fetch(b)
    _git(b, "merge", "-q", "origin/main")  # B brings main's ADR-0003 in
    _write(b, "notes.md", (b / "notes.md").read_text() + "B cites ADR-0003\n")

    adr.renumber(b, 3)
    assert (b / "notes.md").read_text() == (
        "intro cites ADR-0002\nmain cites ADR-0003\nB cites ADR-0004\n"
    )
    assert (b / "docs/decisions/ADR-0003-from-a.md").exists()


def test_cli_check_exit_codes(sessions, monkeypatch, capsys):
    _, a, b = sessions
    _write(a, "docs/decisions/ADR-0003-from-a.md", "# ADR-0003\n")
    _commit_push(a, "claim 3")
    _git(a, "push", "-q", "origin", "HEAD:main")
    _write(b, "docs/decisions/ADR-0003-from-b.md", "# ADR-0003\n")

    monkeypatch.chdir(b)
    assert adr.main(["check"]) == 1
    assert "already on main" in capsys.readouterr().err
    assert adr.main(["--no-fetch", "renumber", "3"]) == 0
    assert adr.main(["--no-fetch", "check"]) == 0
    assert adr.main(["--no-fetch", "next"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "0005"
