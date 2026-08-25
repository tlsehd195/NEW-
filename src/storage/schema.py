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
    """
    CREATE SEQUENCE IF NOT EXISTS regime_observation_id_seq START 1
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS regime_composite_id_seq START 1
    """,
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
)


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in DDL_STATEMENTS:
        conn.execute(statement)
