"""Phase 30/31 structural regression tests for
`scripts/ingest_real_market_data.py` (Phase 30 instruction section 16 /
section 11; Phase 31 instruction section 18).

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

Phase 31 extends the same manifest with `providers_used` (which
provider actually supplied each persisted bar -- `FallbackDataProvider`
can satisfy different symbols from different underlying providers, and
the manifest never said which), `missing_symbols` (requested symbols
that came back with zero bars), `active_count`, and
`historical_universe_membership_available`/
`survivorship_mitigation_applied` (whether this run's universe actually
carried provider-confirmed listing/delisting dates, as opposed to
`delisted_count` merely reading `0` because no real dates were ever
supplied).
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


class TestManifestReportsProvidersUsedAndMissingSymbols:
    """Phase 31 (instruction section 18, questions 1/2/6): the manifest
    must say which provider(s) actually supplied data and which
    requested symbols got nothing back -- neither was previously
    derivable from the manifest alone."""

    def test_manifest_has_providers_used_and_missing_symbols_keys(self) -> None:
        keys = _manifest_keys(_tree())
        assert {"providers_used", "missing_symbols"} <= keys

    def test_providers_used_is_read_from_actual_bar_provenance_not_the_configured_provider_names(self) -> None:
        source = _source()
        assign_line = next(
            line for line in source.splitlines() if line.strip().startswith("providers_used = ")
        )
        # Must read back from the real bars' own provenance -- not from
        # a hardcoded {"tiingo", "stooq"} or from the provider objects'
        # own names, either of which could claim a provider "was used"
        # even for a symbol it actually failed to serve.
        assert "b.provenance.source" in assign_line
        assert "all_bars" in assign_line

    def test_missing_symbols_is_derived_from_actual_zero_bar_counts(self) -> None:
        source = _source()
        assign_line = next(
            line for line in source.splitlines() if line.strip().startswith("missing_symbols = ")
        )
        assert "bar_counts_by_symbol" in assign_line
        assert "== 0" in assign_line


class TestManifestReportsActiveCountAndSurvivorshipMitigationStatus:
    """Phase 31 (instruction section 18, questions 11/16/17): the
    manifest must distinguish "delisted_count is 0 because nothing was
    delisted" from "delisted_count is 0 because no real listing dates
    were ever supplied" -- the latter means no survivorship mitigation
    actually happened this run."""

    def test_manifest_has_active_count_key(self) -> None:
        assert "active_count" in _manifest_keys(_tree())

    def test_manifest_has_historical_universe_membership_and_survivorship_keys(self) -> None:
        keys = _manifest_keys(_tree())
        assert {"historical_universe_membership_available", "survivorship_mitigation_applied"} <= keys

    def test_historical_universe_membership_available_checks_real_listed_dates_not_just_universe_presence(self) -> None:
        source = _source()
        assign_line_start = source.index("historical_universe_membership_available = (")
        # Grab the full parenthesised assignment (multi-line).
        assign_block = source[assign_line_start:source.index("\n\n", assign_line_start)]
        assert "listed_from is not None" in assign_block
        assert "listed_to is not None" in assign_block

    def test_survivorship_mitigation_applied_reuses_the_same_signal_not_a_separate_optimistic_claim(self) -> None:
        tree = _tree()
        manifest = _manifest_dict_node(tree)
        pairs = {
            k.value: v
            for k, v in zip(manifest.keys, manifest.values)
            if isinstance(k, ast.Constant)
        }
        assert "survivorship_mitigation_applied" in pairs
        assert "historical_universe_membership_available" in pairs
        # Both keys must resolve to the exact same expression (a Name
        # node referencing the same variable) -- Phase 31 must not
        # introduce two independently-computed claims that could drift
        # apart and silently over-claim mitigation.
        survivorship_node = pairs["survivorship_mitigation_applied"]
        membership_node = pairs["historical_universe_membership_available"]
        assert isinstance(survivorship_node, ast.Name)
        assert isinstance(membership_node, ast.Name)
        assert survivorship_node.id == membership_node.id
