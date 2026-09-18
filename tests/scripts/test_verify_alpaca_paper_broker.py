"""Tests for `scripts/verify_alpaca_paper_broker.py` (account owner's
own request, 2026-09-18: verify Alpaca's paper broker all the way
through a real buy->fill->sell->fill round trip, not just connectivity).

`main()` itself makes a real network call to Alpaca's paper API when
run and is therefore never imported or executed here (same "never
import/execute a real-network script" discipline
`tests/data_infra/test_ingest_real_market_data_wiring.py` already
established) -- those parts are checked via source/AST inspection.
The two pure helper functions (`_is_paper_endpoint`/
`_poll_until_terminal`) have no network dependency at all and ARE
imported and executed directly here for real, stronger coverage than
source inspection alone could give.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import time
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_alpaca_paper_broker.py"


def _source() -> str:
    return _SCRIPT_PATH.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(_SCRIPT_PATH))


def _load_module():
    """Safe to actually import -- module level only defines functions/
    constants and does an `if __name__ == '__main__'` guard; `main()`
    is never called at import time, and importing does not require
    alpaca-py to be installed (the import happens inside `main()`)."""
    spec = importlib.util.spec_from_file_location("verify_alpaca_paper_broker", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestIsPaperEndpoint:
    def test_none_is_treated_as_the_default_paper_domain(self) -> None:
        module = _load_module()
        assert module._is_paper_endpoint(None) is True

    def test_real_paper_domain_is_accepted(self) -> None:
        module = _load_module()
        assert module._is_paper_endpoint("https://paper-api.alpaca.markets") is True

    def test_live_domain_is_rejected(self) -> None:
        module = _load_module()
        assert module._is_paper_endpoint("https://api.alpaca.markets") is False

    def test_arbitrary_other_url_is_rejected(self) -> None:
        module = _load_module()
        assert module._is_paper_endpoint("https://example.com") is False


class _FakeOrder:
    def __init__(self, status: str) -> None:
        self.status = _FakeStatus(status)


class _FakeStatus:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeClient:
    """Returns a sequence of canned order statuses, one per
    `get_order_by_id` call -- the last one repeats once exhausted."""

    def __init__(self, statuses: list[str]) -> None:
        self._statuses = statuses
        self.calls = 0

    def get_order_by_id(self, order_id):
        index = min(self.calls, len(self._statuses) - 1)
        self.calls += 1
        return _FakeOrder(self._statuses[index])


class TestPollUntilTerminal:
    def test_returns_immediately_when_already_terminal(self) -> None:
        module = _load_module()
        client = _FakeClient(["filled"])
        result = module._poll_until_terminal(client, "order-1", timeout_seconds=10, interval_seconds=1)
        assert result.status.value == "filled"
        assert client.calls == 1

    def test_polls_until_a_later_terminal_status(self, monkeypatch) -> None:
        module = _load_module()
        client = _FakeClient(["new", "partially_filled", "filled"])
        # Advancing fake clock -- avoids the real hang risk of a fixed
        # clock with a sleep_fn that never advances it (a real bug this
        # project's own history already hit once with an identical
        # pattern in TwelveDataRateLimiter's tests).
        clock_value = {"t": 0.0}
        monkeypatch.setattr(time, "monotonic", lambda: clock_value["t"])
        monkeypatch.setattr(time, "sleep", lambda seconds: clock_value.__setitem__("t", clock_value["t"] + seconds))

        result = module._poll_until_terminal(client, "order-1", timeout_seconds=10, interval_seconds=1)
        assert result.status.value == "filled"
        assert client.calls == 3

    def test_gives_up_after_timeout_returning_last_known_status(self, monkeypatch) -> None:
        module = _load_module()
        client = _FakeClient(["new"])  # never reaches a terminal status
        clock_value = {"t": 0.0}
        monkeypatch.setattr(time, "monotonic", lambda: clock_value["t"])
        monkeypatch.setattr(time, "sleep", lambda seconds: clock_value.__setitem__("t", clock_value["t"] + seconds))

        result = module._poll_until_terminal(client, "order-1", timeout_seconds=5, interval_seconds=1)
        assert result.status.value == "new"
        assert client.calls > 1


class TestSourceWiring:
    """Structural checks on the parts of `main()` that need a real
    network call and are therefore never executed here."""

    def test_credentials_are_read_only_from_environment_never_a_cli_flag(self) -> None:
        source = _source()
        assert 'os.environ.get("ALPACA_API_KEY")' in source
        assert 'os.environ.get("ALPACA_SECRET_KEY")' in source
        assert "--api-key" not in source
        assert "--secret-key" not in source

    def test_refuses_a_non_paper_endpoint_before_constructing_a_client(self) -> None:
        source = _source()
        assert "_is_paper_endpoint(base_url)" in source
        construct_index = source.index("TradingClient(api_key, secret_key")
        guard_index = source.index("_is_paper_endpoint(base_url)")
        assert guard_index < construct_index

    def test_checks_the_market_clock_before_submitting_any_order(self) -> None:
        source = _source()
        clock_index = source.index("get_clock()")
        first_submit_index = source.index("submit_order(")
        assert clock_index < first_submit_index

    def test_does_a_real_buy_then_poll_then_sell_then_poll(self) -> None:
        tree = _tree()
        main_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls_in_order = [
            n.func.attr
            for n in ast.walk(main_fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        assert calls_in_order.count("submit_order") == 2
        assert calls_in_order.count("get_order_by_id") == 0  # only via the _poll_until_terminal helper
        source = _source()
        buy_index = source.index("side=OrderSide.BUY")
        sell_index = source.index("side=OrderSide.SELL")
        assert buy_index < sell_index

    def test_sell_quantity_matches_the_actual_filled_buy_quantity_not_the_requested_qty(self) -> None:
        """A partial buy fill must not be over-sold back -- this reads
        `filled_buy.filled_qty`, never `args.qty`, for the sell leg."""
        source = _source()
        sell_call_start = source.index("side=OrderSide.SELL")
        sell_call_snippet = source[max(0, sell_call_start - 200):sell_call_start]
        assert "filled_buy.filled_qty" in sell_call_snippet
