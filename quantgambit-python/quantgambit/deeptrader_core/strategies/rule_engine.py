"""
Rule Engine - Manages strategy execution and applies user-specific rules
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base_strategy import TradingSignal
from .amt_scalping import AMTScalpingStrategy
from config.strategies import strategy_manager
from quantgambit.deeptrader_core.storage.postgres_models import UserTradingSettings
from services.event_schemas import StrategySignalEvent
from services.message_queue import message_queue


class RuleEngine:
    """Manages strategy execution with user-specific rule application"""

    def __init__(self):
        self.strategies = {}
        self.active_strategies = {}
        self.user_last_signals = {}  # user_id -> {strategy_id: last_signal_time}
        self._initialize_strategies()

    def _initialize_strategies(self):
        """Initialize available strategies"""
        # AMT Scalping Strategy
        amt_scalping = AMTScalpingStrategy()
        self.strategies[amt_scalping.strategy_id] = amt_scalping

    async def process_market_features(self, features: Dict[str, Any], user_id: str) -> List[TradingSignal]:
        """
        Process market features through all applicable strategies for a user

        Args:
            features: Market feature dictionary
            user_id: User ID to get settings for

        Returns:
            List of trading signals generated
        """
        signals = []

        try:
            # Get user trading settings
            user_settings = await UserTradingSettings.get_settings(user_id)
            if not user_settings:
                # Seed default settings so users without records can still trade
                user_settings = await UserTradingSettings.create_default_settings(user_id)
                print(f"ℹ️ Seeded default trading settings for user {user_id}")

            # Check if trading is enabled
            if not self._is_trading_enabled(user_settings):
                return signals

            # Apply user-specific filters
            if not self._passes_user_filters(features, user_settings):
                return signals

            # Run strategies that are compatible with user settings
            compatible_strategies = self._get_compatible_strategies(user_settings)
            
            if not compatible_strategies:
                print(f"⚠️ No compatible strategies found for user settings (scalping_mode: {user_settings.get('scalping_mode')})")
                return signals
            
            print(f"✅ Found {len(compatible_strategies)} compatible strategies")

            for strategy in compatible_strategies:
                try:
                    signal = await strategy.analyze_market(features, user_settings)
                    if signal:
                        print(f"🎯 Strategy {strategy.strategy_id} generated signal for {features.get('symbol')}")
                        # Apply additional user-specific rules
                        if self._validate_signal_against_user_rules(signal, user_settings):
                            signals.append(signal)
                            print(f"✅ Signal validated and approved!")

                            # Track signal for rate limiting
                            self._track_user_signal(user_id, signal.strategy_id)
                        else:
                            print(f"❌ Signal rejected by user rules validation")
                    else:
                        print(f"⏭️ Strategy {strategy.strategy_id} returned no signal for {features.get('symbol')}")

                except Exception as e:
                    print(f"❌ Error in strategy {strategy.strategy_id}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        except Exception as e:
            print(f"❌ Error in rule engine processing: {e}")

        return signals

    async def publish_signals(self, signals: List[TradingSignal]) -> None:
        """Publish trading signals to the message queue"""
        for signal in signals:
            try:
                # Calculate percentages and risk metrics
                stop_loss_percent = None
                take_profit_percent = None
                expected_rr = signal.risk_reward_ratio or 2.0
                
                if signal.entry_price and signal.stop_loss_price:
                    stop_loss_percent = abs((signal.stop_loss_price - signal.entry_price) / signal.entry_price * 100)
                
                if signal.entry_price and signal.take_profit_price:
                    take_profit_percent = abs((signal.take_profit_price - signal.entry_price) / signal.entry_price * 100)
                
                # Create event with ALL required fields
                event = StrategySignalEvent(
                    source_worker="strategy_worker",
                    strategy_id=signal.strategy_id,
                    strategy_version="1.0.0",
                    symbol=signal.symbol,
                    exchange=signal.exchange,
                    user_id=signal.user_id,
                    signal_type="entry" if signal.action in ["buy", "sell"] else "exit",
                    action=signal.action,
                    confidence=signal.confidence,
                    reasoning=signal.reasoning,
                    explanation={
                        "features_snapshot": signal.features_snapshot,
                        "risk_reward_ratio": signal.risk_reward_ratio,
                        "holding_period_minutes": signal.holding_period_minutes
                    },
                    # Position parameters
                    target_size_usd=signal.position_size_usd or 0.0,
                    target_size_percent=signal.position_size_percent or 1.0,
                    entry_price=signal.entry_price,
                    stop_loss_price=signal.stop_loss_price,
                    take_profit_price=signal.take_profit_price,
                    stop_loss_percent=stop_loss_percent,
                    take_profit_percent=take_profit_percent,
                    # Risk metrics
                    expected_risk_reward=expected_rr,
                    max_drawdown_risk=stop_loss_percent,
                    probability_of_success=signal.confidence / 10.0,  # Convert 0-10 to 0-1
                    # Feature snapshot
                    feature_snapshot=signal.features_snapshot or {}
                )

                # Publish to message queue
                await message_queue.publish_event(event)

                print(f"📤 Published signal: {signal.strategy_id} {signal.action} {signal.symbol} (confidence: {signal.confidence:.1f})")

            except Exception as e:
                print(f"❌ Failed to publish signal for {signal.symbol}: {e}")

    def _is_trading_enabled(self, user_settings: Dict[str, Any]) -> bool:
        """Check if trading is enabled for the user"""
        # Could add additional checks here (account status, etc.)
        return True

    def _passes_user_filters(self, features: Dict[str, Any], user_settings: Dict[str, Any]) -> bool:
        """Apply user-specific market filters"""
        symbol = features.get("symbol")

        # Check if symbol is enabled
        enabled_tokens = user_settings.get("enabled_tokens", [])
        if symbol not in enabled_tokens:
            print(f"⏭️ {symbol} not in enabled tokens: {enabled_tokens}")
            return False

        # Check minimum confidence threshold
        # NOTE: Lowered from 0.7 to 0.1 since we're still building up data sources
        min_confidence = user_settings.get("ai_confidence_threshold", 7.0)
        feature_confidence = features.get("feature_confidence", 0)
        # Try both field names for data completeness
        data_completeness = features.get("data_completeness_score") or features.get("data_completeness", 0)
        
        # Allow trading with basic market data (price + AMT features)
        # Disabled for now - we have AMT features which is sufficient for scalping
        # if data_completeness < 0.15:  # Need at least basic market data
        #     print(f"⏭️ {symbol} data completeness too low: {data_completeness:.1%} (need 15%)")
        #     return False
        
        print(f"✅ {symbol} passed user filters (data completeness: {data_completeness:.1%})")

        # Check data quality
        data_quality = features.get("data_quality", {})
        if data_quality.get("overall_quality") == "poor":
            print(f"⏭️ {symbol} data quality is poor")
            return False

        return True

    def _get_compatible_strategies(self, user_settings: Dict[str, Any]) -> List:
        """Get strategies compatible with user settings"""
        compatible = []

        for strategy in self.strategies.values():
            # Check trading mode compatibility
            if strategy.trading_mode.name.lower() == "scalping":
                if not user_settings.get("scalping_mode", False):
                    continue
            elif strategy.trading_mode.name.lower() == "day_trading":
                if not user_settings.get("day_trading_enabled", False):
                    continue

            # Check if strategy is active
            if not strategy.get_performance_metrics().get("is_active", True):
                continue

            compatible.append(strategy)

        return compatible

    def _validate_signal_against_user_rules(self, signal: TradingSignal, user_settings: Dict[str, Any]) -> bool:
        """Apply additional user-specific validation rules"""
        # Check position size limits
        max_position_percent = user_settings.get("max_position_size_percent", 0.10)
        max_total_exposure = user_settings.get("max_total_exposure_percent", 0.40)

        # This would check against current positions - simplified for now
        if signal.position_size_usd:
            # Assume we have $10k capital for demo
            capital = 10000
            position_fraction = signal.position_size_usd / capital
            if position_fraction > max_position_percent:
                return False

        # Check order type compatibility
        enabled_order_types = user_settings.get("enabled_order_types", ["bracket"])
        # For scalping, we typically want bracket orders
        if signal.action in ["buy", "sell"] and "bracket" not in enabled_order_types:
            return False

        # Check confidence threshold
        min_confidence = user_settings.get("ai_confidence_threshold", 7.0)
        if signal.confidence < min_confidence:
            return False

        # Check rate limiting
        if not self._check_signal_rate_limit(signal, user_settings):
            return False

        return True

    def _track_user_signal(self, user_id: str, strategy_id: str):
        """Track signal timing for rate limiting"""
        if user_id not in self.user_last_signals:
            self.user_last_signals[user_id] = {}

        self.user_last_signals[user_id][strategy_id] = datetime.utcnow()

    def _check_signal_rate_limit(self, signal: TradingSignal, user_settings: Dict[str, Any]) -> bool:
        """Check if signal passes rate limiting rules"""
        user_signals = self.user_last_signals.get(signal.user_id, {})
        last_signal_time = user_signals.get(signal.strategy_id)

        if not last_signal_time:
            return True

        # Check minimum time between signals
        time_since_last = (datetime.utcnow() - last_signal_time).total_seconds()
        min_interval = 300  # 5 minutes default

        # Adjust based on strategy type
        if "scalping" in signal.strategy_id:
            min_interval = user_settings.get("scalping_min_volume_multiplier", 2) * 60  # 2-5 minutes
        elif "day_trading" in signal.strategy_id:
            min_interval = 300  # 5 minutes

        return time_since_last >= min_interval

    async def get_user_active_strategies(self, user_id: str) -> Dict[str, Any]:
        """Get information about active strategies for a user"""
        user_settings = await UserTradingSettings.get_settings(user_id)
        if not user_settings:
            return {}

        compatible_strategies = self._get_compatible_strategies(user_settings)

        return {
            "user_id": user_id,
            "active_strategies": [s.strategy_id for s in compatible_strategies],
            "trading_mode": self._get_user_trading_mode(user_settings),
            "strategy_count": len(compatible_strategies),
            "last_signals": self.user_last_signals.get(user_id, {})
        }

    def _get_user_trading_mode(self, user_settings: Dict[str, Any]) -> str:
        """Determine user's primary trading mode"""
        if user_settings.get("scalping_mode"):
            return "scalping"
        elif user_settings.get("day_trading_enabled"):
            return "day_trading"
        else:
            return "swing_trading"

    async def update_strategy_performance(self, user_id: str, strategy_id: str, outcome: str):
        """Update strategy performance metrics"""
        if strategy_id in self.strategies:
            self.strategies[strategy_id].update_performance(None, outcome)  # Simplified

    def get_engine_status(self) -> Dict[str, Any]:
        """Get rule engine status"""
        return {
            "total_strategies": len(self.strategies),
            "active_users": len(self.user_last_signals),
            "strategies": {sid: s.get_performance_metrics() for sid, s in self.strategies.items()},
            "last_update": datetime.utcnow().isoformat()
        }


# Global rule engine instance
rule_engine = RuleEngine()
