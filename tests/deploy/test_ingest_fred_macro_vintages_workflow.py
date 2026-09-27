"""Static checks for `ingest_fred_macro_vintages.yml` (ADR-0217): the
per-series matrix must cover exactly `MACRO_SERIES_CATALOG`, so a series
added to the catalog is never silently left out of ingestion."""
from pathlib import Path

import yaml

from data_infra.macro_models import MACRO_SERIES_CATALOG

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ingest_fred_macro_vintages.yml"


def test_matrix_matches_the_catalog_and_merge_runs_after_it() -> None:
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    matrix = doc["jobs"]["ingest"]["strategy"]["matrix"]["series"]
    assert matrix == [spec.series_id for spec in MACRO_SERIES_CATALOG]
    assert doc["jobs"]["merge"]["needs"] == "ingest"
    assert doc["permissions"] == {"contents": "read"}
