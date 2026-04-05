"""
Default trading settings for new users
"""
from typing import Dict, Any


def get_default_trading_settings() -> Dict[str, Any]:
    """Get default trading settings matching the Node.js implementation"""
    return {
        # Order Types
        "enabled_order_types": ["bracket"],
        "order_type_settings": {
            "market": {
                "enabled": False,
                "slippage_limit": 0.5,
                "post_only": False
            },
            "limit": {
                "enabled": False,
                "time_in_force": "GTC",
                "post_only": True,
                "price_offset": 0.001
            },
            "stop_loss": {
                "enabled": False,
                "time_in_force": "GTC",
                "reduce_only": True,
                "close_position": False
            },
            "stop_limit": {
                "enabled": False,
                "time_in_force": "GTC",
                "reduce_only": True
            },
            "trailing_stop": {
                "enabled": False,
                "activation_price": None,
                "callback_rate": 1.0,
                "reduce_only": True
            },
            "take_profit": {
                "enabled": False,
                "time_in_force": "GTC",
                "reduce_only": True,
                "close_position": False
            },
            "bracket": {
                "enabled": True,
                "stop_loss_percent": 0.02,
                "take_profit_percent": 0.05,
                "time_in_force": "GTC"
            },
            "oco": {
                "enabled": False,
                "time_in_force": "GTC"
            }
        },

        # Risk Management
        "risk_profile": "moderate",
        "max_concurrent_positions": 4,
        "max_position_size_percent": 0.10,
        "max_total_exposure_percent": 0.40,
        "ai_confidence_threshold": 7.0,

        # Trading Strategy
        "trading_interval": 300000,  # 5 minutes in milliseconds
        "enabled_tokens": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "ZECUSDT"],

        # AI Filter Settings (NEW)
        "ai_filter_enabled": True,  # Enable AI regime analysis
        "ai_filter_mode": "filter_only",  # "filter_only" or "full_control"
        "ai_swing_trading_enabled": False,  # Future feature
        "strategy_selection": "amt_scalping",  # "amt_scalping", "pure_technical", or "ai_swing"

        # Trading Modes
        "day_trading_enabled": False,
        "scalping_mode": False,

        # Advanced Features
        "trailing_stops_enabled": True,
        "partial_profits_enabled": True,
        "time_based_exits_enabled": True,
        "multi_timeframe_confirmation": False,

        # Day Trading Settings
        "day_trading_max_holding_hours": 8.0,
        "day_trading_start_time": "09:30:00",
        "day_trading_end_time": "15:30:00",
        "day_trading_force_close_time": "15:45:00",
        "day_trading_days_only": False,

        # Scalping Settings
        "scalping_target_profit_percent": 0.005,
        "scalping_max_holding_minutes": 15,
        "scalping_min_volume_multiplier": 2.0,

        # Trailing Stops Settings
        "trailing_stop_activation_percent": 0.02,
        "trailing_stop_callback_percent": 0.01,
        "trailing_stop_step_percent": 0.005,

        # Partial Profit Settings
        "partial_profit_levels": [
            {"percent": 25, "target": 0.03},
            {"percent": 25, "target": 0.05},
            {"percent": 25, "target": 0.08},
            {"percent": 25, "target": 0.12}
        ],

        # Time-Based Exit Settings
        "time_exit_max_holding_hours": 24.0,
        "time_exit_break_even_hours": 4.0,
        "time_exit_weekend_close": True,

        # Multi-Timeframe Confirmation Settings
        "mtf_required_timeframes": ["15m", "1h", "4h"],
        "mtf_min_confirmations": 2,
        "mtf_trend_alignment_required": True,

        # Leverage Settings
        "leverage_enabled": False,
        "max_leverage": 1.0,
        "leverage_mode": "isolated",
        "liquidation_buffer_percent": 0.05,
        "margin_call_threshold_percent": 0.20,
        "available_leverage_levels": [1, 2, 3, 5, 10]
    }
