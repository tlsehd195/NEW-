"""Category: Documentation metadata regression (ADR-0115, finding D-9).

The second independent review found 29 early ADRs (ADR-0016 through
ADR-0045) with no `**Status:**` field at all -- every later ADR
carries one, so its absence on these specific files was silent drift,
not a deliberate convention. This guards against the same class of
regression: every ADR file must declare a status, from now on."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DECISIONS_DIR = _REPO_ROOT / "docs" / "decisions"


def _adr_files() -> list[Path]:
    return sorted(_DECISIONS_DIR.glob("ADR-*.md"))


def test_at_least_the_known_adrs_are_present() -> None:
    # A sanity floor, not an exact count (new ADRs are added over
    # time) -- catches a glob/path mistake making this whole test file
    # vacuously pass over zero files.
    assert len(_adr_files()) >= 115


def test_every_adr_declares_a_status_field() -> None:
    missing = []
    for path in _adr_files():
        head = path.read_text(encoding="utf-8")[:2000]
        if "**Status:**" not in head:
            missing.append(path.name)
    assert not missing, f"ADR(s) missing a **Status:** field: {missing}"
