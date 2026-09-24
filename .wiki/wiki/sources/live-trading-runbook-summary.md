---
type: source
title: LIVE-TRADING-RUNBOOK.md
source_path: ../docs/operations/LIVE-TRADING-RUNBOOK.md
ingested: '2026-09-24'
created: '2026-09-24'
tags: []
---
# LIVE-TRADING-RUNBOOK.md

**Source:** ../docs/operations/LIVE-TRADING-RUNBOOK.md  
**Type:** .md  
**Size:** 13680 bytes  
**Ingested:** 2026-09-24

## Content Preview

# Live Trading Runbook

This document is a manual operational procedure for a human operator.
No part of it is executable by this repository's own code, and nothing
in `src/` reads this file. It exists because `broker.live.
safety_gate.evaluate_safety_gate` requires several inputs
(`LiveActivationApproval`, `SafetyGateContext`) that this repository's
own code deliberately never assembles on its own behalf — assembling
them is this document's job.

**No secret value belongs in this document. Ever…
