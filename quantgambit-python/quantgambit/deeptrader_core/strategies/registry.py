"""Strategy Registry - Central registry of available strategies

Provides O(1) lookup of strategy instances by ID.
New strategies are added here to make them available to the routing system.
"""

from typing import Dict
from .base import Strategy
from .amt_value_area_rejection_scalp import AmtValueAreaRejectionScalp
from .poc_magnet_scalp import POCMagnetScalp
from .breakout_scalp import BreakoutScalp
from .mean_reversion_fade import MeanReversionFade
from .trend_pullback import TrendPullback
from .chop_zone_avoid import ChopZoneAvoid
from .opening_range_breakout import OpeningRangeBreakout
from .asia_range_scalp import AsiaRangeScalp
from .europe_open_vol import EuropeOpenVol
from .us_open_momentum import USOpenMomentum
from .overnight_thin import OvernightThin
from .high_vol_breakout import HighVolBreakout  # Phase 3
from .low_vol_grind import LowVolGrind  # Phase 3
from .vol_expansion import VolExpansion  # Phase 3
from .liquidity_hunt import LiquidityHunt  # Phase 4
from .order_flow_imbalance import OrderFlowImbalance  # Phase 4
from .spread_compression import SpreadCompression  # Phase 4
from .vwap_reversion import VWAPReversion  # Phase 4
from .volume_profile_cluster import VolumeProfileCluster  # Phase 4
from .drawdown_recovery import DrawdownRecovery  # Phase 5
from .max_profit_protection import MaxProfitProtection  # Phase 5
from .test_signal_generator import TestSignalGenerator  # Testing only
from .spot_dip_accumulator import SpotDipAccumulator  # Spot trading
from .spot_momentum_breakout import SpotMomentumBreakout  # Spot trading
from .spot_mean_reversion import SpotMeanReversion  # Spot trading
from .spread_capture_scalp import SpreadCaptureScalp  # Mean-reversion spread capture
from .liquidity_fade_scalp import LiquidityFadeScalp  # Liquidation cascade fade


STRATEGIES: Dict[str, Strategy] = {
    "amt_value_area_rejection_scalp": AmtValueAreaRejectionScalp(),
    "poc_magnet_scalp": POCMagnetScalp(),
    "breakout_scalp": BreakoutScalp(),
    "mean_reversion_fade": MeanReversionFade(),
    "trend_pullback": TrendPullback(),
    "chop_zone_avoid": ChopZoneAvoid(),
    "opening_range_breakout": OpeningRangeBreakout(),
    "asia_range_scalp": AsiaRangeScalp(),
    "europe_open_vol": EuropeOpenVol(),
    "us_open_momentum": USOpenMomentum(),
    "overnight_thin": OvernightThin(),
    "high_vol_breakout": HighVolBreakout(),  # Phase 3
    "low_vol_grind": LowVolGrind(),  # Phase 3
    "vol_expansion": VolExpansion(),  # Phase 3
    "liquidity_hunt": LiquidityHunt(),  # Phase 4
    "order_flow_imbalance": OrderFlowImbalance(),  # Phase 4
    "spread_compression": SpreadCompression(),  # Phase 4
    "vwap_reversion": VWAPReversion(),  # Phase 4
    "volume_profile_cluster": VolumeProfileCluster(),  # Phase 4
    "drawdown_recovery": DrawdownRecovery(),  # Phase 5
    "max_profit_protection": MaxProfitProtection(),  # Phase 5
    "test_signal_generator": TestSignalGenerator(),  # Testing only
    "spot_dip_accumulator": SpotDipAccumulator(),  # Spot trading
    "spot_momentum_breakout": SpotMomentumBreakout(),  # Spot trading
    "spot_mean_reversion": SpotMeanReversion(),  # Spot trading
    "spread_capture_scalp": SpreadCaptureScalp(),  # Mean-reversion spread capture
    "liquidity_fade_scalp": LiquidityFadeScalp(),  # Liquidation cascade fade
}

