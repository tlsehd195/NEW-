---
type: source
title: TOSS-API-GAP-ANALYSIS.md
source_path: ../docs/operations/TOSS-API-GAP-ANALYSIS.md
ingested: '2026-09-24'
created: '2026-09-24'
tags: []
---
# TOSS-API-GAP-ANALYSIS.md

**Source:** ../docs/operations/TOSS-API-GAP-ANALYSIS.md  
**Type:** .md  
**Size:** 24141 bytes  
**Ingested:** 2026-09-24

## Content Preview

# Toss Securities Open API -- Adapter Gap Analysis

Phase 17 Production Safety Review, Section 6. This document exists to
answer one question honestly, per capability: **is this safe to mark
`CapabilityStatus.ENABLED` on `TossBrokerAdapter` today, or not?**

**Status as of Phase 21: all four capabilities are now implemented in
code (see "Phase 21 addendum" below), against the Tier 1 schema Phase
20 extracted -- but `TossBrokerAdapter.get_capabilities()` still
reports `CapabilityStatus.UNKNOWN` f…

## See also

- [Broker Adapter 중립성 패턴](../concepts/broker-adapter.md)
- [broker](../entities/broker.md)
