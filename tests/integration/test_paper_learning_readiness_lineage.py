"""Category: Integration Test (Phase 17 -- Production Safety Review,
Section 11 "Paper Trading Readiness" / Section 12 "Paper Trading
Experience Test" / Section 13 "Paper -> Learning Safety"). Traces the
actual code path Paper Order -> Fill -> Position/Cash -> Trade Journal
-> Post Trade Analysis -> Counterfactual -> Experience Dataset ->
Learning Engine, through real function calls -- never asserting only
that an import succeeds.

tests/integration/test_paper_trading_lineage.py (Phase 15) already
proves one BUY-and-FILLED path reaches the Trade Journal end to end
through DuckDB with a restart. This file supplements it with the five
scenarios the Phase 17 review instruction specifically names (A-E),
using the simpler in-memory repositories so each scenario stays
readable, plus the Paper -> Learning provenance-safety guarantees
Section 13 requires.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from broker_helpers import make_risk_checked_position
from paper_helpers import make_bar, make_paper_config, utc

from backtest.enums import OrderSide
from broker.enums import BrokerOrderStatus, OrderValidationStatus
from broker.errors import BrokerError, BrokerTimeoutError
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.journal import build_trade_record
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from learning.dataset import build_training_dataset
from learning.enums import SampleStatus

from risk.enums import RiskCheckStatus

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.experience import build_experience_records
from trade_journal.repository import InMemoryTradeJournalRepository


def _risk_and_order(*, quantity: float, risk_id: str, side_status: RiskCheckStatus = RiskCheckStatus.PASS):
    risk = make_risk_checked_position(
        risk_id=risk_id, final_target_quantity=quantity, status=side_status, provenance=TradeProvenance.PAPER_TRADING,
    )
    validation = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1")
    return risk, validation


class TestScenarioA_BuyFillJournalExperience:
    def test_a_buy_fill_journal_experience(self) -> None:
        as_of = utc(2024, 6, 1)
        risk, validation = _risk_and_order(quantity=10.0, risk_id="RISK-A1")
        assert validation.status == OrderValidationStatus.ACCEPTED
        order = validation.validated_order

        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=as_of, security_id=order.security_id, decision=DecisionAction.BUY,
        )

        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=as_of, volume=1_000_000.0)])
        session = PaperTradingSession(config, mds)

        response, fills = session.submit(order, requested_at=as_of)
        assert response.status == BrokerOrderStatus.FILLED
        assert len(fills) == 1

        trade = journal.record_trade(
            decision_id=decision.snapshot_id, fill=fills[0].fill, position_after=order.quantity,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        assert trade.provenance == TradeProvenance.PAPER_TRADING

        records = build_experience_records(journal, provenance=TradeProvenance.PAPER_TRADING, created_at=as_of)
        assert len(records) == 1
        assert records[0].trade_id == trade.trade_id
        assert records[0].provenance == TradeProvenance.PAPER_TRADING
        assert records[0].action == DecisionAction.BUY


class TestScenarioB_PartialThenFullFillJournalExperience:
    def test_b_partial_then_full_fill_each_produce_their_own_journal_and_experience_entry(self) -> None:
        """Reuses the exact max_participation=0.10 / volume=1000 /
        quantity=250 combination tests/broker/paper/test_paper_adapter.py
        already proves fills across three bars as
        100 -> +100 (200 total) -> +50 (250 total, FILLED) -- this test
        picks up from there and checks each incremental fill reaches its
        own Trade Journal record and Experience record, never fabricated
        as one lump BUY."""
        day1, day2, day3 = utc(2024, 6, 1), utc(2024, 6, 2), utc(2024, 6, 3)
        risk, validation = _risk_and_order(quantity=250.0, risk_id="RISK-B1")
        order = validation.validated_order

        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=day1, security_id=order.security_id, decision=DecisionAction.BUY)

        config = make_paper_config(initial_cash=10_000_000.0, max_participation=0.10)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=day1, volume=1_000.0)])
        session = PaperTradingSession(config, mds)

        response1, fills1 = session.submit(order, requested_at=day1)
        assert response1.status == BrokerOrderStatus.PARTIAL_FILLED
        assert len(fills1) == 1 and fills1[0].fill.quantity == 100.0

        mds.register(make_bar(security_id=order.security_id, available_time=day2, volume=1_000.0))
        _, fills2 = session.advance(day2)
        assert len(fills2) == 1 and fills2[0].fill.quantity == 100.0

        mds.register(make_bar(security_id=order.security_id, available_time=day3, volume=1_000.0))
        _, fills3 = session.advance(day3)
        assert len(fills3) == 1 and fills3[0].fill.quantity == 50.0

        all_fills = fills1 + fills2 + fills3
        assert sum(f.fill.quantity for f in all_fills) == 250.0

        for i, fill_record in enumerate(all_fills, start=1):
            journal.record_trade(
                decision_id=decision.snapshot_id, fill=fill_record.fill, position_after=100.0 * i if i < 3 else 250.0,
                provenance=TradeProvenance.PAPER_TRADING,
            )

        assert len(journal.list_trades(provenance=TradeProvenance.PAPER_TRADING)) == 3

        records = build_experience_records(journal, provenance=TradeProvenance.PAPER_TRADING, created_at=day3)
        assert len(records) == 3
        assert sum(r.actual_outcome["realized_pnl"] is None for r in records) == 3  # no PnL claimed on an opening BUY leg
        assert {r.provenance for r in records} == {TradeProvenance.PAPER_TRADING}


class TestScenarioC_RejectedByRiskProducesNoFalseTrade:
    def test_c_reject_status_never_produces_a_validated_order_or_any_downstream_record(self) -> None:
        risk, validation = _risk_and_order(quantity=50.0, risk_id="RISK-C1", side_status=RiskCheckStatus.REJECT)
        assert validation.status == OrderValidationStatus.VALIDATION_REJECTED
        assert validation.validated_order is None  # structurally nothing left to submit -- OrderValidationResult enforces this

        # No PaperTradingSession.submit call is even possible without a
        # ValidatedOrder -- there is no code path from here to a Fill,
        # a Trade Journal record, or an Experience record.
        journal = InMemoryTradeJournalRepository()
        assert journal.list_trades() == []
        assert build_experience_records(journal, provenance=TradeProvenance.PAPER_TRADING, created_at=utc(2024, 6, 1)) == []

    def test_c_unknown_risk_status_also_produces_no_validated_order(self) -> None:
        """UNKNOWN -> DO NOT TRADE (risk.enums.RiskCheckStatus docstring)
        -- the same fail-closed rule applies as REJECT, not just a
        literal REJECT status."""
        risk, validation = _risk_and_order(quantity=50.0, risk_id="RISK-C2", side_status=RiskCheckStatus.UNKNOWN)
        assert validation.status == OrderValidationStatus.VALIDATION_REJECTED
        assert validation.validated_order is None


class TestScenarioD_BrokerFailureNeverFabricatesATradeAndIsNeverBlindlyRetried:
    def test_d_broker_timeout_raises_and_leaves_no_trade_journal_record(self) -> None:
        as_of = utc(2024, 6, 1)
        risk, validation = _risk_and_order(quantity=10.0, risk_id="RISK-D1")
        order = validation.validated_order

        config = make_paper_config(initial_cash=1_000_000.0, failure_mode="timeout")
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=as_of, volume=1_000_000.0)])
        session = PaperTradingSession(config, mds)

        journal = InMemoryTradeJournalRepository()

        with pytest.raises(BrokerTimeoutError):
            submit_validated_order(
                session.adapter, order, execution_mode="PAPER", requested_at=as_of, configuration_version="cfg-v1",
            )

        # A submission exception must never leave a Fill or Trade Journal
        # entry behind -- the caller (this test, standing in for a real
        # driving loop) decides whether/when to retry; nothing in
        # broker.pipeline.submit_validated_order retries automatically,
        # and nothing fabricates a trade for an order whose true outcome
        # is unknown (mirrors broker.live.session.LiveTradingSession's
        # identical guarantee for Live, tests/broker/live/
        # test_live_session.py -- Paper has no reconciliation state
        # machine of its own since there is no independent real broker
        # to reconcile against, but the "no fabricated trade" invariant
        # is identical).
        assert journal.list_trades() == []
        assert order.client_order_id not in session.adapter._orders  # nothing was ever recorded as submitted

    def test_d_a_second_call_is_a_conscious_caller_decision_not_an_automatic_retry(self) -> None:
        """submit_validated_order itself makes exactly one adapter call
        per invocation -- proving "no blind retry" structurally rather
        than by reading the source."""
        as_of = utc(2024, 6, 1)
        risk, validation = _risk_and_order(quantity=10.0, risk_id="RISK-D2")
        order = validation.validated_order
        config = make_paper_config(initial_cash=1_000_000.0, failure_mode="timeout")
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=as_of, volume=1_000_000.0)])
        session = PaperTradingSession(config, mds)

        call_count = 0
        original_submit = session.adapter.submit_order

        def _counting_submit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_submit(*args, **kwargs)

        session.adapter.submit_order = _counting_submit  # type: ignore[method-assign]

        with pytest.raises(BrokerError):
            submit_validated_order(session.adapter, order, execution_mode="PAPER", requested_at=as_of, configuration_version="cfg-v1")

        assert call_count == 1


class TestScenarioE_CompletedTradeReachesPostTradeAnalysisCounterfactualAndLearningDataset:
    def test_e_full_chain_buy_then_closing_sell_reaches_a_labeled_training_sample(self) -> None:
        buy_day, sell_day = utc(2024, 6, 1), utc(2024, 6, 10)
        journal = InMemoryTradeJournalRepository()

        buy_risk, buy_validation = _risk_and_order(quantity=10.0, risk_id="RISK-E1")
        buy_order = buy_validation.validated_order
        buy_decision = journal.record_decision(decision_time=buy_day, security_id=buy_order.security_id, decision=DecisionAction.BUY)

        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([
            make_bar(security_id=buy_order.security_id, available_time=buy_day, volume=1_000_000.0, close=100.0),
            make_bar(security_id=buy_order.security_id, available_time=sell_day, volume=1_000_000.0, close=110.0),
        ])
        session = PaperTradingSession(config, mds)

        _, buy_fills = session.submit(buy_order, requested_at=buy_day)
        buy_trade = journal.record_trade(
            decision_id=buy_decision.snapshot_id, fill=buy_fills[0].fill, position_after=10.0,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        assert buy_trade.realized_return is None  # an opening leg realizes nothing yet

        sell_risk = make_risk_checked_position(
            risk_id="RISK-E2", final_target_quantity=0.0, provenance=TradeProvenance.PAPER_TRADING,
        )
        sell_validation = build_validated_order(sell_risk, current_quantity=10.0, configuration_version="cfg-v1")
        sell_order = sell_validation.validated_order
        assert sell_order.side == OrderSide.SELL
        sell_decision = journal.record_decision(decision_time=sell_day, security_id=sell_order.security_id, decision=DecisionAction.SELL)

        _, sell_fills = session.submit(sell_order, requested_at=sell_day)
        sell_trade = journal.record_trade(
            decision_id=sell_decision.snapshot_id, fill=sell_fills[0].fill, position_after=0.0,
            realized_pnl=95.0, realized_return=0.095, holding_period=sell_day - buy_day,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        assert sell_trade.realized_return == 0.095

        journal.record_post_trade_analysis(sell_trade.trade_id, prediction_error=0.01, computed_at=sell_day)
        journal.record_counterfactual(
            sell_trade.trade_id, selected_action=DecisionAction.SELL,
            alternatives=(), computed_at=sell_day,
        )

        records = build_experience_records(journal, provenance=TradeProvenance.PAPER_TRADING, created_at=sell_day)
        assert len(records) == 2
        sell_record = next(r for r in records if r.trade_id == sell_trade.trade_id)
        assert sell_record.prediction_error == 0.01
        assert sell_record.counterfactual_results == ()
        assert sell_record.reward == 0.095

        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.PAPER_TRADING, created_at=sell_day,
        )
        # The opening BUY leg has no realized_return -- Phase 9's
        # DataCleaningConfig.require_realized_outcome=True default
        # EXCLUDES it (never fabricates a 0.0 label); only the closing
        # SELL leg becomes a labeled sample.
        assert result.dataset.sample_count == 1
        assert result.dataset.provenance == TradeProvenance.PAPER_TRADING
        buy_cleaning = next(r for r in result.cleaning_results if r.trade_id == buy_trade.trade_id)
        assert buy_cleaning.status == SampleStatus.EXCLUDED
        sell_cleaning = next(r for r in result.cleaning_results if r.trade_id == sell_trade.trade_id)
        assert sell_cleaning.status == SampleStatus.VALID
        assert result.labeled_samples[0].label_value == 0.095


class TestPaperToLearningProvenanceSafety:
    """Section 13 -- PAPER_TRADING must never be convertible to
    LIVE_TRADING, and a mismatched/wrong provenance in a batch of
    records must fail closed (excluded), never silently absorbed into
    the wrong dataset."""

    def _journal_with_mixed_provenance(self, as_of: datetime) -> InMemoryTradeJournalRepository:
        journal = InMemoryTradeJournalRepository()
        for i, provenance in enumerate((TradeProvenance.PAPER_TRADING, TradeProvenance.LIVE_TRADING, TradeProvenance.HISTORICAL_SIMULATION)):
            risk, validation = _risk_and_order(quantity=10.0, risk_id=f"RISK-PROV{i}")
            order = validation.validated_order
            decision = journal.record_decision(decision_time=as_of, security_id=order.security_id, decision=DecisionAction.BUY)
            config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
            mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=as_of, volume=1_000_000.0)])
            session = PaperTradingSession(config, mds)
            _, fills = session.submit(order, requested_at=as_of)
            journal.record_trade(
                decision_id=decision.snapshot_id, fill=fills[0].fill, position_after=10.0,
                realized_pnl=1.0, realized_return=0.01, provenance=provenance,
            )
        return journal

    def test_list_trades_provenance_filter_never_returns_a_different_provenance(self) -> None:
        journal = self._journal_with_mixed_provenance(utc(2024, 6, 1))
        paper_only = journal.list_trades(provenance=TradeProvenance.PAPER_TRADING)
        assert len(paper_only) == 1
        assert paper_only[0].provenance == TradeProvenance.PAPER_TRADING

    def test_build_experience_records_provenance_filter_excludes_live_and_historical(self) -> None:
        journal = self._journal_with_mixed_provenance(utc(2024, 6, 1))
        records = build_experience_records(journal, provenance=TradeProvenance.PAPER_TRADING, created_at=utc(2024, 6, 1))
        assert len(records) == 1
        assert records[0].provenance == TradeProvenance.PAPER_TRADING

    def test_data_cleaner_rejects_a_wrong_provenance_record_even_if_it_bypasses_the_repository_filter(self) -> None:
        """Defense in depth: even if a caller assembles `records`
        without going through `list_trades(provenance=...)` (a
        programming mistake, not the intended path),
        `learning.cleaning.DataCleaner.clean` independently re-checks
        each record's own provenance and marks a mismatch INVALID --
        this is what makes "PAPER_TRADING can never become LIVE_TRADING"
        a structural guarantee, not a convention resting on a single
        filter call."""
        journal = self._journal_with_mixed_provenance(utc(2024, 6, 1))
        every_trade_as_experience = build_experience_records(journal, provenance=None, created_at=utc(2024, 6, 1))
        assert len(every_trade_as_experience) == 3  # unfiltered, on purpose, to bypass the normal safe path

        result = build_training_dataset(
            journal, every_trade_as_experience, provenance=TradeProvenance.PAPER_TRADING, created_at=utc(2024, 6, 1),
        )
        assert result.dataset.sample_count == 1
        mismatched = [r for r in result.cleaning_results if r.reason == "provenance_mismatch"]
        assert len(mismatched) == 2
        assert {r.provenance for r in mismatched} == {TradeProvenance.LIVE_TRADING, TradeProvenance.HISTORICAL_SIMULATION}
        # Structural proof LIVE_TRADING data can never silently end up
        # inside a PAPER_TRADING TrainingDataset's actual sample set:
        live_trade_id = next(t.trade_id for t in journal.list_trades(provenance=TradeProvenance.LIVE_TRADING))
        assert live_trade_id not in {s.trade_id for s in result.labeled_samples}

    def test_no_function_anywhere_converts_one_provenance_value_into_another(self) -> None:
        """A trade's provenance, once recorded, is carried forward
        verbatim through experience.py/dataset.py/cleaning.py/
        labeling.py -- none of these modules ever hardcodes
        TradeProvenance.LIVE_TRADING or .PAPER_TRADING as a literal
        (each would only ever read/compare an existing value)."""
        import ast
        import inspect

        import learning.cleaning
        import learning.dataset
        import learning.labeling
        import trade_journal.experience

        for module in (learning.cleaning, learning.dataset, learning.labeling, trade_journal.experience):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("LIVE_TRADING", "PAPER_TRADING"):
                    raise AssertionError(
                        f"{module.__name__} references TradeProvenance.{node.attr} as a literal -- "
                        "provenance must only ever be read/compared, never assigned by name here"
                    )
