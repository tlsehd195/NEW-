"""Category: Transport Failure Test -- `TiingoHttpTransport` is the one
real, network-capable component in `data_infra.providers.tiingo`. This
file is the only place in the test suite allowed to import it, and it
never reaches the network -- `urllib.request.urlopen` is monkeypatched
in every test (ADR-0025: no automated test in this repository may ever
call the real Tiingo API)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.tiingo_budget import TiingoRequestBudget
from data_infra.providers.tiingo_transport import TiingoHttpTransport


class _FakeHTTPResponse:
    def __init__(self, status: int, body, headers: dict) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestSuccessfulRequest:
    def test_get_returns_parsed_json_array(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, [{"date": "2024-01-02", "close": "100.0"}], {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        response = transport.get("/tiingo/daily/AAPL/prices", params={"token": "x"}, timeout=5.0)
        assert response.status_code == 200
        assert response.body == [{"date": "2024-01-02", "close": "100.0"}]


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)


class TestHttpErrorMapping:
    def test_401_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 401, "Unauthorized", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_404_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 404, "Not Found", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_429_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_429_with_a_real_retry_after_header_carries_it_on_the_exception(self, monkeypatch) -> None:
        """ADR-0157: a real production 429 kept exhausting IngestionRunner's
        fixed 2s/4s/8s backoff, which has no relationship to the
        server's own actual rate-limit window -- when Tiingo tells us
        exactly how long via Retry-After, that must be preserved."""
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                "https://api.tiingo.com/x", 429, "Too Many Requests", {"retry-after": "60"}, None
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError) as excinfo:
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

        assert excinfo.value.retry_after_seconds == 60.0

    def test_429_with_no_retry_after_header_leaves_it_none(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError) as excinfo:
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

        assert excinfo.value.retry_after_seconds is None

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 500, "Internal Server Error", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)


class TestMalformedResponse:
    def test_non_json_body_yields_none_body_not_a_crash(self, monkeypatch) -> None:
        class _RawTextResponse:
            status = 200
            headers = {}

            def read(self):
                return b"not valid json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout):
            return _RawTextResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        response = transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)
        assert response.body is None
        assert response.raw_text == "not valid json"


class TestNoSecretInRequestConstruction:
    def test_token_in_query_params_never_leaks_into_headers(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            return _FakeHTTPResponse(200, [], {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        transport.get("/tiingo/daily/AAPL/prices", params={"token": "sk-real-secret-token"}, timeout=5.0)
        assert "sk-real-secret-token" in captured["url"]  # Tiingo's own documented auth mechanism is a query param
        assert "Authorization" not in captured["headers"]


class TestRequestBudget:
    """ADR-0160: `TiingoHttpTransport.get()` is the one choke point
    every real Tiingo call (price fetch, corporate actions, symbol
    metadata) passes through -- proving the budget check lives there,
    not duplicated per method."""

    def test_exhausted_budget_raises_permanent_error_before_any_network_call(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise AssertionError("must never reach the network once the budget is exhausted")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=lambda: 0.0)
        for _ in range(48):
            budget.record_request()
        transport = TiingoHttpTransport("https://api.tiingo.com", budget=budget)
        with pytest.raises(PermanentProviderError) as excinfo:
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)
        assert "budget" in str(excinfo.value).lower()

    def test_exhaustion_raises_permanent_not_transient(self, monkeypatch) -> None:
        """ADR-0157's `FallbackDataProvider` classification only stops
        `IngestionRunner` retrying when the combined dual-provider
        failure is Permanent on both sides -- a budget-exhaustion
        condition must be Permanent, never Transient, or a retry would
        be attempted against a quota that cannot recover within the
        retry window."""
        budget = TiingoRequestBudget(limit_per_hour=1, safety_margin=0, clock=lambda: 0.0)
        budget.record_request()
        transport = TiingoHttpTransport("https://api.tiingo.com", budget=budget)
        with pytest.raises(PermanentProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_a_request_within_budget_still_succeeds_normally(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, [{"date": "2024-01-02"}], {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=lambda: 0.0)
        transport = TiingoHttpTransport("https://api.tiingo.com", budget=budget)
        response = transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)
        assert response.status_code == 200
        assert budget.remaining() == 47  # one real call consumed

    def test_a_shared_budget_instance_is_consumed_across_repeated_calls(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, [], {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        budget = TiingoRequestBudget(limit_per_hour=3, safety_margin=0, clock=lambda: 0.0)
        transport = TiingoHttpTransport("https://api.tiingo.com", budget=budget)
        transport.get("/x", params={}, timeout=5.0)
        transport.get("/x", params={}, timeout=5.0)
        transport.get("/x", params={}, timeout=5.0)
        with pytest.raises(PermanentProviderError):
            transport.get("/x", params={}, timeout=5.0)

    def test_two_transport_instances_given_the_same_budget_share_one_counter(self, monkeypatch) -> None:
        """Regression for the real production gap (ADR-0160, finding
        #2): if a future change ever constructed two separate
        `TiingoHttpTransport` instances for the two real call paths,
        explicitly sharing one `TiingoRequestBudget` between them is
        what would keep the tracking real rather than fake."""
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, [], {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        shared_budget = TiingoRequestBudget(limit_per_hour=2, safety_margin=0, clock=lambda: 0.0)
        transport_a = TiingoHttpTransport("https://api.tiingo.com", budget=shared_budget)
        transport_b = TiingoHttpTransport("https://api.tiingo.com", budget=shared_budget)
        transport_a.get("/x", params={}, timeout=5.0)
        transport_b.get("/x", params={}, timeout=5.0)
        with pytest.raises(PermanentProviderError):
            transport_a.get("/x", params={}, timeout=5.0)

    def test_without_an_explicit_budget_a_default_one_is_still_enforced(self, monkeypatch) -> None:
        """Every existing call site in this repository constructs
        `TiingoHttpTransport(base_url)` with no `budget` argument -- the
        real 50/hour cap must still apply via an instance-owned
        default, not silently become unlimited."""
        call_count = {"n": 0}

        def fake_urlopen(req, timeout):
            call_count["n"] += 1
            return _FakeHTTPResponse(200, [], {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        for _ in range(48):
            transport.get("/x", params={}, timeout=5.0)
        with pytest.raises(PermanentProviderError):
            transport.get("/x", params={}, timeout=5.0)
        assert call_count["n"] == 48  # the 49th call never reached urlopen
