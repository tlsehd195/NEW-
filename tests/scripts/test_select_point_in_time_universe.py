"""Real, executable tests for `scripts/select_point_in_time_universe.py`.
No network call (reads a local CSV, same real schema
`parse_ticker_intervals` already validates elsewhere in this
repository's test suite). Mirrors
`tests/scripts/test_select_delisted_candidates_since.py`'s own shape."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "select_point_in_time_universe.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("select_point_in_time_universe", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# AAA: member 2000-2010 only. BBB: two disjoint intervals (left the
# index, then rejoined) -- the real AAL-shaped case
# sp500_index_constituent_history's own docstring documents. CCC: still
# a member today (empty end_date). DDD: joined 2015, still a member.
_CSV_TEXT = """ticker,start_date,end_date
AAA,2000-01-01,2010-05-01
BBB,2005-01-01,2012-03-15
BBB,2018-06-01,
CCC,2010-01-01,
DDD,2015-01-01,2023-07-01
"""


def _write_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "sp500_ticker_start_end.csv"
    csv_path.write_text(_CSV_TEXT)
    return csv_path


class TestSelectUniverse:
    def test_real_membership_on_a_historical_date(self, tmp_path) -> None:
        # The exact capability data_infra.universe's current-membership-
        # only definitions cannot offer: AAA is not in any UniverseDefinition
        # today, but it really was an S&P 500 member on 2005-06-01 (CCC
        # had not joined yet as of this date -- its start_date is 2010-01-01).
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        result = module.select_universe(csv_path, date(2005, 6, 1))
        assert result == ["AAA", "BBB"]

    def test_a_ticker_outside_every_interval_is_excluded(self, tmp_path) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        result = module.select_universe(csv_path, date(2013, 1, 1))
        assert "AAA" not in result
        assert "BBB" not in result  # between its two real intervals
        assert result == ["CCC"]

    def test_a_ticker_with_two_disjoint_intervals_is_included_in_both(self, tmp_path) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        assert "BBB" in module.select_universe(csv_path, date(2006, 1, 1))
        assert "BBB" in module.select_universe(csv_path, date(2020, 1, 1))

    def test_current_members_are_included_for_a_recent_date(self, tmp_path) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        result = module.select_universe(csv_path, date(2026, 1, 1))
        assert result == ["BBB", "CCC"]


class TestMain:
    def test_prints_space_separated_sorted_tickers(self, tmp_path, capsys) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        exit_code = module.main(["--sp500-intervals-csv", str(csv_path), "--as-of", "2005-06-01"])
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == "AAA BBB"

    def test_no_constituents_is_fatal_not_a_silent_empty_success(self, tmp_path, capsys) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        exit_code = module.main(["--sp500-intervals-csv", str(csv_path), "--as-of", "1990-01-01"])
        assert exit_code == 1
        assert "FATAL" in capsys.readouterr().err
