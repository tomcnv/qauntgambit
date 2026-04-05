"""Runtime config application logic."""

from __future__ import annotations

from quantgambit.config.models import BotConfig
from quantgambit.observability.logger import log_warning
from quantgambit.execution.wiring import build_execution_manager


class RuntimeConfigApplier:
    """Apply config changes to runtime subsystems."""

    def __init__(self, runtime):
        self.runtime = runtime

    async def apply(self, config: BotConfig) -> bool:
        runtime = self.runtime
        exchange_changed = runtime.config.exchange != config.active_exchange
        trading_mode_changed = runtime.config.trading_mode != config.trading_mode
        market_type_changed = getattr(runtime.config, "market_type", "perp") != config.market_type
        margin_mode_changed = getattr(runtime.config, "margin_mode", "isolated") != config.margin_mode

        runtime.config.exchange = config.active_exchange
        runtime.config.trading_mode = config.trading_mode
        runtime.config.market_type = config.market_type
        runtime.config.margin_mode = config.margin_mode
        runtime.telemetry_ctx.exchange = config.active_exchange
        trading_hours = config.trading_hours or {}
        runtime.config.trading_hours_start = int(trading_hours.get("start_hour_utc", 0))
        runtime.config.trading_hours_end = int(trading_hours.get("end_hour_utc", 24))
        if getattr(config, "order_intent_max_age_sec", None) is not None:
            runtime.config.order_intent_max_age_sec = config.order_intent_max_age_sec
            if hasattr(runtime, "order_store") and runtime.order_store:
                runtime.order_store._max_intent_age_sec = config.order_intent_max_age_sec
        if runtime.feature_worker:
            runtime.feature_worker.config.trading_session_start_hour_utc = runtime.config.trading_hours_start
            runtime.feature_worker.config.trading_session_end_hour_utc = runtime.config.trading_hours_end

        if exchange_changed or trading_mode_changed or market_type_changed:
            runtime.execution_manager = build_execution_manager(
                exchange_name=config.active_exchange,
                adapter=runtime.execution_adapter,
                state_manager=runtime.state_manager,
                trading_mode=config.trading_mode,
                redis_client=runtime.redis_client,
                bot_id=runtime.config.bot_id,
                reference_prices=runtime.reference_prices,
                exchange_router=runtime.exchange_router,
                reconciler=runtime.reconciler,
                adapter_config=runtime.adapter_config,
                paper_fill_engine=runtime.paper_fill_engine,
                paper_config=runtime.paper_config,
                telemetry=runtime.telemetry,
                telemetry_context=runtime.telemetry_ctx,
                snapshot_reader=runtime.snapshot_reader,
            )
            runtime.action_handler.execution_manager = runtime.execution_manager
            applier = runtime.config_watcher.applier
            if hasattr(applier, "position_manager"):
                applier.position_manager = runtime.execution_manager.position_manager
        if market_type_changed or margin_mode_changed:
            log_warning("runtime_config_requires_restart", market_type=config.market_type, margin_mode=config.margin_mode)
        log_warning(
            "runtime_config_applied",
            version=config.version,
            exchange=config.active_exchange,
            trading_mode=config.trading_mode,
            market_type=config.market_type,
            margin_mode=config.margin_mode,
        )
        return True
