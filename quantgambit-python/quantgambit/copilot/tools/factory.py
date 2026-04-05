"""Factory function for creating a fully-wired :class:`ToolRegistry`.

Registers all read-only query tools and settings mutation tools with their
respective data-store dependencies.
"""

from __future__ import annotations

from typing import Any

from quantgambit.copilot.settings_mutation import SettingsMutationManager
from quantgambit.docs.loader import DocLoader
from quantgambit.docs.search import DocSearchIndex
from quantgambit.copilot.tools.backtests import create_query_backtests_tool
from quantgambit.copilot.tools.candles import create_query_candles_tool
from quantgambit.copilot.tools.doc_search import create_search_docs_tool
from quantgambit.copilot.tools.page_docs import create_get_page_docs_tool
from quantgambit.copilot.tools.decisions import create_query_decision_traces_tool
from quantgambit.copilot.tools.market_context import create_query_market_context_tool
from quantgambit.copilot.tools.market_price import create_query_market_price_tool
from quantgambit.copilot.tools.market_quality import create_query_market_quality_tool
from quantgambit.copilot.tools.performance import create_query_performance_tool
from quantgambit.copilot.tools.pipeline import create_query_pipeline_throughput_tool
from quantgambit.copilot.tools.positions import create_query_positions_tool
from quantgambit.copilot.tools.registry import ToolRegistry
from quantgambit.copilot.tools.settings import create_settings_tools
from quantgambit.copilot.tools.system import (
    create_query_risk_config_tool,
    create_query_system_health_tool,
)
from quantgambit.copilot.tools.trades import create_query_trades_tool
from quantgambit.copilot.tools.trade_flow import create_query_trade_flow_tool


def create_tool_registry(
    timescale_pool: Any,
    redis_client: Any,
    dashboard_pool: Any,
    mutation_manager: SettingsMutationManager,
    tenant_id: str,
    bot_id: str,
    user_id: str,
    conversation_id: str,
    doc_loader: DocLoader | None = None,
    doc_search_index: DocSearchIndex | None = None,
) -> ToolRegistry:
    """Create a :class:`ToolRegistry` with all copilot tools registered.

    Parameters
    ----------
    timescale_pool:
        asyncpg connection pool for TimescaleDB (order_events, decision_events,
        position_events).
    redis_client:
        Async Redis client for positions, system health, and risk config.
    dashboard_pool:
        asyncpg connection pool for the dashboard PostgreSQL database
        (backtest_runs, backtest_metrics).
    mutation_manager:
        :class:`SettingsMutationManager` backing the settings mutation tools.
    tenant_id:
        Tenant identifier scoping all queries.
    bot_id:
        Bot identifier scoping all queries.
    user_id:
        Authenticated user identity for settings tools.
    conversation_id:
        Current conversation identity for settings tools.
    doc_loader:
        Optional :class:`DocLoader` for page documentation tools.
    doc_search_index:
        Optional :class:`DocSearchIndex` for documentation search tools.
    """
    registry = ToolRegistry()

    # -- Read-only query tools (TimescaleDB) --------------------------------
    registry.register(
        create_query_trades_tool(pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id)
    )
    registry.register(
        create_query_positions_tool(
            pool=timescale_pool, redis_client=redis_client, tenant_id=tenant_id, bot_id=bot_id
        )
    )
    registry.register(
        create_query_performance_tool(pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id)
    )
    registry.register(
        create_query_decision_traces_tool(pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id)
    )
    registry.register(
        create_query_pipeline_throughput_tool(
            pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id
        )
    )

    # -- Read-only query tools (dashboard PostgreSQL) -----------------------
    registry.register(
        create_query_backtests_tool(
            dashboard_pool=dashboard_pool, tenant_id=tenant_id, bot_id=bot_id
        )
    )

    # -- Read-only query tools (Redis) --------------------------------------
    registry.register(
        create_query_system_health_tool(
            redis_client=redis_client, tenant_id=tenant_id, bot_id=bot_id
        )
    )
    registry.register(
        create_query_risk_config_tool(
            redis_client=redis_client, tenant_id=tenant_id, bot_id=bot_id
        )
    )

    # -- Read-only query tools (Redis: market data) ----------------------------
    registry.register(
        create_query_market_price_tool(
            redis_client=redis_client, tenant_id=tenant_id, bot_id=bot_id
        )
    )
    registry.register(
        create_query_market_quality_tool(
            redis_client=redis_client, tenant_id=tenant_id, bot_id=bot_id
        )
    )

    # -- Read-only query tools (TimescaleDB: market context) -------------------
    registry.register(
        create_query_market_context_tool(
            pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id
        )
    )

    # -- Read-only query tools (TimescaleDB: candles & trade flow) -------------
    registry.register(
        create_query_candles_tool(
            pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id
        )
    )
    registry.register(
        create_query_trade_flow_tool(
            pool=timescale_pool, tenant_id=tenant_id, bot_id=bot_id
        )
    )

    # -- Settings mutation tools --------------------------------------------
    for tool in create_settings_tools(
        mutation_manager=mutation_manager,
        user_id=user_id,
        conversation_id=conversation_id,
    ):
        registry.register(tool)

    # -- Documentation tools ------------------------------------------------
    if doc_loader is not None:
        registry.register(create_get_page_docs_tool(doc_loader=doc_loader))
    if doc_search_index is not None:
        registry.register(create_search_docs_tool(search_index=doc_search_index))

    return registry
