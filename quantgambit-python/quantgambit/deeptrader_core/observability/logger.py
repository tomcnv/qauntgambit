"""
Structured logging system for the trading engine
"""
import json
import sys
import os
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
import structlog
from pythonjsonlogger import jsonlogger


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TradingLogger:
    """Structured logger for trading operations"""

    def __init__(self, service_name: str, log_level: LogLevel = LogLevel.INFO):
        self.service_name = service_name
        self.log_level = log_level

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                self._add_service_info,
                structlog.processors.JSONRenderer()
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level.value.lower()),
            context_class=dict,
            logger_factory=structlog.WriteLoggerFactory(),
            cache_logger_on_first_use=True,
        )

        self.logger = structlog.get_logger()

    def _add_service_info(self, logger, method_name, event_dict):
        """Add service metadata to all log entries"""
        event_dict["service"] = self.service_name
        event_dict["worker"] = os.getenv("WORKER_NAME", "unknown")
        event_dict["version"] = os.getenv("SERVICE_VERSION", "1.0.0")
        return event_dict

    def debug(self, event: str, **kwargs):
        """Log debug message"""
        self.logger.debug(event, **kwargs)

    def info(self, event: str, **kwargs):
        """Log info message"""
        self.logger.info(event, **kwargs)

    def warning(self, event: str, **kwargs):
        """Log warning message"""
        self.logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs):
        """Log error message"""
        self.logger.error(event, **kwargs)

    def critical(self, event: str, **kwargs):
        """Log critical message"""
        self.logger.critical(event, **kwargs)

    # Trading-specific logging methods
    def log_strategy_signal(
        self,
        strategy_id: str,
        symbol: str,
        exchange: str,
        action: str,
        confidence: float,
        correlation_id: str,
        reasoning: str = None,
        **kwargs
    ):
        """Log strategy signal generation"""
        self.info(
            "strategy_signal_generated",
            strategy_id=strategy_id,
            symbol=symbol,
            exchange=exchange,
            action=action,
            confidence=confidence,
            correlation_id=correlation_id,
            reasoning=reasoning,
            **kwargs
        )

    def log_order_execution(
        self,
        order_id: str,
        symbol: str,
        exchange: str,
        side: str,
        quantity: float,
        price: float,
        execution_time_ms: int,
        correlation_id: str,
        slippage_bps: float = None,
        **kwargs
    ):
        """Log order execution"""
        self.info(
            "order_executed",
            order_id=order_id,
            symbol=symbol,
            exchange=exchange,
            side=side,
            quantity=quantity,
            price=price,
            execution_time_ms=execution_time_ms,
            correlation_id=correlation_id,
            slippage_bps=slippage_bps,
            **kwargs
        )

    def log_risk_check(
        self,
        check_type: str,
        passed: bool,
        reason: str = None,
        user_id: str = None,
        symbol: str = None,
        correlation_id: str = None,
        **kwargs
    ):
        """Log risk management check"""
        log_method = self.info if passed else self.warning
        log_method(
            "risk_check",
            check_type=check_type,
            passed=passed,
            reason=reason,
            user_id=user_id,
            symbol=symbol,
            correlation_id=correlation_id,
            **kwargs
        )

    def log_position_update(
        self,
        position_id: str,
        symbol: str,
        exchange: str,
        side: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        unrealized_pnl: float,
        correlation_id: str,
        **kwargs
    ):
        """Log position update"""
        self.info(
            "position_updated",
            position_id=position_id,
            symbol=symbol,
            exchange=exchange,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            correlation_id=correlation_id,
            **kwargs
        )

    def log_worker_health(
        self,
        worker_name: str,
        status: str,
        uptime_seconds: int,
        messages_processed: int = 0,
        errors_count: int = 0,
        **kwargs
    ):
        """Log worker health status"""
        log_method = self.info if status == "running" else self.warning
        log_method(
            "worker_health",
            worker_name=worker_name,
            status=status,
            uptime_seconds=uptime_seconds,
            messages_processed=messages_processed,
            errors_count=errors_count,
            **kwargs
        )

    def log_performance_metric(
        self,
        metric_name: str,
        value: float,
        tags: Dict[str, Any] = None,
        **kwargs
    ):
        """Log performance metric"""
        self.info(
            "performance_metric",
            metric_name=metric_name,
            value=value,
            tags=tags or {},
            **kwargs
        )

    def log_error(
        self,
        error_type: str,
        message: str,
        stack_trace: str = None,
        correlation_id: str = None,
        **kwargs
    ):
        """Log error with context"""
        self.error(
            "application_error",
            error_type=error_type,
            message=message,
            stack_trace=stack_trace,
            correlation_id=correlation_id,
            **kwargs
        )

    def log_message_flow(
        self,
        event_type: str,
        event_id: str,
        correlation_id: str,
        causation_id: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
        **kwargs
    ):
        """Log message flow for debugging"""
        self.debug(
            "message_flow",
            event_type=event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            processing_time_ms=processing_time_ms,
            **kwargs
        )


# Global logger instances
data_logger = TradingLogger("data_worker")
strategy_logger = TradingLogger("strategy_worker")
risk_logger = TradingLogger("risk_worker")
execution_logger = TradingLogger("execution_worker")
monitoring_logger = TradingLogger("monitoring_api")

# Convenience function to get logger by service name
def get_logger(service_name: str) -> TradingLogger:
    """Get logger instance for a service"""
    loggers = {
        "data_worker": data_logger,
        "strategy_worker": strategy_logger,
        "risk_worker": risk_logger,
        "execution_worker": execution_logger,
        "monitoring_api": monitoring_logger
    }
    return loggers.get(service_name, TradingLogger(service_name))
