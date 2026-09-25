#!/usr/bin/env python3
"""Verifies `ai_gateway.providers.gemini.GeminiProviderAdapter` against a
real Gemini API call -- one `generateContent` request/response round
trip, through the real `ai_gateway.gateway.AIGateway` pipeline exactly as
`scripts/run_ai_prediction_experiment.py` uses it, but with a trivial,
fixed prompt instead of real market data (account owner's own
`GEMINI_API_KEY`, `workflow_dispatch`/manual verification tool -- same
pattern as `scripts/verify_alpaca_paper_broker.py`).

**Costs real (free-tier) Gemini quota every time it runs** -- Gemini's
own confirmed free-tier limit for this model is 5 requests/minute (see
`ai_gateway.providers.gemini_transport`'s own docstring); never put this
on a recurring schedule, only run it deliberately.

Credentials are read only from the `GEMINI_API_KEY` environment variable
(never a CLI flag, so a real secret is never visible in a process list or
shell history).

Usage:
    export GEMINI_API_KEY=...
    python3 scripts/verify_gemini_adapter.py [--model gemini-3.8-flash]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_gateway.config import GatewayConfig, ProviderConfig  # noqa: E402
from ai_gateway.enums import BillingStatus, RequestStatus, TaskTier  # noqa: E402
from ai_gateway.gateway import AIGateway  # noqa: E402
from ai_gateway.models import AIRequest  # noqa: E402
from ai_gateway.providers.gemini import DEFAULT_GEMINI_PROVIDER_CONFIG, GeminiProviderAdapter  # noqa: E402
from ai_gateway.quota_manager import QuotaManager  # noqa: E402
from ai_gateway.repository import InMemoryQuotaStateRepository  # noqa: E402
from trade_journal.enums import TradeProvenance  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None, help="override the default Gemini model")
    args = parser.parse_args(argv)

    config = DEFAULT_GEMINI_PROVIDER_CONFIG
    if args.model:
        config = ProviderConfig(
            provider_id=config.provider_id, provider_name=config.provider_name, model=args.model,
            api_key_reference=config.api_key_reference, rpm_limit=config.rpm_limit,
            rpd_limit=config.rpd_limit, tpm_limit=config.tpm_limit, tpd_limit=config.tpd_limit,
        )

    now = datetime.now(timezone.utc)
    quota_manager = QuotaManager(InMemoryQuotaStateRepository())
    quota_manager.initialize(config, at=now, billing_status=BillingStatus.CONFIRMED_FREE)
    gateway = AIGateway(
        GatewayConfig(providers=(config,)), {config.provider_id: GeminiProviderAdapter(config)}, quota_manager,
    )

    request = AIRequest(
        request_id="AIREQ-VERIFY-000001", task_tier=TaskTier.MEDIUM,
        prompt_template_id="verify_gemini_adapter", prompt_template_version="v1",
        payload="Reply with exactly one word: OK", max_tokens=50, requested_at=now,
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )
    response = gateway.generate(request, as_of=now)

    print(f"status: {response.status.value}")
    print(f"provider_id: {response.provider_id}")
    print(f"model: {response.model}")
    print(f"content: {response.content!r}")
    print(f"usage: {response.usage}")
    print(f"attempt_count: {response.attempt_count}")
    if response.status != RequestStatus.SUCCESS:
        print(f"error_reason: {response.error_reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
