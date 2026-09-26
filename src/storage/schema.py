"""DuckDB schema (DDL) for the Phase 4 persistent storage layer.

See docs/specifications/PHASE-4-baseline-models-and-storage.md section 4
and ADR-0010. All statements are idempotent (``CREATE TABLE IF NOT
EXISTS`` / ``CREATE SEQUENCE IF NOT EXISTS``) so opening the same on-disk
database file repeatedly (restart safety) never wipes or redefines
existing tables.

Every relational/metadata dataset listed in the Phase 4 instruction lives
here (Security Master, Universe Membership, Corporate Actions, Benchmark,
Trade Journal, Experiment, Experience, version metadata). Only the
high-volume per-security OHLCV time series (Raw + Clean Market Data)
lives outside DuckDB tables, in append-only Parquet files under the same
storage root (parquet_layer.py) -- see ADR-0010 for why.
"""

from __future__ import annotations

import functools

import duckdb

DDL_STATEMENTS: tuple[str, ...] = (
    # -- Phase 1: relational/metadata (small relative to OHLCV volume) --
    """
    CREATE TABLE IF NOT EXISTS security_master (
        security_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        exchange TEXT NOT NULL,
        currency TEXT NOT NULL,
        company_id TEXT NOT NULL,
        instrument_type TEXT NOT NULL,
        valid_from TIMESTAMP NOT NULL,
        valid_to TIMESTAMP,
        status TEXT NOT NULL,
        provenance_source TEXT,
        provenance_source_dataset TEXT,
        provenance_source_record_id TEXT,
        provenance_retrieved_at TIMESTAMP,
        provenance_data_version TEXT,
        provenance_schema_version INTEGER,
        PRIMARY KEY (security_id, valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        provenance_source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        action_type TEXT NOT NULL,
        event_time TIMESTAMP,
        announcement_time TIMESTAMP,
        effective_time TIMESTAMP,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        details_json TEXT NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchmark_points (
        provenance_source_record_id TEXT PRIMARY KEY,
        benchmark_id TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        level DOUBLE NOT NULL,
        return_type TEXT NOT NULL,
        currency TEXT NOT NULL,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS universe_membership (
        security_id TEXT NOT NULL,
        universe TEXT NOT NULL,
        valid_from TIMESTAMP NOT NULL,
        valid_to TIMESTAMP,
        provenance_source TEXT,
        provenance_source_dataset TEXT,
        provenance_source_record_id TEXT,
        provenance_retrieved_at TIMESTAMP,
        provenance_data_version TEXT,
        provenance_schema_version INTEGER,
        PRIMARY KEY (security_id, universe, valid_from)
    )
    """,
    # Audit manifest of raw-ingestion Parquet batches (the Parquet files
    # themselves are the actual immutable raw store -- see
    # parquet_layer.py). This table exists so "what raw batches do we
    # have" is answerable with SQL rather than a directory listing.
    """
    CREATE TABLE IF NOT EXISTS raw_ingestion_batches (
        batch_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        source TEXT NOT NULL,
        record_count INTEGER NOT NULL,
        ingested_at TIMESTAMP NOT NULL,
        parquet_path TEXT NOT NULL
    )
    """,
    # Session 37 (real-data DQ gap): DataQualityFramework.run() (Phase 1
    # spec section 13) previously produced a DataQualityRun that nothing
    # ever read back -- CRITICAL-severity findings did not stop a
    # corrupted bar from being served to Paper Trading/backtest/Learning
    # Cycle code. This table implements the Raw/Clean promotion states
    # Phase 1 spec section 3.1 already documented (QUALITY_REJECTED /
    # QUALITY_FLAGGED) but never wired up: DuckDBDataRepository.get_bars()
    # consults it to exclude a CRITICAL-flagged (security_id, timestamp)
    # from its default result (QUALITY_REJECTED -- not promoted to
    # Clean), while the underlying Parquet bar itself is never deleted
    # (Raw Immutability, section 17) and remains reachable via
    # get_bars(..., include_quality_rejected=True) for audit. A
    # WARNING/ERROR-severity finding is recorded here too (so a consumer
    # can inspect/filter on it -- QUALITY_FLAGGED) but is NOT excluded by
    # default, matching section 3.1's own documented distinction.
    """
    CREATE TABLE IF NOT EXISTS data_quality_flags (
        security_id TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        check_name TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        validation_id TEXT NOT NULL,
        dataset TEXT NOT NULL,
        flagged_at TIMESTAMP NOT NULL,
        PRIMARY KEY (security_id, timestamp, check_name)
    )
    """,
    # -- Phase 3: Trade Journal --
    """
    CREATE SEQUENCE IF NOT EXISTS decision_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS trade_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS correction_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS experience_id_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        snapshot_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        decision_time TIMESTAMP NOT NULL,
        security_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        strategy_version TEXT NOT NULL,
        execution_version TEXT NOT NULL,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        data_version TEXT,
        feature_version TEXT,
        model_version TEXT,
        risk_version TEXT,
        confidence DOUBLE,
        expected_return DOUBLE,
        expected_risk DOUBLE,
        target_weight DOUBLE,
        decision_reason TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        decision_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        security_id TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        side TEXT NOT NULL,
        quantity DOUBLE NOT NULL,
        execution_price DOUBLE NOT NULL,
        reference_price DOUBLE NOT NULL,
        slippage DOUBLE NOT NULL,
        transaction_cost DOUBLE NOT NULL,
        position_after DOUBLE NOT NULL,
        realized_pnl DOUBLE,
        realized_return DOUBLE,
        holding_period_seconds DOUBLE,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS post_trade_analysis_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS post_trade_analyses (
        seq BIGINT PRIMARY KEY DEFAULT nextval('post_trade_analysis_seq'),
        trade_id TEXT NOT NULL,
        computed_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS counterfactual_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS counterfactuals (
        seq BIGINT PRIMARY KEY DEFAULT nextval('counterfactual_seq'),
        trade_id TEXT NOT NULL,
        computed_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corrections (
        correction_id TEXT PRIMARY KEY,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        corrected_fields_json TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        created_by TEXT NOT NULL
    )
    """,
    # -- Phase 4: Experiment Registry + Experience Dataset --
    """
    CREATE TABLE IF NOT EXISTS experiments (
        experiment_id TEXT PRIMARY KEY,
        strategy_version TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        start_date TIMESTAMP NOT NULL,
        end_date TIMESTAMP NOT NULL,
        initial_capital DOUBLE NOT NULL,
        code_version TEXT NOT NULL,
        seed INTEGER,
        result TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        cumulative_return DOUBLE,
        cagr DOUBLE,
        sharpe_ratio DOUBLE,
        sortino_ratio DOUBLE,
        max_drawdown DOUBLE,
        excess_return DOUBLE,
        turnover DOUBLE,
        total_transaction_cost DOUBLE,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_records (
        experience_id TEXT PRIMARY KEY,
        trade_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        action TEXT NOT NULL,
        provenance TEXT NOT NULL,
        reward DOUBLE,
        strategy_version TEXT NOT NULL,
        model_version TEXT,
        data_version TEXT,
        created_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 5: Market Regime --
    # Relational metadata, not Parquet time series: regime observations
    # are point-lookup/filter-heavy (natural-key idempotency, "most
    # recent composite as of a decision time") the same way Trade
    # Journal/Experiment records are, not bulk-columnar-scan workloads
    # the way per-security OHLCV bars are -- the same criterion ADR-0010
    # section 1 already applied to Benchmark data, applied again here
    # (docs/specifications/PHASE-5-market-regime.md section 11).
    #
    # No id sequence here (ADR-0118): regime_id/composite_id are the
    # caller-assigned natural PRIMARY KEY below, the same pattern
    # broker_requests/broker_responses already use (see storage.
    # broker_repository's own module docstring) -- an earlier revision
    # of this schema created regime_observation_id_seq/regime_composite_
    # id_seq for this purpose and never consumed either via nextval;
    # removed as genuinely dead DDL rather than left undocumented.
    """
    CREATE TABLE IF NOT EXISTS regime_observations (
        regime_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        axis TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        state TEXT NOT NULL,
        value DOUBLE,
        reliability DOUBLE NOT NULL,
        feature_version TEXT NOT NULL,
        method_version TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS regime_composites (
        composite_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        subject_id TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        composite_label TEXT,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 6: Prediction --
    # Relational metadata, not Parquet: same criterion as Regime
    # (point-lookup/filter/join-heavy, natural-key idempotency,
    # "most recent prediction as of a decision time") -- ADR-0010
    # section 1 / ADR-0011 section 4, applied again here (Phase 6 spec
    # section 11).
    """
    CREATE TABLE IF NOT EXISTS decision_outputs (
        decision_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        security_id TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        action TEXT NOT NULL,
        decision_reason TEXT NOT NULL,
        confidence DOUBLE,
        time_horizon_days INTEGER,
        target_weight_hint DOUBLE,
        prediction_id TEXT,
        prediction_version TEXT,
        regime_version TEXT,
        feature_version TEXT,
        model_version TEXT,
        decision_version TEXT NOT NULL,
        strategy_version TEXT,
        risk_version TEXT,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS predictions (
        prediction_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        security_id TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        horizon_days INTEGER NOT NULL,
        expected_return DOUBLE,
        probability DOUBLE,
        expected_volatility DOUBLE,
        uncertainty DOUBLE,
        confidence DOUBLE,
        method TEXT NOT NULL,
        method_type TEXT NOT NULL,
        feature_version TEXT NOT NULL,
        method_version TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        model_version TEXT,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 8: Position Sizing + Portfolio Risk Engine. Two new,
    # additive tables -- no existing table's schema changed. risk_state
    # (portfolio-level metrics) is embedded inside risk_assessments'
    # payload_json rather than a separate table, mirroring how
    # decision_outputs already embeds its `regime` context dict inline
    # (Phase 7 spec section 5) instead of requiring a join for something
    # that is always 1:1 with the record that used it (Phase 8 spec
    # section 11, ADR-0014 section 8).
    """
    CREATE TABLE IF NOT EXISTS position_sizing_results (
        sizing_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        security_id TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        status TEXT NOT NULL,
        reason TEXT NOT NULL,
        decision_id TEXT,
        decision_action TEXT,
        proposed_target_weight DOUBLE,
        proposed_target_quantity DOUBLE,
        current_weight DOUBLE,
        current_quantity DOUBLE NOT NULL,
        sizing_version TEXT NOT NULL,
        feature_version TEXT,
        prediction_id TEXT,
        decision_version TEXT,
        prediction_version TEXT,
        regime_version TEXT,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_assessments (
        risk_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        security_id TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        status TEXT NOT NULL,
        reason TEXT NOT NULL,
        final_target_weight DOUBLE,
        final_target_quantity DOUBLE,
        sizing_id TEXT,
        decision_id TEXT,
        prediction_id TEXT,
        risk_version TEXT NOT NULL,
        feature_version TEXT,
        sizing_version TEXT,
        decision_version TEXT,
        prediction_version TEXT,
        regime_version TEXT,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        recorded_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 9: Learning Engine. Four new, additive tables -- no
    # existing table's schema changed. `training_datasets.dataset_version`
    # is a content hash (reproducibility: rebuilding from identical
    # source experiences + configuration always idempotently returns the
    # same row, see storage/learning_repository.py).
    #
    # The four *_id primary keys below are allocated by this sequence
    # group at INSERT time, never trusted from the caller's in-process
    # allocator -- the identical fix `experience_id_seq` already applies
    # to `ExperienceRecord.experience_id` (Phase 4 spec section 12.1,
    # ADR-0010 "Known correctness fix"): a fresh, per-process
    # `DatasetIdAllocator`/trainer/evaluator/tracker restarts its
    # "...-000001" counter on every call, so two independently-built
    # pipeline runs can legitimately allocate the same in-process id for
    # two genuinely different records; only a storage-level sequence is
    # actually globally unique.
    """
    CREATE SEQUENCE IF NOT EXISTS training_dataset_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS candidate_model_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS evaluation_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS learning_experiment_id_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS training_datasets (
        dataset_id TEXT PRIMARY KEY,
        dataset_version TEXT UNIQUE,
        created_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        feature_version TEXT,
        label_version TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        sample_count INTEGER NOT NULL,
        excluded_count INTEGER NOT NULL,
        quality_status TEXT NOT NULL,
        as_of_cutoff TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS candidate_models (
        candidate_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        status TEXT NOT NULL,
        trainer_version TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        label_version TEXT NOT NULL,
        seed INTEGER,
        trained_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        experiment_id TEXT,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_results (
        evaluation_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        candidate_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        evaluator_version TEXT NOT NULL,
        evaluated_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learning_experiments (
        experiment_id TEXT PRIMARY KEY,
        natural_key TEXT UNIQUE,
        dataset_id TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        trainer_version TEXT NOT NULL,
        evaluator_version TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        evaluation_id TEXT NOT NULL,
        configuration_version TEXT NOT NULL,
        seed INTEGER,
        provenance TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 10: Performance Attribution (Counterfactual reuses Phase 3's
    # existing `counterfactuals` table -- no new table for it) --
    """
    CREATE SEQUENCE IF NOT EXISTS attribution_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS attribution_results (
        seq BIGINT PRIMARY KEY DEFAULT nextval('attribution_seq'),
        experiment_id TEXT NOT NULL,
        computed_at TIMESTAMP,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 11: Model Evolution --
    """
    CREATE SEQUENCE IF NOT EXISTS model_status_transition_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS model_status_transitions (
        seq BIGINT PRIMARY KEY DEFAULT nextval('model_status_transition_seq'),
        transition_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        criteria_version TEXT NOT NULL,
        passed BOOLEAN NOT NULL,
        evaluated_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_lineage (
        candidate_id TEXT PRIMARY KEY,
        parent_candidate_id TEXT,
        generation INTEGER NOT NULL,
        dataset_id TEXT NOT NULL,
        dataset_version TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 12: AI Gateway --
    """
    CREATE TABLE IF NOT EXISTS ai_requests (
        request_id TEXT PRIMARY KEY,
        task_tier TEXT NOT NULL,
        prompt_template_id TEXT NOT NULL,
        prompt_template_version TEXT NOT NULL,
        requested_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_responses (
        response_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        status TEXT NOT NULL,
        provider_id TEXT,
        responded_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS provider_quota_state_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_quota_states (
        seq BIGINT PRIMARY KEY DEFAULT nextval('provider_quota_state_seq'),
        state_id TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        observed_at TIMESTAMP NOT NULL,
        health_status TEXT NOT NULL,
        billing_status TEXT NOT NULL,
        enabled BOOLEAN NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 13: Toss Securities Adapter (Broker) --
    """
    CREATE TABLE IF NOT EXISTS broker_requests (
        request_id TEXT PRIMARY KEY,
        broker_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        execution_mode TEXT NOT NULL,
        client_order_id TEXT,
        decision_id TEXT,
        sizing_id TEXT,
        risk_assessment_id TEXT,
        requested_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS broker_responses (
        response_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        broker_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        responded_at TIMESTAMP NOT NULL,
        provenance TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS order_status_event_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS order_status_events (
        seq BIGINT PRIMARY KEY DEFAULT nextval('order_status_event_seq'),
        observation_id TEXT NOT NULL,
        client_order_id TEXT NOT NULL,
        broker_id TEXT NOT NULL,
        status TEXT NOT NULL,
        observed_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 14: Monitoring --
    """
    CREATE TABLE IF NOT EXISTS monitoring_events (
        event_id TEXT PRIMARY KEY,
        component TEXT NOT NULL,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        observed_at TIMESTAMP NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS component_health_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS component_health_states (
        seq BIGINT PRIMARY KEY DEFAULT nextval('component_health_seq'),
        health_id TEXT NOT NULL,
        component TEXT NOT NULL,
        status TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS drift_result_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS drift_results (
        seq BIGINT PRIMARY KEY DEFAULT nextval('drift_result_seq'),
        drift_id TEXT NOT NULL,
        component TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        status TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id TEXT PRIMARY KEY,
        severity TEXT NOT NULL,
        component TEXT NOT NULL,
        raised_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 15: Paper Trading --
    """
    CREATE TABLE IF NOT EXISTS paper_orders (
        client_order_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity DOUBLE NOT NULL,
        initial_status TEXT NOT NULL,
        requested_at TIMESTAMP NOT NULL,
        decision_id TEXT NOT NULL,
        sizing_id TEXT NOT NULL,
        risk_assessment_id TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS paper_fill_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_fills (
        seq BIGINT PRIMARY KEY DEFAULT nextval('paper_fill_seq'),
        fill_id TEXT NOT NULL,
        client_order_id TEXT NOT NULL,
        security_id TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity DOUBLE NOT NULL,
        price DOUBLE NOT NULL,
        recorded_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # ADR-0155: the persisted idempotency ledger a fresh-per-process
    # `PaperBrokerAdapter`/`CorporateActionApplier` needs across restarts
    # -- `source_record_id` is the PRIMARY KEY (not an append-only seq
    # like paper_fills), since a corporate action, unlike a fill, must
    # never be recorded twice at all -- `record()`'s dedup query is a
    # direct primary-key lookup. `applied_at` is indexed-by-scan order
    # (ORDER BY, same as paper_orders/paper_fills) for `list_all()`'s
    # required chronological ordering, used by `PaperTradingSession.
    # restore()`'s merge-sort-by-time replay against `paper_fills.
    # recorded_at`/`fill.execution_time`.
    """
    CREATE TABLE IF NOT EXISTS paper_applied_corporate_actions (
        source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        action_type TEXT NOT NULL,
        applied_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 16: Live Trading --
    """
    CREATE SEQUENCE IF NOT EXISTS kill_switch_event_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS kill_switch_events (
        seq BIGINT PRIMARY KEY DEFAULT nextval('kill_switch_event_seq'),
        event_id TEXT NOT NULL,
        engaged BOOLEAN NOT NULL,
        reason TEXT NOT NULL,
        triggered_by TEXT NOT NULL,
        occurred_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS reconciliation_event_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS reconciliation_events (
        seq BIGINT PRIMARY KEY DEFAULT nextval('reconciliation_event_seq'),
        reconciliation_id TEXT NOT NULL,
        target TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        status TEXT NOT NULL,
        as_of_time TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # Phase 18 -- Paper Trading Performance Report persistence, purely
    # additive (docs/specifications/PHASE-18-paper-performance-and-validation.md).
    """
    CREATE SEQUENCE IF NOT EXISTS paper_performance_report_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_performance_reports (
        seq BIGINT PRIMARY KEY DEFAULT nextval('paper_performance_report_seq'),
        report_id TEXT NOT NULL,
        paper_session_id TEXT NOT NULL,
        evaluated_at TIMESTAMP NOT NULL,
        payload_json TEXT NOT NULL
    )
    """,
    # -- Phase 33: Fundamentals Data (SEC EDGAR) -- ADR-0042. Low-volume,
    # point-lookup/filter-heavy (one company's history is a few hundred
    # rows at most, queried per security+concept), same criterion
    # ADR-0010 section 1 already applied to Benchmark data -- a DuckDB
    # table with explicit typed columns, not Parquet.
    """
    CREATE TABLE IF NOT EXISTS fundamental_records (
        provenance_source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        concept TEXT NOT NULL,
        period_start TIMESTAMP,
        period_end TIMESTAMP NOT NULL,
        fiscal_year INTEGER NOT NULL,
        fiscal_period TEXT NOT NULL,
        form_type TEXT NOT NULL,
        value DOUBLE NOT NULL,
        unit TEXT NOT NULL,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    # -- Session 36 continued: Insider Transactions (SEC Form 4) --
    # ADR-0086. Same low-volume, point-lookup/filter-heavy criterion as
    # fundamental_records above. provenance_source_record_id (the
    # accession number + transaction-row identity) is the natural key,
    # not (security_id, transaction_date) alone -- a single Form 4
    # filing can report multiple transaction rows for the same insider
    # on the same date (e.g. separate open-market buys at different
    # prices), and each is its own real, distinct transaction.
    """
    CREATE TABLE IF NOT EXISTS insider_transactions (
        provenance_source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        reporting_owner_cik TEXT NOT NULL,
        reporting_owner_name TEXT NOT NULL,
        is_officer BOOLEAN NOT NULL,
        is_director BOOLEAN NOT NULL,
        is_ten_percent_owner BOOLEAN NOT NULL,
        officer_title TEXT,
        transaction_date TIMESTAMP NOT NULL,
        transaction_code TEXT NOT NULL,
        acquired_disposed_code TEXT NOT NULL,
        shares DOUBLE NOT NULL,
        price_per_share DOUBLE,
        is_10b5_1_plan BOOLEAN NOT NULL,
        accession_number TEXT NOT NULL,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    # Session 36 continued -- FINRA Rule 4560 equity short interest
    # reports (data_infra.short_interest_models.ShortInterestRecord).
    # Natural key = provenance_source_record_id (one row per security
    # per settlement date), same idempotent-insert shape as
    # insider_transactions/fundamental_records above.
    """
    CREATE TABLE IF NOT EXISTS short_interest_records (
        provenance_source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        settlement_date TIMESTAMP NOT NULL,
        short_interest_quantity DOUBLE NOT NULL,
        average_daily_volume DOUBLE,
        days_to_cover DOUBLE,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    # Session 36 continued addition -- SEC Form 13F aggregate
    # institutional holdings (data_infra.institutional_holding_models.
    # InstitutionalHoldingRecord). Mirrors short_interest_records above
    # exactly: natural key = provenance_source_record_id (one row per
    # security per calendar quarter), same idempotent-insert shape.
    """
    CREATE TABLE IF NOT EXISTS institutional_holding_records (
        provenance_source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        quarter_end TIMESTAMP NOT NULL,
        institutional_shares DOUBLE NOT NULL,
        num_institutions INTEGER,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    # guru_consensus_score's own data -- one SPECIFIC 13F filer's
    # reported position in one security for one quarter (data_infra.
    # institutional_holding_models.InstitutionalFilerHoldingRecord),
    # distinct from institutional_holding_records above (which sums
    # across ALL filers and carries no filer identity). Natural key
    # includes filer_cik since the same security/quarter can have one
    # row per tracked filer.
    """
    CREATE TABLE IF NOT EXISTS institutional_filer_holding_records (
        provenance_source_record_id TEXT PRIMARY KEY,
        security_id TEXT NOT NULL,
        filer_cik TEXT NOT NULL,
        quarter_end TIMESTAMP NOT NULL,
        shares_held DOUBLE NOT NULL,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
    # ADR-0217 -- point-in-time macro observations (data_infra.
    # macro_models.MacroObservationRecord): one row per ALFRED vintage
    # of one observation, so revisions coexist instead of overwriting.
    # Natural key = provenance_source_record_id
    # (source:series:observation_date:realtime_start).
    """
    CREATE TABLE IF NOT EXISTS macro_observation_vintages (
        provenance_source_record_id TEXT PRIMARY KEY,
        series_id TEXT NOT NULL,
        observation_date TIMESTAMP NOT NULL,
        value DOUBLE,
        realtime_start TIMESTAMP NOT NULL,
        realtime_end TIMESTAMP,
        available_time TIMESTAMP NOT NULL,
        ingestion_time TIMESTAMP NOT NULL,
        provenance_source TEXT NOT NULL,
        provenance_source_dataset TEXT NOT NULL,
        provenance_retrieved_at TIMESTAMP NOT NULL,
        provenance_data_version TEXT NOT NULL,
        provenance_schema_version INTEGER NOT NULL
    )
    """,
)


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in DDL_STATEMENTS:
        conn.execute(statement)
    _add_missing_columns(conn)


@functools.lru_cache(maxsize=1)
def _expected_columns() -> dict[str, tuple[tuple[str, str, bool], ...]]:
    """(column, type, nullable) per table, as DDL_STATEMENTS defines them today.

    Built once per process from a scratch in-memory database so the DDL
    above stays the single source of truth for the schema.
    """
    scratch = duckdb.connect(":memory:")
    try:
        for statement in DDL_STATEMENTS:
            scratch.execute(statement)
        rows = scratch.execute(
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns WHERE table_schema = 'main' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
    finally:
        scratch.close()
    expected: dict[str, list[tuple[str, str, bool]]] = {}
    for table, column, data_type, is_nullable in rows:
        expected.setdefault(table, []).append((column, data_type, is_nullable == "YES"))
    return {table: tuple(cols) for table, cols in expected.items()}


def _add_missing_columns(conn: duckdb.DuckDBPyConnection) -> None:
    """Additive migration for databases created by an older DDL_STATEMENTS.

    ``CREATE TABLE IF NOT EXISTS`` never touches a table that already
    exists, so a column added to the DDL later (e.g. ADR-0203's
    ``provenance_*`` columns on ``security_master``) is missing from any
    on-disk database created before that change -- and every INSERT
    naming it then fails with a Binder Error. A nullable column is added
    in place (existing rows read NULL, the same as a new row that omits
    it). A NOT NULL column cannot be backfilled honestly without a value,
    so that case fails loudly instead of guessing one.
    """
    actual: dict[str, set[str]] = {}
    for table, column in conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'main'"
    ).fetchall():
        actual.setdefault(table, set()).add(column)
    for table, columns in _expected_columns().items():
        present = actual.get(table)
        if present is None:
            continue
        for column, data_type, nullable in columns:
            if column in present:
                continue
            if not nullable:
                raise RuntimeError(
                    f"existing table {table!r} is missing NOT NULL column {column!r}; "
                    "it cannot be added without a backfill value -- migrate this "
                    "database explicitly"
                )
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {data_type}')
