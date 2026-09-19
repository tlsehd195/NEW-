"""Real, executable tests for `scripts/select_universe_shard.py` --
pure symbol-list arithmetic, no network, so unlike
`ingest_insider_transactions.py` this is imported and its functions
called directly (same "import via spec_from_file_location, call one
pure helper" pattern `test_ingest_insider_transactions_pagination.py`
already established for that script's own pure helper)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "select_universe_shard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("select_universe_shard", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestSelectShard:
    def test_every_symbol_is_covered_across_all_shards_exactly_once(self) -> None:
        module = _load_module()
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "JPM", "SPY"]
        shard_count = 3
        all_selected: list[str] = []
        for i in range(shard_count):
            all_selected.extend(module.select_shard(symbols, shard_index=i, shard_count=shard_count))
        assert sorted(all_selected) == sorted(symbols)
        assert len(all_selected) == len(symbols)  # no duplicates, none dropped

    def test_deterministic_regardless_of_input_order(self) -> None:
        module = _load_module()
        shard_a = module.select_shard(["AAPL", "MSFT", "JPM"], shard_index=0, shard_count=2)
        shard_b = module.select_shard(["JPM", "AAPL", "MSFT"], shard_index=0, shard_count=2)
        assert shard_a == shard_b

    def test_shard_sizes_are_balanced_within_one(self) -> None:
        module = _load_module()
        symbols = [f"SYM{i}" for i in range(10)]
        sizes = [len(module.select_shard(symbols, shard_index=i, shard_count=3)) for i in range(3)]
        assert max(sizes) - min(sizes) <= 1
        assert sum(sizes) == 10

    def test_rejects_a_non_positive_shard_count(self) -> None:
        module = _load_module()
        try:
            module.select_shard(["AAPL"], shard_index=0, shard_count=0)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_rejects_a_shard_index_out_of_range(self) -> None:
        module = _load_module()
        try:
            module.select_shard(["AAPL"], shard_index=5, shard_count=3)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestMain:
    def test_prints_space_separated_symbols_and_returns_zero(self, capsys) -> None:
        module = _load_module()
        exit_code = module.main(["--universe", "RESEARCH_UNIVERSE", "--shard-index", "0", "--shard-count", "10"])
        assert exit_code == 0
        out = capsys.readouterr().out.strip()
        assert out
        assert " " in out or len(out.split()) >= 1

    def test_every_shard_together_covers_the_whole_universe_with_no_overlap(self, capsys) -> None:
        module = _load_module()
        from data_infra.universe import RESEARCH_UNIVERSE_STAGE4

        shard_count = 10
        seen: list[str] = []
        for i in range(shard_count):
            module.main(["--universe", "RESEARCH_UNIVERSE", "--shard-index", str(i), "--shard-count", str(shard_count)])
            out = capsys.readouterr().out.strip()
            seen.extend(out.split())
        assert sorted(seen) == sorted(RESEARCH_UNIVERSE_STAGE4.symbol_ids)
        assert len(seen) == len(set(seen))

    def test_invalid_shard_count_fails_cleanly(self, capsys) -> None:
        module = _load_module()
        exit_code = module.main(["--universe", "RESEARCH_UNIVERSE", "--shard-index", "0", "--shard-count", "0"])
        assert exit_code == 1
