"""
Environment variable validation schema.

This module defines all environment variables used by the QuantGambit runtime
and provides validation to catch configuration errors at startup.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from enum import Enum


class EnvVarType(Enum):
    """Type of environment variable."""
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"  # Comma-separated


@dataclass
class EnvVarSpec:
    """Specification for an environment variable."""
    name: str
    type: EnvVarType
    default: Any = None
    required: bool = False
    description: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[Set[str]] = None
    secret: bool = False  # Don't log value


# =============================================================================
# Environment Variable Definitions
# =============================================================================

ENV_VARS: List[EnvVarSpec] = [
    # Core Runtime
    EnvVarSpec(
        name="TENANT_ID",
        type=EnvVarType.STRING,
        required=True,
        description="Tenant identifier",
    ),
    EnvVarSpec(
        name="BOT_ID",
        type=EnvVarType.STRING,
        required=True,
        description="Bot identifier",
    ),
    EnvVarSpec(
        name="EXCHANGE",
        type=EnvVarType.STRING,
        required=True,
        description="Exchange to trade on",
        allowed_values={"bybit", "okx", "binance"},
    ),
    EnvVarSpec(
        name="TRADING_MODE",
        type=EnvVarType.STRING,
        default="paper",
        description="Trading mode",
        allowed_values={"paper", "live"},
    ),
    EnvVarSpec(
        name="MARKET_TYPE",
        type=EnvVarType.STRING,
        default="perp",
        description="Market type",
        allowed_values={"perp", "spot"},
    ),
    EnvVarSpec(
        name="MARGIN_MODE",
        type=EnvVarType.STRING,
        default="isolated",
        description="Margin mode for perpetuals",
        allowed_values={"isolated", "cross"},
    ),
    
    # Quant Integration
    EnvVarSpec(
        name="QUANT_INTEGRATION_ENABLED",
        type=EnvVarType.BOOL,
        default=True,
        description="Enable quant-grade components (kill switch, reconciliation, latency tracking)",
    ),
    EnvVarSpec(
        name="QUANT_STATS_INTERVAL_SEC",
        type=EnvVarType.FLOAT,
        default=5.0,
        min_value=1.0,
        description="Interval for publishing quant stats to Redis",
    ),
    
    # Kill Switch
    EnvVarSpec(
        name="KILL_SWITCH_REJECT_THRESHOLD",
        type=EnvVarType.INT,
        default=5,
        min_value=1,
        description="Number of order rejects before triggering kill switch",
    ),
    EnvVarSpec(
        name="KILL_SWITCH_RESYNC_THRESHOLD",
        type=EnvVarType.INT,
        default=3,
        min_value=1,
        description="Number of book resyncs before triggering kill switch",
    ),
    
    # Reconciliation
    EnvVarSpec(
        name="RECONCILIATION_INTERVAL_SEC",
        type=EnvVarType.FLOAT,
        default=30.0,
        min_value=5.0,
        description="Interval between reconciliation runs",
    ),
    EnvVarSpec(
        name="RECONCILIATION_AUTO_HEAL",
        type=EnvVarType.BOOL,
        default=True,
        description="Automatically heal discrepancies found during reconciliation",
    ),
    
    # Latency Tracking
    EnvVarSpec(
        name="LATENCY_MAX_SAMPLES",
        type=EnvVarType.INT,
        default=100000,
        min_value=1000,
        description="Maximum samples to keep for latency tracking",
    ),
    EnvVarSpec(
        name="LATENCY_WINDOW_SEC",
        type=EnvVarType.FLOAT,
        default=60.0,
        min_value=10.0,
        description="Time window for latency percentile calculation",
    ),
    
    # Position Guard
    EnvVarSpec(
        name="POSITION_GUARD_ENABLED",
        type=EnvVarType.BOOL,
        default=True,
        description="Enable position guard worker",
    ),
    EnvVarSpec(
        name="POSITION_GUARD_INTERVAL_SEC",
        type=EnvVarType.FLOAT,
        default=1.0,
        min_value=0.1,
        description="Position guard check interval",
    ),
    EnvVarSpec(
        name="POSITION_GUARD_MAX_AGE_SEC",
        type=EnvVarType.FLOAT,
        default=0.0,
        min_value=0.0,
        description="Maximum position age before forced close (0 = disabled)",
    ),
    EnvVarSpec(
        name="POSITION_GUARD_TRAILING_BPS",
        type=EnvVarType.FLOAT,
        default=0.0,
        min_value=0.0,
        description="Trailing stop in basis points (0 = disabled)",
    ),
    
    # Trading Capital - User's configured trading budget
    EnvVarSpec(
        name="TRADING_CAPITAL_USD",
        type=EnvVarType.FLOAT,
        default=10000.0,
        min_value=10.0,
        description="User's configured trading capital in USD. This is the amount the bot will use for position sizing.",
    ),
    
    # Risk Management
    EnvVarSpec(
        name="MAX_POSITION_SIZE_USD",
        type=EnvVarType.FLOAT,
        default=10000.0,
        min_value=0.0,
        description="Maximum position size in USD",
    ),
    EnvVarSpec(
        name="MAX_TOTAL_EXPOSURE_PCT",
        type=EnvVarType.FLOAT,
        default=1.0,
        min_value=0.0,
        max_value=5.0,
        description="Maximum total exposure as percentage of equity (decimal)",
    ),
    EnvVarSpec(
        name="RISK_PER_TRADE_PCT",
        type=EnvVarType.FLOAT,
        default=0.01,
        min_value=0.0,
        max_value=1.0,
        description="Risk per trade as percentage of equity (decimal)",
    ),
    
    # Equity Refresh
    EnvVarSpec(
        name="EQUITY_REFRESH_INTERVAL_SEC",
        type=EnvVarType.FLOAT,
        default=30.0,
        min_value=10.0,
        description="Interval for refreshing equity from exchange",
    ),
    EnvVarSpec(
        name="BALANCE_CURRENCY",
        type=EnvVarType.STRING,
        default="USDT",
        description="Currency for balance queries",
    ),
    
    # Order Management
    EnvVarSpec(
        name="ORDER_EVENT_REPLAY_HOURS",
        type=EnvVarType.FLOAT,
        default=6.0,
        min_value=0.0,
        description="Hours of order events to replay on startup",
    ),
    EnvVarSpec(
        name="ORDER_EVENT_REPLAY_LIMIT",
        type=EnvVarType.INT,
        default=500,
        min_value=0,
        description="Maximum order events to replay on startup",
    ),
    EnvVarSpec(
        name="ORDER_INTENT_MAX_AGE_SEC",
        type=EnvVarType.FLOAT,
        default=300.0,
        min_value=0.0,
        description="Maximum age for pending order intents",
    ),
    
    # Alerting
    EnvVarSpec(
        name="SLACK_WEBHOOK_URL",
        type=EnvVarType.STRING,
        default=None,
        description="Slack webhook URL for alerts",
        secret=True,
    ),
    EnvVarSpec(
        name="DISCORD_WEBHOOK_URL",
        type=EnvVarType.STRING,
        default=None,
        description="Discord webhook URL for alerts",
        secret=True,
    ),
    EnvVarSpec(
        name="ALERT_WEBHOOK_URL",
        type=EnvVarType.STRING,
        default=None,
        description="Generic webhook URL for alerts",
        secret=True,
    ),
    EnvVarSpec(
        name="ALERT_CHANNEL",
        type=EnvVarType.STRING,
        default=None,
        description="Slack channel override for alerts",
    ),
    EnvVarSpec(
        name="ALERT_USERNAME",
        type=EnvVarType.STRING,
        default="QuantGambit Bot",
        description="Bot username for alerts",
    ),
    
    # Redis
    EnvVarSpec(
        name="REDIS_URL",
        type=EnvVarType.STRING,
        default="redis://localhost:6379",
        description="Redis connection URL",
        secret=True,
    ),
    
    # Database
    EnvVarSpec(
        name="TIMESCALE_URL",
        type=EnvVarType.STRING,
        default=None,
        description="TimescaleDB connection URL",
        secret=True,
    ),
    
    # Exchange Credentials
    EnvVarSpec(
        name="BYBIT_API_KEY",
        type=EnvVarType.STRING,
        default=None,
        description="Bybit API key",
        secret=True,
    ),
    EnvVarSpec(
        name="BYBIT_API_SECRET",
        type=EnvVarType.STRING,
        default=None,
        description="Bybit API secret",
        secret=True,
    ),
    EnvVarSpec(
        name="BYBIT_TESTNET",
        type=EnvVarType.BOOL,
        default=False,
        description="Use Bybit testnet",
    ),
]


@dataclass
class ValidationError:
    """Validation error for an environment variable."""
    var_name: str
    message: str
    value: Any = None


@dataclass
class ValidationResult:
    """Result of environment variable validation."""
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    values: Dict[str, Any] = field(default_factory=dict)


def _parse_bool(value: str) -> bool:
    """Parse boolean from string."""
    return value.lower() in ("true", "1", "yes", "on")


def _parse_list(value: str) -> List[str]:
    """Parse comma-separated list from string."""
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_env_var(spec: EnvVarSpec) -> Optional[ValidationError]:
    """
    Validate a single environment variable.
    
    Returns ValidationError if invalid, None if valid.
    """
    raw_value = os.getenv(spec.name)
    
    # Check required
    if spec.required and not raw_value:
        return ValidationError(
            var_name=spec.name,
            message=f"Required environment variable {spec.name} is not set",
        )
    
    # Use default if not set
    if not raw_value:
        return None
    
    # Parse and validate type
    try:
        if spec.type == EnvVarType.STRING:
            value = raw_value
        elif spec.type == EnvVarType.INT:
            value = int(raw_value)
        elif spec.type == EnvVarType.FLOAT:
            value = float(raw_value)
        elif spec.type == EnvVarType.BOOL:
            value = _parse_bool(raw_value)
        elif spec.type == EnvVarType.LIST:
            value = _parse_list(raw_value)
        else:
            value = raw_value
    except (ValueError, TypeError) as e:
        return ValidationError(
            var_name=spec.name,
            message=f"Invalid type for {spec.name}: expected {spec.type.value}, got '{raw_value}'",
            value=raw_value,
        )
    
    # Check min/max for numeric types
    if spec.type in (EnvVarType.INT, EnvVarType.FLOAT):
        if spec.min_value is not None and value < spec.min_value:
            return ValidationError(
                var_name=spec.name,
                message=f"{spec.name} value {value} is below minimum {spec.min_value}",
                value=value,
            )
        if spec.max_value is not None and value > spec.max_value:
            return ValidationError(
                var_name=spec.name,
                message=f"{spec.name} value {value} is above maximum {spec.max_value}",
                value=value,
            )
    
    # Check allowed values
    if spec.allowed_values and str(value).lower() not in {v.lower() for v in spec.allowed_values}:
        return ValidationError(
            var_name=spec.name,
            message=f"{spec.name} value '{value}' not in allowed values: {spec.allowed_values}",
            value=value,
        )
    
    return None


def validate_all_env_vars() -> ValidationResult:
    """
    Validate all environment variables.
    
    Returns ValidationResult with errors and parsed values.
    """
    errors = []
    warnings = []
    values = {}
    
    for spec in ENV_VARS:
        error = validate_env_var(spec)
        if error:
            if spec.required:
                errors.append(error)
            else:
                warnings.append(error)
        else:
            # Store parsed value
            raw_value = os.getenv(spec.name)
            if raw_value:
                if spec.type == EnvVarType.INT:
                    values[spec.name] = int(raw_value)
                elif spec.type == EnvVarType.FLOAT:
                    values[spec.name] = float(raw_value)
                elif spec.type == EnvVarType.BOOL:
                    values[spec.name] = _parse_bool(raw_value)
                elif spec.type == EnvVarType.LIST:
                    values[spec.name] = _parse_list(raw_value)
                else:
                    values[spec.name] = raw_value
            elif spec.default is not None:
                values[spec.name] = spec.default
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        values=values,
    )


def get_env_var_docs() -> str:
    """Generate documentation for all environment variables."""
    lines = ["# Environment Variables\n"]
    
    # Group by category (based on prefix)
    categories = {}
    for spec in ENV_VARS:
        # Determine category from name prefix
        if spec.name.startswith("KILL_SWITCH"):
            category = "Kill Switch"
        elif spec.name.startswith("RECONCILIATION"):
            category = "Reconciliation"
        elif spec.name.startswith("LATENCY"):
            category = "Latency Tracking"
        elif spec.name.startswith("POSITION_GUARD"):
            category = "Position Guard"
        elif spec.name.startswith("RISK") or spec.name.startswith("MAX_"):
            category = "Risk Management"
        elif spec.name.startswith("EQUITY") or spec.name.startswith("BALANCE"):
            category = "Equity/Balance"
        elif spec.name.startswith("ORDER"):
            category = "Order Management"
        elif spec.name.startswith("ALERT") or spec.name.endswith("WEBHOOK_URL"):
            category = "Alerting"
        elif spec.name.startswith("REDIS") or spec.name.startswith("TIMESCALE"):
            category = "Database"
        elif spec.name.startswith("BYBIT") or spec.name.startswith("OKX") or spec.name.startswith("BINANCE"):
            category = "Exchange Credentials"
        elif spec.name.startswith("QUANT"):
            category = "Quant Integration"
        else:
            category = "Core Runtime"
        
        categories.setdefault(category, []).append(spec)
    
    for category, specs in sorted(categories.items()):
        lines.append(f"\n## {category}\n")
        lines.append("| Variable | Type | Default | Required | Description |")
        lines.append("|----------|------|---------|----------|-------------|")
        
        for spec in specs:
            default = spec.default if not spec.secret else "***"
            required = "✓" if spec.required else ""
            lines.append(
                f"| `{spec.name}` | {spec.type.value} | {default} | {required} | {spec.description} |"
            )
    
    return "\n".join(lines)
