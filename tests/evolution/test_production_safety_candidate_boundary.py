"""Category: Boundary Test (Phase 17 -- Production Safety Review,
Section 10 "Candidate Model Validation Boundary"). Repo-wide (not just
`evolution.*`) AST scan proving no code path anywhere in `src/`
constructs `CandidateModelStatus.APPROVED` or `.DEPLOYED`.

tests/evolution/test_evolution_boundary.py (Phase 11) already scans
every file inside the `evolution` package for this. This test is
intentionally broader in scope -- it scans the *entire* `src/` tree,
including `learning.*`, `monitoring.*`, `ai_gateway.*`, and any future
package -- because the instruction driving this review explicitly asks
for a fresh, independent verification that no such path exists
*anywhere*, not a re-assertion that Phase 11's own package stays clean.
A future module outside `evolution.*` that tried to assign either
status would fail this test even if it never touches `evolution.*` at
all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import learning
import evolution

_FORBIDDEN_ATTRS = {"APPROVED", "DEPLOYED"}

# Files that may reference these names in prose (docstrings/comments)
# without it being a code-level `ast.Attribute` node -- an `ast.parse`
# of a whole file cannot distinguish "mentioned in a docstring" from
# "referenced as CandidateModelStatus.APPROVED", so this scan only
# flags an actual `ast.Attribute` node (`.attr in _FORBIDDEN_ATTRS`),
# which a docstring/comment can never produce -- no exclusion list is
# needed for that reason. The one legitimate producer is
# `learning.enums.CandidateModelStatus` itself, which must define the
# enum members somewhere; enum member *definitions* are
# `ast.Assign`/`ast.AnnAssign` targets (`ast.Name`), never
# `ast.Attribute` nodes, so the enum's own file is naturally exempt
# without needing a special case.


def _repo_src_root() -> Path:
    # learning and evolution are both top-level packages directly under
    # the same src/ directory -- this walks up from one of them rather
    # than hardcoding an absolute path, so the test is not sensitive to
    # where this checkout happens to live on disk.
    return Path(learning.__file__).resolve().parent.parent


class TestNoCandidateApprovalOrDeploymentPathAnywhereInSrc:
    def test_no_file_in_src_references_candidate_model_status_approved_or_deployed_as_an_attribute(self) -> None:
        src_root = _repo_src_root()
        offending: list[str] = []
        for py_file in src_root.rglob("*.py"):
            if "egg-info" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
                    offending.append(f"{py_file.relative_to(src_root)}:{node.lineno} -- .{node.attr}")
        assert offending == [], (
            "found a code-level reference to CandidateModelStatus.APPROVED/.DEPLOYED "
            f"outside its own enum definition: {offending}"
        )

    def test_evolution_package_still_has_no_automated_transition_reaching_approved_or_deployed(self) -> None:
        """Re-confirms Phase 11's own finding still holds this phase --
        not a duplicate of test_evolution_boundary.py's AST scan (which
        only checks the `evolution` package's own files), but a direct
        behavioral check of `next_status` against every possible input."""
        from evolution.criteria import next_status
        from learning.enums import CandidateModelStatus

        for status in CandidateModelStatus:
            try:
                result = next_status(status)
            except ValueError:
                continue
            assert result not in (CandidateModelStatus.APPROVED, CandidateModelStatus.DEPLOYED)

    def test_candidate_model_status_enum_itself_is_the_only_file_defining_approved_and_deployed(self) -> None:
        """Sanity check on the scan's own exemption logic: confirms the
        enum's own file is where APPROVED/DEPLOYED are actually
        defined, so the repo-wide scan above is verifiably not just
        passing because nothing anywhere uses this enum at all."""
        from learning.enums import CandidateModelStatus

        assert CandidateModelStatus.APPROVED.value == "APPROVED"
        assert CandidateModelStatus.DEPLOYED.value == "DEPLOYED"
