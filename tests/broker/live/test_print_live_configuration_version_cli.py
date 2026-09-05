"""Session 36 continued tests for `scripts/print_live_configuration_version.py`
(ADR-0078) -- the operational tool an operator uses to compute the
hash they pin for `orchestration.live_runner.run_cycle`'s
`pinned_configuration_version` (`configuration_integrity_valid`,
ADR-0072/ADR-0074). Makes no network call and touches no real config
file, so -- like `run_paper_trading_cycle.py`'s own tests -- this is
run end to end via `main()`, not just AST-checked."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from broker.live.config import LiveTradingConfig

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "print_live_configuration_version.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("print_live_configuration_version", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestScriptIsSyntacticallyValid:
    def test_module_loads_without_error(self) -> None:
        _load_module()


class TestPrintedHashMatchesTheRealConfigurationVersion:
    def test_default_flags_match_a_default_live_trading_config(self, capsys) -> None:
        module = _load_module()
        rc = module.main([])
        assert rc == 0
        output = capsys.readouterr().out
        printed_hash = output.strip().splitlines()[-1].split(": ")[1]
        assert printed_hash == LiveTradingConfig().configuration_version()

    def test_custom_flags_match_the_equivalent_real_config(self, capsys) -> None:
        module = _load_module()
        rc = module.main([
            "--live-trading-enabled", "--max-daily-loss", "100.0",
            "--max-order-frequency-per-hour", "6", "--max-consecutive-failures", "5",
        ])
        assert rc == 0
        output = capsys.readouterr().out
        printed_hash = output.strip().splitlines()[-1].split(": ")[1]

        real_config = LiveTradingConfig(
            live_trading_enabled=True, max_daily_loss=100.0,
            max_order_frequency_per_hour=6, max_consecutive_failures=5,
        )
        assert printed_hash == real_config.configuration_version()

    def test_a_different_max_daily_loss_produces_a_different_hash(self, capsys) -> None:
        """Sanity check that this isn't a constant/vacuous hash -- a
        real, meaningfully different config produces a different one."""
        module = _load_module()
        module.main(["--max-daily-loss", "50.0"])
        first_hash = capsys.readouterr().out.strip().splitlines()[-1]

        module.main(["--max-daily-loss", "999.0"])
        second_hash = capsys.readouterr().out.strip().splitlines()[-1]

        assert first_hash != second_hash

    def test_output_includes_a_full_field_dump_not_just_a_bare_hash(self, capsys) -> None:
        """A future reader must be able to verify WHAT was pinned, not
        just trust an opaque hex string."""
        module = _load_module()
        module.main(["--max-daily-loss", "100.0"])
        output = capsys.readouterr().out
        dump = json.loads(output.rsplit("configuration_version:", 1)[0])
        assert dump["max_daily_loss"] == 100.0
