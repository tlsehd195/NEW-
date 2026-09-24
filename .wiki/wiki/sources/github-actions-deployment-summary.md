---
type: source
title: GITHUB-ACTIONS-DEPLOYMENT.md
source_path: ../docs/operations/GITHUB-ACTIONS-DEPLOYMENT.md
ingested: '2026-09-24'
created: '2026-09-24'
tags: []
---
# GITHUB-ACTIONS-DEPLOYMENT.md

**Source:** ../docs/operations/GITHUB-ACTIONS-DEPLOYMENT.md  
**Type:** .md  
**Size:** 3078 bytes  
**Ingested:** 2026-09-24

## Content Preview

# GitHub Actions scheduler: setup guide

**Decision record:** ADR-0082 (supersedes ADR-0081's Oracle Cloud VM as
the active choice). Workflow file: `.github/workflows/
paper_trading_cycle.yml`.

This is the only manual step required -- everything else runs
automatically once it's done:

## 1. Add the `MARKET_DATA_API_KEY` secret

1. In the repository on github.com: **Settings -> Secrets and
   variables -> Actions -> New repository secret**.
2. Name: `MARKET_DATA_API_KEY`. Value: your real Tiing…
