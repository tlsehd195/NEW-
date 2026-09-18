#!/usr/bin/env python3
"""Real market data ingestion CLI (Phase 23, instruction section 6).

This script exists because this development environment's outbound
network is blocked to every market-data provider domain (confirmed this
session: `api.tiingo.com`, `stooq.com`, `api.twelvedata.com`,
`www.alphavantage.co` all return a 403 CONNECT rejection at the egress
proxy -- see `docs/operations/MARKET-DATA-PROVIDER.md`'s Phase 23
section). It is NEVER executed by this repository's own automated test
suite, and it makes a REAL network call when run -- run it only in an
environment with real internet access, with a real Tiingo API key set
in `MARKET_DATA_API_KEY`, a real Twelve Data API key set in
`TWELVEDATA_API_KEY`, and a real Alpha Vantage API key set in
`ALPHAVANTAGE_API_KEY` (never pass a key on the command line or write
one into a file).

Every module this script imports (`TiingoDataProvider`,
`TwelveDataDataProvider`, `AlphaVantageDataProvider`,
`FallbackDataProvider`, `IngestionRunner`, `DuckDBDataRepository`,
`DataQualityFramework`) already exists and is already covered by this
repository's own fixture-based test suite (Phase 20-22, ADR-0164) --
this script performs no new data-handling logic itself, it only wires
those exact, unmodified pieces together against a real network and a
real on-disk DuckDB catalog.

Usage:
    export MARKET_DATA_API_KEY=<your real Tiingo API key>
    export TWELVEDATA_API_KEY=<your real Twelve Data API key>
    export ALPHAVANTAGE_API_KEY=<your real Alpha Vantage API key>
    python3 scripts/ingest_real_market_data.py \\
        --start 2024-01-02 --end 2024-06-28 \\
        --db-path ./data/real_market_data

Every provider call's `end` date is exactly what you pass on the command
line -- this script never reads wall-clock time to decide what "now" is,
so re-running it with the same arguments against a fresh database
directory is expected to be reproducible up to whatever the providers
themselves return differently over time (a real, external fact this
script cannot control, and does not attempt to hide -- see the
manifest's `note` field).

**Phase 24 update**: `--universe` selects a named, versioned
`UniverseDefinition` from `src/data_infra/universe.py`
(`PILOT_UNIVERSE` or `RESEARCH_UNIVERSE`, default `PILOT_UNIVERSE`)
instead of a symbol list hardcoded in this script -- the benchmark
symbol (`SPY`) is always additionally ingested and always tracked
separately from the universe's own tradeable membership (instruction
section 32). `--symbols` remains available as an explicit override for
ad-hoc runs. The script now also populates `SecurityMaster`/
`UniverseMembership` records for the selected universe (previously it
only wrote price bars), and records a content checksum
(`data_infra.versioning.compute_data_version`, unmodified) in the
manifest for reproducibility tracking.

**Phase 24 follow-up (found via a real ingestion run)**: this script
now also fetches and persists `CorporateAction` records (splits/
dividends) via `TiingoDataProvider.fetch_corporate_actions`/
`normalize_corporate_actions` -- both already existed and were already
covered by this repository's own fixture-based tests (Phase 20), they
were simply never called from this script. Without them, a real
position held across a real split date (e.g. NVDA's June 2024 10-for-1,
AVGO's July 2024 10-for-1, WMT's February 2024 3-for-1 -- all three
observed as `impossible_price_movement` WARNINGs on a real run of this
script) would mark-to-market against raw `close` with no offsetting
share-count adjustment, producing a spurious large paper loss at the
split date even though `adjusted_close` (used for signal generation)
was never wrong. Corporate actions are Tiingo-only (neither Twelve
Data nor Alpha Vantage implement corporate-action fetching either,
`metadata()["supports_corporate_actions"] == False` on both, ADR-0164 --
same reasoning ADR-0028 already gave for Stooq, the secondary this
chain used before it) -- fetched directly from the `tiingo` provider
instance below, not through `FallbackDataProvider` (which only exposes
the shared `DataProvider` Protocol, deliberately not extended for this).

**Phase 30 fix**: the manifest previously reported only the *requested*
`start`/`end` -- it never recorded what the provider actually returned.
A provider that lacks data back to the requested start, or lags behind
the requested end, would previously be indistinguishable in the
manifest from a run that got exactly what was asked for, silently
inviting a false "covers 2010-latest" claim (instruction section 16:
"Do NOT claim 'through today' unless data actually reaches today's
date... Do not fabricate 2010 coverage"). The manifest now also reports
`actual_data_start`/`actual_data_end` (computed from the real persisted
bars' own timestamps, `None` when no bars were persisted), an explicit
`delisted_count` (from the persisted `SecurityMaster` records' actual
`status`, not assumed), and an explicit `data_status: "REAL"` field
(this script only ever performs a real, network-backed ingestion --
unlike `run_long_horizon_validation.py`, which accepts synthetic
fixtures too and therefore needs a caller-supplied flag).

**Phase 31 fix**: the manifest still couldn't answer several of the
questions a reproducibility manifest must answer (instruction section
18) -- which provider(s) actually supplied data (`FallbackDataProvider`
can satisfy different symbols from different underlying providers, and
the manifest never said which), which requested symbols came back with
zero bars, how many of the universe's securities are still active vs.
delisted, and whether this run's universe carried real,
provider-confirmed listing/delisting dates or only ever used the
uniform fallback `valid_from` (i.e. whether any actual survivorship
mitigation happened, as opposed to `delisted_count` merely reading `0`
because no real dates were ever supplied). Added `providers_used`
(read back from each persisted bar's own `provenance.source`, never
assumed), `missing_symbols`, `active_count`, and
`historical_universe_membership_available`/
`survivorship_mitigation_applied` (both derived from whether any
`SymbolMetadata` in the run's universe actually had a confirmed
`listed_from`/`listed_to`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import IngestionRunner, PermanentProviderError, TransientProviderError  # noqa: E402
from data_infra.providers.alphavantage import AlphaVantageDataProvider  # noqa: E402
from data_infra.providers.alphavantage_config import DEFAULT_ALPHAVANTAGE_CONFIG  # noqa: E402
from data_infra.providers.alphavantage_transport import AlphaVantageHttpTransport  # noqa: E402
from data_infra.providers.fallback import FallbackDataProvider  # noqa: E402
from data_infra.providers.tiingo import TiingoDataProvider  # noqa: E402
from data_infra.providers.tiingo_config import DEFAULT_TIINGO_CONFIG  # noqa: E402
from data_infra.providers.tiingo_transport import TiingoHttpTransport  # noqa: E402
from data_infra.providers.twelvedata import TwelveDataDataProvider  # noqa: E402
from data_infra.providers.twelvedata_config import DEFAULT_TWELVEDATA_CONFIG  # noqa: E402
from data_infra.providers.twelvedata_transport import TwelveDataHttpTransport  # noqa: E402
from data_infra.quality import DataQualityFramework  # noqa: E402
from data_infra.enums import DataQualityRunStatus, DataQualitySeverity, SecurityStatus  # noqa: E402
from data_infra.universe import (  # noqa: E402
    BENCHMARK_SYMBOL,
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE4,
    build_security_masters,
    build_universe_memberships,
)
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

# "RESEARCH_UNIVERSE" always resolves to the LATEST populated stage
# (Stage 2 as of this change) -- same convention "PILOT_UNIVERSE"
# already uses for PILOT_UNIVERSE_V1. Stage 1 remains importable from
# `data_infra.universe` for historical reference (it is what the
# user's first real 76-fold walk-forward run above was NOT run
# against -- that run used PILOT_UNIVERSE only).
_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE", help="Named universe from src/data_infra/universe.py (default: PILOT_UNIVERSE). SPY is always additionally ingested as the benchmark, tracked separately.")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely (advanced/ad-hoc use)")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date, YYYY-MM-DD -- also used as the ingestion's available_time/as_of reference; never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog + Parquet store (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/ingestion_manifest.json)")
    args = parser.parse_args()

    manifest_path = args.manifest_out or (args.db_path / "ingestion_manifest.json")

    if args.symbols is not None:
        universe = None
        symbols = list(args.symbols)
    else:
        universe = _UNIVERSES[args.universe]
        symbols = list(universe.symbol_ids) + [BENCHMARK_SYMBOL]

    # ADR-0160: exactly one TiingoHttpTransport is constructed here and
    # reused by both real call paths below (FallbackDataProvider's
    # IngestionRunner-driven fetch(), and the direct
    # fetch_corporate_actions loop further down) -- this is what makes
    # TiingoRequestBudget's proactive 50/hour tracking shared between
    # them for free. Do not construct a second TiingoHttpTransport for
    # either path without explicitly sharing its budget.
    tiingo = TiingoDataProvider(DEFAULT_TIINGO_CONFIG, TiingoHttpTransport(DEFAULT_TIINGO_CONFIG.base_url))
    # ADR-0164: Stooq (the original secondary, ADR-0025) is a confirmed
    # permanent dead end (ADR-0160 -- a JS bot-verification challenge
    # page on every real request, not fixable via headers) and is no
    # longer constructed here at all. Twelve Data and Alpha Vantage
    # extend this into a flat 3-tier chain in one FallbackDataProvider
    # (widened to accept any number of providers, ADR-0164 -- nesting
    # two instances was tried first and found to corrupt provenance/
    # crash normalize(), see that module's own docstring) -- Tiingo's
    # real ~48/hour budget cap (ADR-0160) hands off to Twelve Data (real
    # free-tier cap ~800/day, verified against a real response) for the
    # remainder of RESEARCH_UNIVERSE's 87 symbols, with Alpha Vantage
    # (real free-tier cap ~25/day, likewise verified) as a third-tier
    # safety net only reached when both of the first two fail for a
    # given symbol.
    twelvedata = TwelveDataDataProvider(DEFAULT_TWELVEDATA_CONFIG, TwelveDataHttpTransport(DEFAULT_TWELVEDATA_CONFIG.base_url))
    alphavantage = AlphaVantageDataProvider(DEFAULT_ALPHAVANTAGE_CONFIG, AlphaVantageHttpTransport(DEFAULT_ALPHAVANTAGE_CONFIG.base_url))
    provider = FallbackDataProvider(tiingo, twelvedata, alphavantage)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    try:
        security_masters = []
        if universe is not None:
            security_masters = build_security_masters(universe, valid_from=args.start)
            for record in security_masters:
                repository.add_security(record)
            for record in build_universe_memberships(universe, valid_from=args.start):
                repository.add_universe_membership(record)

        runner = IngestionRunner(provider, repository)
        result = runner.run(symbols, args.start, args.end)

        corporate_action_results = []
        all_actions = []
        for symbol in symbols:
            try:
                raw_actions = tiingo.fetch_corporate_actions(symbol, args.start, args.end)
                actions = tiingo.normalize_corporate_actions(
                    symbol, raw_actions, retrieved_at=args.end, ingestion_time=args.end
                )
                for action in actions:
                    repository.add_corporate_action(action)
                all_actions.extend(actions)
                corporate_action_results.append({"security_id": symbol, "count": len(actions), "error": None})
            except (TransientProviderError, PermanentProviderError) as exc:
                corporate_action_results.append({"security_id": symbol, "count": 0, "error": str(exc)})

        quality = DataQualityFramework()
        all_bars = []
        for symbol in symbols:
            # include_quality_rejected=True: this manifest's own bar
            # counts/checksum/actual_data_start-end must reflect
            # literally everything this run persisted, never silently
            # under-reporting because an EARLIER run's CRITICAL flag
            # happens to fall inside this run's own [--start, --end]
            # window (get_bars() would otherwise exclude it by default --
            # see DuckDBDataRepository.get_bars's own docstring).
            all_bars.extend(
                repository.get_bars(
                    symbol, args.start, args.end, as_of_time=args.end, include_quality_rejected=True
                )
            )
        quality_run = quality.run(
            all_bars, dataset="phase24_real_ingestion", data_version="real-run",
            known_security_ids=set(symbols), as_of_now=args.end, corporate_actions=all_actions,
        )
        # Session 37 (real-data DQ gap): previously this run's own DQ
        # findings were written to the manifest and then never consulted
        # again by anything -- a CRITICAL-severity finding (data
        # corruption, e.g. a non-finite price) did not stop that bar from
        # being served to Paper Trading the same day, and this script's
        # own exit code ignored quality_run.status entirely. Persisting
        # here implements Phase 1 spec section 3.1's QUALITY_REJECTED/
        # QUALITY_FLAGGED states: DuckDBDataRepository.get_bars() now
        # excludes a CRITICAL-flagged bar by default (see that method's
        # own docstring) for every consumer reading from this same
        # catalog, starting immediately after this call.
        quality_rows_written = repository.record_quality_issues(quality_run)
        severity_counts = {sev.value: 0 for sev in DataQualitySeverity}
        for issue in quality_run.issues:
            severity_counts[issue.severity.value] += 1

        checksum = compute_data_version(
            {
                "symbols": sorted(symbols),
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "per_symbol_bar_counts": {
                    symbol: sum(1 for b in all_bars if b.security_id == symbol) for symbol in sorted(symbols)
                },
                "per_symbol_corporate_action_counts": {
                    symbol: sum(1 for a in all_actions if a.security_id == symbol) for symbol in sorted(symbols)
                },
            }
        )

        # Phase 30 (instruction section 16): the requested --start/--end is
        # not necessarily what the provider actually returned (a provider
        # may not have data reaching back to the requested start, or may
        # lag behind the requested end) -- report what was ACTUALLY
        # observed, computed from the real persisted bars, never assumed
        # equal to the request. `None` (not the requested date) when no
        # bars were persisted at all, so a caller cannot mistake "no data"
        # for "data exactly matching the request".
        actual_data_start = min((b.timestamp for b in all_bars), default=None)
        actual_data_end = max((b.timestamp for b in all_bars), default=None)
        delisted_count = sum(1 for s in security_masters if s.status == SecurityStatus.DELISTED)
        active_count = len(security_masters) - delisted_count if security_masters else None

        # Phase 31 (instruction section 18, questions 1/2/6/16/17): which
        # provider(s) actually supplied a bar (never assumed -- read back
        # from each persisted bar's own `provenance.source`, since
        # FallbackDataProvider may satisfy different symbols from
        # different underlying providers); which requested symbols got
        # zero bars; and whether this run's universe carried real,
        # provider-confirmed listing/delisting dates (Phase 29's
        # `SymbolMetadata.listed_from`/`listed_to`) or only the uniform
        # caller-supplied `valid_from` fallback -- the latter means no
        # actual survivorship mitigation happened this run, even if
        # `delisted_count` is 0.
        providers_used = sorted({b.provenance.source for b in all_bars})
        bar_counts_by_symbol = {symbol: 0 for symbol in symbols}
        for b in all_bars:
            bar_counts_by_symbol[b.security_id] = bar_counts_by_symbol.get(b.security_id, 0) + 1
        missing_symbols = sorted(symbol for symbol, count in bar_counts_by_symbol.items() if count == 0)
        historical_universe_membership_available = (
            any(s.listed_from is not None or s.listed_to is not None for s in universe.symbols)
            if universe is not None
            else None
        )

        manifest = {
            "note": (
                "This manifest describes a real ingestion run against live "
                "provider APIs. Bar counts and quality findings reflect "
                "whatever the providers actually returned at run time -- "
                "they are NOT reproduced or asserted by this repository's "
                "own test suite, which never makes real network calls."
            ),
            "data_status": "REAL",
            "universe_name": universe.name if universe is not None else None,
            "universe_version": universe.version if universe is not None else None,
            "symbols": list(symbols),
            "symbol_count": len(symbols),
            "active_count": active_count,
            "delisted_count": delisted_count,
            "missing_symbols": missing_symbols,
            "providers_used": providers_used,
            "historical_universe_membership_available": historical_universe_membership_available,
            "survivorship_mitigation_applied": historical_universe_membership_available,
            "requested_start": args.start.isoformat(),
            "requested_end": args.end.isoformat(),
            "actual_data_start": actual_data_start.isoformat() if actual_data_start is not None else None,
            "actual_data_end": actual_data_end.isoformat() if actual_data_end is not None else None,
            "db_path": str(args.db_path),
            "ingestion_run_id": result.run_id,
            "ingestion_status": result.status.value,
            "per_symbol_results": [
                {"security_id": r.security_id, "status": r.status.value, "bars_ingested": r.bars_ingested, "error": r.error}
                for r in result.results
            ],
            "total_bars_persisted": len(all_bars),
            "data_quality_status": quality_run.status.value,
            "data_quality_issue_count": len(quality_run.issues),
            "data_quality_severity_counts": severity_counts,
            "data_quality_flags_persisted": quality_rows_written,
            "data_quality_issues": [
                {"check": i.check, "severity": i.severity.value, "security_id": i.security_id, "message": i.message}
                for i in quality_run.issues
            ],
            "corporate_actions_persisted": len(all_actions),
            "corporate_actions_per_symbol": corporate_action_results,
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"Ingestion status: {result.status.value}")
        print(f"Total bars persisted: {len(all_bars)}")
        print(f"ACTUAL_DATA_START: {manifest['actual_data_start']}")
        print(f"ACTUAL_DATA_END: {manifest['actual_data_end']}")
        print(f"Active securities: {active_count}")
        print(f"Delisted securities in universe: {delisted_count}")
        print(f"Missing symbols (zero bars): {missing_symbols}")
        # Session 37 (real-data ingestion gap): a symbol can have a
        # non-SUCCESS per-symbol IngestionResult (e.g. a transient
        # provider error partway through) while still ending up with
        # bars_ingested > 0 -- such a symbol never appears in
        # `missing_symbols` (that list is computed from FINAL zero-bar
        # counts, not from status), so a run like this could go PARTIAL_
        # SUCCESS with an empty missing_symbols list and no visible
        # explanation anywhere in CI logs. The full per-symbol detail
        # (status/error) only ever lived in this manifest, which is a
        # GitHub Actions artifact behind Azure Blob Storage this
        # environment's own egress proxy cannot reach -- this line makes
        # "why was this PARTIAL_SUCCESS" answerable from CI logs alone.
        non_success_results = [r for r in result.results if r.status.value != "SUCCESS"]
        print(
            f"Non-SUCCESS per-symbol ingestion results: "
            f"{[{'security_id': r.security_id, 'status': r.status.value, 'bars_ingested': r.bars_ingested, 'error': r.error} for r in non_success_results]}"
        )
        print(f"Providers used: {providers_used}")
        print(f"Historical universe membership available: {historical_universe_membership_available}")
        print(f"Corporate actions persisted: {len(all_actions)}")
        print(f"Data quality status: {quality_run.status.value} ({len(quality_run.issues)} issue(s))")
        # Session 37: print the severity breakdown directly to the job's
        # own stdout log -- the full per-issue manifest only round-trips
        # as a GitHub Actions artifact behind Azure Blob Storage, which
        # this environment's own egress proxy cannot reach (see
        # docs/operations/MARKET-DATA-PROVIDER.md); this line is what
        # makes "how bad was this run" answerable straight from CI logs.
        print(f"Data quality severity breakdown: {severity_counts}")
        print(f"Data quality flags newly persisted to catalog: {quality_rows_written}")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        if quality_run.status == DataQualityRunStatus.CRITICAL_FAILURE:
            print(
                f"FATAL: data quality CRITICAL_FAILURE -- {severity_counts['CRITICAL']} CRITICAL "
                "issue(s) found (e.g. non-finite price/volume). The affected bar(s) are now excluded "
                "from DuckDBDataRepository.get_bars()'s default result (Phase 1 spec section 3.1, "
                "QUALITY_REJECTED) -- Raw copies are retained, not deleted -- but this run itself must "
                "still be treated as failed so it is never silently mistaken for a clean ingestion.",
                file=sys.stderr,
            )
        return 0 if result.status.value == "SUCCESS" and quality_run.status != DataQualityRunStatus.CRITICAL_FAILURE else 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
