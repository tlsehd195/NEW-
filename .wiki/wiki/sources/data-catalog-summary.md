---
type: source
title: data-catalog.md
source_path: ../docs/architecture/data-catalog.md
ingested: '2026-09-24'
created: '2026-09-24'
tags: []
---
# data-catalog.md

**Source:** ../docs/architecture/data-catalog.md  
**Type:** .md  
**Size:** 6104 bytes  
**Ingested:** 2026-09-24

## Content Preview

# Data Catalog — Phase 1

Referenced from `docs/specifications/PHASE-1-data-infrastructure.md` §18.
Lists every dataset the system knows about as of Phase 1. All entries
below are **mock/reference datasets** used to validate the Data
Infrastructure design and test suite — none is a real external data
source (see ADR-0005).

---

## `mock_ohlcv_us_equity`

| Field | Value |
|---|---|
| dataset_id | `mock_ohlcv_us_equity` |
| description | Deterministic mock daily OHLCV bars for a small set of US …

## See also

- [Additive Phase Boundary Architecture](../concepts/additive-phase-boundary-architecture.md)
- [data_infra](../entities/data-infra.md)
- [backtest](../entities/backtest.md)
