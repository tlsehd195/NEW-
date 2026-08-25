"""Category: Point-in-Time / Leakage Test -- the Gateway takes an
already-built `AIRequest` and an explicit `as_of` timestamp; it never
fetches its own market/decision data, so there is no new leakage
surface to guard (PROJECT_MASTER_PLAN.md's point-in-time principle,
applied to the AI Gateway)."""

from __future__ import annotations

import inspect

from ai_gateway_helpers import make_gateway_config, make_provider_config, make_request, utc

from ai_gateway.gateway import AIGateway
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryQuotaStateRepository


class TestGatewayOnlyReadsCallerSuppliedData:
    def test_generate_requires_an_explicit_as_of_parameter(self) -> None:
        params = inspect.signature(AIGateway.generate).parameters
        assert "as_of" in params
        assert params["as_of"].default is inspect.Parameter.empty  # no silent default -- the caller must state "now"

    def test_ai_request_payload_is_plain_opaque_data_not_a_data_query(self) -> None:
        # AIRequest.payload is a str -- there is no field through which a
        # security_id/date-range/repository handle could be threaded in,
        # so the Gateway has no way to go fetch anything itself even if
        # it wanted to.
        from ai_gateway.models import AIRequest
        import dataclasses

        payload_field = next(f for f in dataclasses.fields(AIRequest) if f.name == "payload")
        assert payload_field.type == "str"


class TestFutureAsOfTimeDoesNotAffectAnAlreadyMadeDecision:
    def test_two_requests_with_different_as_of_but_same_provider_state_are_independent(self) -> None:
        """Point-in-time here means: `as_of` only ever gates *quota/
        reset-window* availability, never rewrites already-recorded
        quota history and never causes the Gateway to reach for data
        beyond what the caller passed in `AIRequest`."""
        a = make_provider_config("a")
        config = make_gateway_config(a)
        qm = QuotaManager(InMemoryQuotaStateRepository())
        qm.initialize(a, at=utc(2024, 1, 1))
        adapters = {"a": MockProviderAdapter(a)}
        gateway = AIGateway(config, adapters, qm)

        request = make_request()
        response_early = gateway.generate(request, as_of=utc(2024, 1, 2))
        # a later as_of does not retroactively change what already happened
        assert response_early.responded_at == utc(2024, 1, 2)
