"""Create backtest tables for backtesting API integration.

Revision ID: 001
Revises: None
Create Date: 2026-01-15

This migration creates all tables required for the backtesting API:
- backtest_runs: Run metadata
- backtest_metrics: Aggregated metrics
- backtest_trades: Individual trades
- backtest_equity_curve: Equity over time
- backtest_symbol_equity_curve: Per-symbol equity curves
- backtest_symbol_metrics: Per-symbol metrics
- backtest_decision_snapshots: Decision log
- backtest_position_snapshots: Position snapshots
- wfo_runs: Walk-forward optimization runs

Requirements: R5.3 (Result Persistence)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all backtest-related tables and indexes."""
    
    # =========================================================================
    # backtest_runs - Run metadata
    # =========================================================================
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", postgresql.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("start_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("end_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
    )
    
    # Indexes for backtest_runs
    op.create_index(
        "backtest_runs_idx",
        "backtest_runs",
        ["tenant_id", "bot_id", sa.text("started_at DESC")],
    )
    op.create_index("backtest_runs_tenant_idx", "backtest_runs", ["tenant_id"])
    op.create_index("backtest_runs_status_idx", "backtest_runs", ["status"])
    op.create_index(
        "backtest_runs_tenant_status_idx",
        "backtest_runs",
        ["tenant_id", "status"],
    )
    op.create_index("backtest_runs_symbol_idx", "backtest_runs", ["symbol"])
    
    # =========================================================================
    # backtest_metrics - Aggregated metrics
    # =========================================================================
    op.create_table(
        "backtest_metrics",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("total_fees", sa.Float(), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("avg_slippage_bps", sa.Float(), nullable=False),
        sa.Column("total_return_pct", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("avg_trade_pnl", sa.Float(), nullable=False),
    )
    
    # =========================================================================
    # backtest_trades - Individual trades
    # =========================================================================
    op.create_table(
        "backtest_trades",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("size", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=False),
        sa.Column("entry_fee", sa.Float(), nullable=False),
        sa.Column("exit_fee", sa.Float(), nullable=False),
        sa.Column("total_fees", sa.Float(), nullable=False),
        sa.Column("entry_slippage_bps", sa.Float(), nullable=False),
        sa.Column("exit_slippage_bps", sa.Float(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=True),
        sa.Column("profile_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    
    op.create_index(
        "backtest_trades_idx",
        "backtest_trades",
        ["run_id", sa.text("ts DESC")],
    )
    
    # =========================================================================
    # backtest_equity_curve - Equity over time
    # =========================================================================
    op.create_table(
        "backtest_equity_curve",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False),
    )
    
    op.create_index(
        "backtest_equity_curve_idx",
        "backtest_equity_curve",
        ["run_id", sa.text("ts DESC")],
    )
    
    # =========================================================================
    # backtest_symbol_equity_curve - Per-symbol equity curves
    # =========================================================================
    op.create_table(
        "backtest_symbol_equity_curve",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False),
    )
    
    op.create_index(
        "backtest_symbol_equity_curve_idx",
        "backtest_symbol_equity_curve",
        ["run_id", "symbol", sa.text("ts DESC")],
    )
    
    # =========================================================================
    # backtest_symbol_metrics - Per-symbol metrics
    # =========================================================================
    op.create_table(
        "backtest_symbol_metrics",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("total_fees", sa.Float(), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("avg_trade_pnl", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("avg_slippage_bps", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "symbol"),
    )
    
    op.create_index(
        "backtest_symbol_metrics_idx",
        "backtest_symbol_metrics",
        ["run_id", "symbol"],
    )
    
    # =========================================================================
    # backtest_decision_snapshots - Decision log
    # =========================================================================
    op.create_table(
        "backtest_decision_snapshots",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("profile_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    
    op.create_index(
        "backtest_decision_snapshots_idx",
        "backtest_decision_snapshots",
        ["run_id", sa.text("ts DESC")],
    )
    
    # =========================================================================
    # backtest_position_snapshots - Position snapshots
    # =========================================================================
    op.create_table(
        "backtest_position_snapshots",
        sa.Column(
            "run_id",
            postgresql.UUID(),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    
    op.create_index(
        "backtest_position_snapshots_idx",
        "backtest_position_snapshots",
        ["run_id", sa.text("ts DESC")],
    )
    
    # =========================================================================
    # wfo_runs - Walk-forward optimization runs
    # =========================================================================
    op.create_table(
        "wfo_runs",
        sa.Column("run_id", postgresql.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
    )
    
    # Indexes for wfo_runs
    op.create_index("wfo_runs_tenant_idx", "wfo_runs", ["tenant_id"])
    op.create_index("wfo_runs_status_idx", "wfo_runs", ["status"])
    op.create_index("wfo_runs_tenant_status_idx", "wfo_runs", ["tenant_id", "status"])
    op.create_index("wfo_runs_profile_idx", "wfo_runs", ["profile_id"])
    op.create_index("wfo_runs_symbol_idx", "wfo_runs", ["symbol"])


def downgrade() -> None:
    """Drop all backtest-related tables and indexes."""
    
    # Drop tables in reverse order (respecting foreign key constraints)
    op.drop_table("wfo_runs")
    op.drop_table("backtest_position_snapshots")
    op.drop_table("backtest_decision_snapshots")
    op.drop_table("backtest_symbol_metrics")
    op.drop_table("backtest_symbol_equity_curve")
    op.drop_table("backtest_equity_curve")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_metrics")
    op.drop_table("backtest_runs")
