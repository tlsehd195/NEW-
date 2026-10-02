import json

from strategy_research.pbo_dsr import compute_dsr_for_all_candidates
from strategy_research.trial_ledger import compute_cumulative_dsr, load_prior_candidate_names

FOLDS = {"a": [0.10, 0.02, 0.07, 0.04], "b": [0.01, 0.03, -0.02, 0.02]}


def _write(path, names):
    path.write_text(json.dumps({"pbo_dsr_result": {"deflated_sharpe_by_candidate": dict.fromkeys(names, 0.5)}}))


def test_prior_names_union_and_ignore_bad_files(tmp_path):
    _write(tmp_path / "full-validation-1.json", ["a", "x"])
    _write(tmp_path / "full-validation-2.json", ["y"])
    (tmp_path / "full-validation-3.json").write_text("not json")
    (tmp_path / "full-validation-4.json").write_text(json.dumps({}))
    assert load_prior_candidate_names(tmp_path) == {"a", "x", "y"}


def test_cumulative_counts_only_new_prior_names(tmp_path):
    _write(tmp_path / "full-validation-1.json", ["a", "x", "y"])
    res = compute_cumulative_dsr(FOLDS, tmp_path)
    assert res["a"].num_trials == 4  # a, b + x, y (a is in current run, not double-counted)
    assert res["a"].deflated_sharpe_ratio <= compute_dsr_for_all_candidates(FOLDS)["a"].deflated_sharpe_ratio


def test_no_reports_equals_plain_dsr(tmp_path):
    assert compute_cumulative_dsr(FOLDS, tmp_path) == compute_dsr_for_all_candidates(FOLDS)
