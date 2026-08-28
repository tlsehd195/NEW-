"""Phase 30 structural regression tests for
`scripts/ingest_real_market_data.py` (instruction section 16 / section
11).

This script is deliberately never imported or executed by the
automated test suite -- it makes a real network call to a live
provider when run (see its own module docstring), which this
environment's egress is blocked from making (re-confirmed this phase).
These tests therefore work entirely on its SOURCE TEXT/AST -- never
`import` it, never call `main()` -- the same discipline
`tests/strategy_research/test_run_long_horizon_validation_wiring.py`
already established for `scripts/run_long_horizon_validation.py`.

The concrete gap this file regression-tests: the ingestion manifest
previously reported only the *requested* --start/--end, never what the
provider actually returned. A provider lacking data back to the
requested start (or lagging behind the requested end) would have been
silently indistinguishable in the manifest from a run that got exactly
what was asked for -- inviting a false "covers 2010-latest" claim
(instruction section 16: "Do NOT claim 'through today' unless data
actually reaches today's date... Do not fabricate 2010 coverage").
Fixed by computing `actual_data_start`/`actual_data_end` from the real
persisted bars' own timestamps (never the requested dates), plus an
explicit `delisted_count` (from persisted `SecurityMaster.status`) and
`data_status` field.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ingest_real_market_data.py"


def _source() -> str:
    return _SCRIPT_PATH.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(_SCRIPT_PATH))


def _manifest_dict_node(tree: ast.Module) -> ast.Dict:
    """Locates the `manifest = {...}` assignment's dict literal."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "manifest"
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise AssertionError("expected a `manifest = {...}` dict literal assignment")


def _manifest_keys(tree: ast.Module) -> set[str]:
    manifest = _manifest_dict_node(tree)
    return {k.value for k in manifest.keys if isinstance(k, ast.Constant)}


class TestManifestReportsActualDataRangeNotJustRequested:
    """The manifest must distinguish what was requested from what was
    actually observed (instruction section 16)."""

    def test_manifest_has_both_requested_and_actual_date_range_keys(self) -> None:
        keys = _manifest_keys(_tree())
        assert {"requested_start", "requested_end", "actual_data_start", "actual_data_end"} <= keys

    def test_manifest_no_longer_uses_the_old_ambiguous_start_end_keys(self) -> None:
        # The pre-Phase-30 manifest used bare "start"/"end" for the
        # *requested* range, which reads exactly like "what was
        # actually ingested" -- renamed to requested_start/requested_end
        # to remove that ambiguity rather than adding new keys beside
        # the misleading old ones.
        keys = _manifest_keys(_tree())
        assert "start" not in keys
        assert "end" not in keys

    def test_actual_data_start_is_computed_from_persisted_bars_not_requested_start(self) -> None:
        source = _source()
        assign_line = next(
            line for line in source.splitlines() if line.strip().startswith("actual_data_start = ")
        )
        assert "all_bars" in assign_line
        assert "args.start" not in assign_line

    def test_actual_data_end_is_computed_from_persisted_bars_not_requested_end(self) -> None:
        source = _source()
        assign_line = next(
            line for line in source.splitlines() if line.strip().startswith("actual_data_end = ")
        )
        assert "all_bars" in assign_line
        assert "args.end" not in assign_line


class TestManifestReportsDelistedCountAndDataStatus:
    def test_manifest_has_delisted_count_key(self) -> None:
        assert "delisted_count" in _manifest_keys(_tree())

    def test_delisted_count_is_computed_from_actual_security_master_status(self) -> None:
        source = _source()
        assign_line = next(
            line for line in source.splitlines() if line.strip().startswith("delisted_count = ")
        )
        assert "security_masters" in assign_line
        assert "SecurityStatus.DELISTED" in assign_line

    def test_manifest_declares_data_status_real(self) -> None:
        tree = _tree()
        manifest = _manifest_dict_node(tree)
        pairs = {
            k.value: v
            for k, v in zip(manifest.keys, manifest.values)
            if isinstance(k, ast.Constant)
        }
        assert "data_status" in pairs
        assert isinstance(pairs["data_status"], ast.Constant)
        assert pairs["data_status"].value == "REAL"


class TestManifestFieldsPrintedToStdout:
    """instruction section 16 explicitly asks the report to *print*
    ACTUAL_DATA_START/ACTUAL_DATA_END, not just write them to the JSON
    file a human might not open."""

    def test_actual_data_start_and_end_are_printed(self) -> None:
        source = _source()
        assert "ACTUAL_DATA_START" in source
        assert "ACTUAL_DATA_END" in source
