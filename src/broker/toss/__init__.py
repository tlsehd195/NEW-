"""Toss Securities Adapter -- the one `broker.protocol.BrokerAdapter`
implementation capable of a real network call, gated behind explicit
`BrokerExecutionMode.LIVE` + `BrokerConfig.live_opt_in=True` +
caller-supplied real credentials. See docs/specifications/
PHASE-13-toss-securities-adapter.md section "Toss API Verification" for
exactly what was confirmed against Toss Securities' official developer
documentation (https://developers.tossinvest.com/docs) at
implementation time (2026-08-25) versus what could not be independently
verified (the documentation host is unreachable from this environment's
network egress proxy) and is therefore left `CapabilityStatus.UNKNOWN`
rather than guessed.
"""

from __future__ import annotations
