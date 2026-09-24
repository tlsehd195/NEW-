"""Category: documentation citation-drift regression (independent audit
finding R8-e: 24 ADR/spec citation drift instances) + Batch K's adoption
of llmwiki's broken-links/stale-entries lint pattern
(EXTERNAL_REPO_APPLICABILITY_REPORT.md, priority-2 recommendation).

Every "ADR-NNNN" or "PHASE-N" citation anywhere in this repo's tracked
text (docs, code comments, workflow YAML) must resolve to a real file
under docs/decisions/ or docs/specifications/ -- a citation to a number
that was never written, or whose file was since renamed or removed, is
exactly the drift class the audit repeatedly found by hand. This turns
that drift into a test failure instead of a manual audit finding."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_RE = re.compile(r"ADR-(\d{4})")
_PHASE_RE = re.compile(r"PHASE-(\d{1,2})\b")
_SCAN_SUFFIXES = {".md", ".py", ".yml", ".yaml"}


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [
        _REPO_ROOT / line
        for line in result.stdout.splitlines()
        if (_REPO_ROOT / line).suffix in _SCAN_SUFFIXES
    ]


def _existing_numbers(directory: Path, pattern: re.Pattern) -> set[str]:
    numbers: set[str] = set()
    for path in directory.glob("*.md"):
        match = pattern.search(path.name)
        if match:
            numbers.add(match.group(1))
    return numbers


def _citation_drift(pattern: re.Pattern, existing: set[str]) -> dict[str, list[str]]:
    broken: dict[str, list[str]] = {}
    for path in _tracked_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number in set(pattern.findall(text)):
            if number not in existing:
                broken.setdefault(number, []).append(str(path.relative_to(_REPO_ROOT)))
    return broken


def test_every_adr_citation_resolves_to_a_real_adr_file() -> None:
    existing = _existing_numbers(_REPO_ROOT / "docs" / "decisions", _ADR_RE)
    assert len(existing) >= 115  # sanity floor, matches test_adr_metadata.py's own
    broken = _citation_drift(_ADR_RE, existing)
    assert not broken, f"citations to nonexistent ADR numbers (file -> citing files): {broken}"


def test_every_phase_citation_resolves_to_a_real_phase_spec() -> None:
    existing = _existing_numbers(_REPO_ROOT / "docs" / "specifications", _PHASE_RE)
    assert len(existing) >= 18  # sanity floor: 18 PHASE specs exist as of Batch K
    broken = _citation_drift(_PHASE_RE, existing)
    assert not broken, f"citations to nonexistent PHASE numbers (number -> citing files): {broken}"
