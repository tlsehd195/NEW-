"""Category: Unit Test -- DataCleaner (Phase 9 spec section 7).

Covers: required field presence, invalid numeric values (NaN/infinity),
duplicate sample, invalid timestamp (unresolvable decision), missing
outcome, invalid reward, provenance mismatch.
"""

from __future__ import annotations

import dataclasses
import math

from learning_helpers import build_journal_with_closed_trades, build_journal_with_open_trade, utc

from learning.cleaning import DataCleaner
from learning.config import DataCleaningConfig
from learning.enums import SampleStatus

from trade_journal.enums import TradeProvenance


class TestValidSamples:
    def test_normal_closed_trades_are_all_valid(self) -> None:
        journal, records = build_journal_with_closed_trades(5)
        results = DataCleaner().clean(records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert len(results) == 5
        assert all(r.status == SampleStatus.VALID for r in results)
        assert all(r.reason == "ok" for r in results)
        assert all(r.sample_as_of_time is not None for r in results)


class TestMissingOutcome:
    def test_open_trade_with_no_realized_return_is_excluded(self) -> None:
        journal, records = build_journal_with_open_trade()
        results = DataCleaner().clean(records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.EXCLUDED
        assert results[0].reason == "no_realized_outcome"

    def test_require_realized_outcome_false_allows_it_through(self) -> None:
        journal, records = build_journal_with_open_trade()
        cleaner = DataCleaner(DataCleaningConfig(require_realized_outcome=False))
        results = cleaner.clean(records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.VALID


class TestInvalidTimestamp:
    def test_unresolvable_decision_is_unknown(self) -> None:
        journal, records = build_journal_with_closed_trades(1)
        bad_record = dataclasses.replace(records[0], decision_id="NO-SUCH-DECISION")
        results = DataCleaner().clean([bad_record], journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.UNKNOWN
        assert results[0].reason == "missing_decision"
        assert results[0].sample_as_of_time is None

    def test_a_decision_with_no_resolvable_time_is_unknown_not_a_crash(self) -> None:
        """Session 37 (ADR-0115, external review, previously-remaining
        MEDIUM): before this fix, this exclusion only applied when
        `config.require_sample_as_of_time` was True -- a dead guard in
        practice, since a real `DecisionSnapshot.decision_time` can
        never actually be None (its own `__post_init__` requires a
        timezone-aware value). This proves the exclusion is now
        unconditional even against a malformed/legacy decision object
        that duck-types past that validation (e.g. a raw DB row from
        before this field existed) -- the one case that, before this
        fix, would have let `sample_as_of_time=None` reach `learning.
        dataset.build_training_dataset`'s chronological sort and crash
        it, regardless of `require_sample_as_of_time`."""
        import types

        journal, records = build_journal_with_closed_trades(1)
        real_decision = journal.get_decision(records[0].decision_id)
        malformed_decision = types.SimpleNamespace(
            decision_time=None, security_id=real_decision.security_id,
        )

        class _StubJournal:
            def get_decision(self, decision_id):
                return malformed_decision

        for require in (True, False):
            cleaner = DataCleaner(DataCleaningConfig(require_sample_as_of_time=require))
            results = cleaner.clean([records[0]], _StubJournal(), provenance=TradeProvenance.HISTORICAL_SIMULATION)
            assert results[0].status == SampleStatus.UNKNOWN
            assert results[0].reason == "missing_decision"
            assert results[0].sample_as_of_time is None


class TestInvalidNumeric:
    def test_nan_reward_is_invalid(self) -> None:
        journal, records = build_journal_with_closed_trades(1)
        bad_record = dataclasses.replace(records[0], reward=float("nan"))
        results = DataCleaner().clean([bad_record], journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.INVALID
        assert results[0].reason == "invalid_reward_numeric"

    def test_infinite_reward_is_invalid(self) -> None:
        journal, records = build_journal_with_closed_trades(1)
        bad_record = dataclasses.replace(records[0], reward=float("inf"))
        results = DataCleaner().clean([bad_record], journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.INVALID
        assert results[0].reason == "invalid_reward_numeric"

    def test_nan_realized_return_is_invalid(self) -> None:
        journal, records = build_journal_with_closed_trades(1)
        bad_outcome = dict(records[0].actual_outcome)
        bad_outcome["realized_return"] = float("nan")
        bad_record = dataclasses.replace(records[0], actual_outcome=bad_outcome)
        results = DataCleaner().clean([bad_record], journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.INVALID
        assert results[0].reason == "invalid_realized_return_numeric"

    def test_infinite_realized_return_is_invalid(self) -> None:
        journal, records = build_journal_with_closed_trades(1)
        bad_outcome = dict(records[0].actual_outcome)
        bad_outcome["realized_return"] = float("-inf")
        bad_record = dataclasses.replace(records[0], actual_outcome=bad_outcome)
        results = DataCleaner().clean([bad_record], journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.INVALID
        assert results[0].reason == "invalid_realized_return_numeric"


class TestDuplicateSample:
    def test_duplicate_trade_id_in_the_same_batch_is_invalid_for_the_second_occurrence(self) -> None:
        journal, records = build_journal_with_closed_trades(1)
        results = DataCleaner().clean([records[0], records[0]], journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.VALID
        assert results[1].status == SampleStatus.INVALID
        assert results[1].reason == "duplicate_trade_id"


class TestProvenanceMismatch:
    def test_record_with_a_different_provenance_is_invalid(self) -> None:
        journal, records = build_journal_with_closed_trades(1, provenance=TradeProvenance.PAPER_TRADING)
        results = DataCleaner().clean(records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        assert results[0].status == SampleStatus.INVALID
        assert results[0].reason == "provenance_mismatch"


class TestNeverSilentlyDrops:
    def test_every_input_record_gets_exactly_one_result(self) -> None:
        journal, records = build_journal_with_closed_trades(8)
        _, open_records = build_journal_with_open_trade(decision_time=utc(2024, 6, 1))
        all_records = list(records) + list(open_records)
        results = DataCleaner().clean(all_records, journal, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        # open_records' decision lives in a different journal -- unresolvable here -> UNKNOWN, not dropped
        assert len(results) == len(all_records)
        assert all(isinstance(r.status, SampleStatus) for r in results)
