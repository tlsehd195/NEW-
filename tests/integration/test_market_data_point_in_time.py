"""Category: Point-in-Time Regression Test (Phase 20, instruction
section 9). Proves the specific temporal-behavior guarantee the
instruction names: a corporate action discovered/ingested *later*
never retroactively rewrites a raw OHLCV observation already stored
for an earlier date. This is distinct from -- and a real-data-shaped
extension of -- `tests/data/test_lookahead_guard.py`'s generic
"future-available records are invisible" guard (Phase 1): that test
proves invisibility of not-yet-available records; this test proves
non-mutation of already-stored ones once a later fact becomes known.

Uses `TiingoDataProvider` (Phase 20) to produce Tiingo-shaped raw
records, and the real `storage.data_repository.DuckDBDataRepository`
(Phase 4, unmodified) -- not the in-memory repository -- so the
guarantee is proven against actual on-disk persistence, including a
process restart, not just in-process object identity.
"""

from __future__ import annotations

from datetime import datetime, timezone

from storage_helpers import new_engine

from data_infra.enums import CorporateActionType
from data_infra.providers.tiingo import TiingoDataProvider
from data_infra.providers.tiingo_config import TiingoConfig
from data_infra.providers.tiingo_transport import TiingoTransportResponse
from storage.data_repository import DuckDBDataRepository


def utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class _StubTransport:
    """Never reaches the network -- returns a fixed Tiingo-shaped
    response regardless of the request (ADR-0025)."""

    def __init__(self, body) -> None:
        self._body = body

    def get(self, path, *, params, timeout):
        return TiingoTransportResponse(status_code=200, body=self._body, raw_text=None, headers={})


class TestRawObservationNeverRewrittenByALaterCorporateAction:
    def test_split_discovered_later_does_not_change_the_already_stored_raw_bar(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

        # -- Day 1: ingest AAPL's raw 2024-01-02 bar, before any split is known --
        pre_split_body = [{
            "date": "2024-01-02T00:00:00.000Z", "open": "185.0", "high": "186.5", "low": "184.2",
            "close": "185.64", "volume": "82488700", "adjClose": "185.64", "splitFactor": "1.0", "divCash": "0.0",
        }]
        provider = TiingoDataProvider(TiingoConfig(), _StubTransport(pre_split_body))
        raw = provider.fetch("AAPL", utc(2024, 1, 1), utc(2024, 1, 3))
        bars = provider.normalize("AAPL", raw)
        assert len(bars) == 1

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_bars(bars)

        as_of_ingestion = utc(2024, 1, 3)
        original = repo.get_bars("AAPL", utc(2024, 1, 2), utc(2024, 1, 2, 23), as_of_time=as_of_ingestion)
        assert len(original) == 1
        original_close = original[0].close
        original_open = original[0].open
        original_volume = original[0].volume
        assert original_close == 185.64  # the genuine raw, unadjusted close

        # -- Months later: a 4:1 split is announced/ingested for AAPL,
        # effective well after the bar above, discovered only now --
        split_actions = provider.normalize_corporate_actions(
            "AAPL",
            [{"date": "2024-06-10T00:00:00.000Z", "splitFactor": "4.0", "divCash": "0.0"}],
            retrieved_at=utc(2024, 6, 11), ingestion_time=utc(2024, 6, 11),
        )
        assert len(split_actions) == 1
        assert split_actions[0].action_type == CorporateActionType.SPLIT
        repo.add_corporate_action(split_actions[0])

        # -- Re-query the SAME original bar, as of a time well after the
        # split is now known -- the raw observation must be byte-identical
        # to what was stored on day 1, never divided by 4 or otherwise
        # "adjusted in place". --
        as_of_after_split = utc(2024, 7, 1)
        reloaded = repo.get_bars("AAPL", utc(2024, 1, 2), utc(2024, 1, 2, 23), as_of_time=as_of_after_split)
        assert len(reloaded) == 1
        assert reloaded[0].close == original_close == 185.64
        assert reloaded[0].open == original_open
        assert reloaded[0].volume == original_volume
        assert reloaded[0].adjusted_close == 185.64  # also never dynamically recomputed by this query

        # -- The split itself is correctly visible now, and was correctly
        # invisible before it was ever ingested (the look-ahead guard,
        # exercised here against genuinely Tiingo-shaped data rather than
        # a hand-built fixture). --
        actions_after = repo.get_corporate_actions("AAPL", utc(2024, 1, 1), utc(2024, 12, 31), as_of_time=as_of_after_split)
        assert len(actions_after) == 1
        assert actions_after[0].details["ratio"] == 4.0

        actions_before_discovery = repo.get_corporate_actions(
            "AAPL", utc(2024, 1, 1), utc(2024, 12, 31), as_of_time=utc(2024, 6, 10)  # one day before ingestion_time
        )
        assert actions_before_discovery == []

        engine.close()

        # -- Restart: reopen the same DuckDB/Parquet catalog -- the raw
        # bar is still exactly as originally stored, not recomputed on
        # load either. --
        engine2 = new_engine(tmp_path)
        repo2 = DuckDBDataRepository(engine2)
        reloaded_after_restart = repo2.get_bars("AAPL", utc(2024, 1, 2), utc(2024, 1, 2, 23), as_of_time=as_of_after_split)
        assert reloaded_after_restart[0].close == 185.64
        engine2.close()

    def test_dividend_discovered_later_does_not_change_the_already_stored_raw_bar(self, tmp_path, monkeypatch) -> None:
        """The same guarantee, exercised for a dividend event instead
        of a split -- a separate code path in
        normalize_corporate_actions, deliberately tested independently."""
        monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

        body = [{
            "date": "2024-02-01T00:00:00.000Z", "open": "180.0", "high": "181.0", "low": "179.0",
            "close": "180.5", "volume": "50000000", "adjClose": "180.5", "splitFactor": "1.0", "divCash": "0.0",
        }]
        provider = TiingoDataProvider(TiingoConfig(), _StubTransport(body))
        raw = provider.fetch("AAPL", utc(2024, 1, 31), utc(2024, 2, 2))
        bars = provider.normalize("AAPL", raw)

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine)
        repo.append_bars(bars)

        original_close = repo.get_bars("AAPL", utc(2024, 2, 1), utc(2024, 2, 1, 23), as_of_time=utc(2024, 2, 2))[0].close
        assert original_close == 180.5

        dividend_actions = provider.normalize_corporate_actions(
            "AAPL", [{"date": "2024-05-10T00:00:00.000Z", "splitFactor": "1.0", "divCash": "0.25"}],
            retrieved_at=utc(2024, 5, 11), ingestion_time=utc(2024, 5, 11),
        )
        repo.add_corporate_action(dividend_actions[0])

        reloaded_close = repo.get_bars(
            "AAPL", utc(2024, 2, 1), utc(2024, 2, 1, 23), as_of_time=utc(2024, 6, 1)
        )[0].close
        assert reloaded_close == original_close == 180.5

        engine.close()
