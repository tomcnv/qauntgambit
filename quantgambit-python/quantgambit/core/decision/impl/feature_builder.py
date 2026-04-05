"""
Default FeatureFrameBuilder implementation.

Extracts features from market data for model inference.
"""

from typing import List, Dict, Any, Optional
import math

from quantgambit.core.clock import Clock, get_clock
from quantgambit.core.decision.interfaces import (
    FeatureFrame,
    DecisionInput,
    FeatureFrameBuilder,
)
from quantgambit.core.book.types import BookSide


# Default feature set version
DEFAULT_FEATURE_SET_VERSION = "v1.0.0"


class DefaultFeatureFrameBuilder(FeatureFrameBuilder):
    """
    Default feature builder extracting microstructure features.
    
    Features extracted:
    - Spread (bps)
    - Imbalance at multiple depths
    - Microprice
    - Book depth
    - Position metrics
    """
    
    def __init__(
        self,
        feature_set_version_id: str = DEFAULT_FEATURE_SET_VERSION,
        imbalance_depths: List[int] = None,
        clock: Optional[Clock] = None,
    ):
        """
        Initialize feature builder.
        
        Args:
            feature_set_version_id: Version identifier for feature set
            imbalance_depths: Depths to compute imbalance at
            clock: Clock for timestamps
        """
        self._version_id = feature_set_version_id
        self._imbalance_depths = imbalance_depths or [1, 3, 5, 10]
        self._clock = clock or get_clock()
        
        # Build feature names
        self._feature_names = self._build_feature_names()
    
    def _build_feature_names(self) -> List[str]:
        """Build ordered list of feature names."""
        names = [
            "spread_bps",
            "mid_price",
            "microprice",
            "bid_depth",
            "ask_depth",
            "total_depth",
        ]
        
        # Imbalance at each depth
        for depth in self._imbalance_depths:
            names.append(f"imbalance_{depth}")
        
        # Position features
        names.extend([
            "position_size",
            "position_pnl_pct",
            "position_duration_sec",
        ])
        
        return names
    
    def build(self, decision_input: DecisionInput) -> FeatureFrame:
        """
        Build feature frame from decision input.
        
        Args:
            decision_input: Complete decision input
            
        Returns:
            FeatureFrame with computed features
        """
        book = decision_input.book
        features: Dict[str, float] = {}
        missing: Dict[str, bool] = {}
        quality_issues = 0
        
        # Spread
        spread_bps = book.spread_bps
        if spread_bps is not None:
            features["spread_bps"] = spread_bps
            missing["spread_bps"] = False
        else:
            features["spread_bps"] = 0.0
            missing["spread_bps"] = True
            quality_issues += 1
        
        # Mid price
        mid = book.mid_price
        if mid is not None:
            features["mid_price"] = mid
            missing["mid_price"] = False
        else:
            features["mid_price"] = 0.0
            missing["mid_price"] = True
            quality_issues += 1
        
        # Microprice
        microprice = book.microprice()
        if microprice is not None:
            features["microprice"] = microprice
            missing["microprice"] = False
        else:
            features["microprice"] = features["mid_price"]
            missing["microprice"] = True
            quality_issues += 1
        
        # Depth
        features["bid_depth"] = float(len(book.bids))
        features["ask_depth"] = float(len(book.asks))
        features["total_depth"] = features["bid_depth"] + features["ask_depth"]
        missing["bid_depth"] = False
        missing["ask_depth"] = False
        missing["total_depth"] = False
        
        # Imbalance at various depths
        for depth in self._imbalance_depths:
            imb = book.imbalance(levels=depth)
            key = f"imbalance_{depth}"
            if imb is not None:
                features[key] = imb
                missing[key] = False
            else:
                features[key] = 0.0
                missing[key] = True
                quality_issues += 1
        
        # Position features
        features["position_size"] = decision_input.current_position_size
        missing["position_size"] = False
        
        # Position PnL as percentage
        if decision_input.current_position_entry_price and decision_input.current_position_entry_price > 0:
            if mid and mid > 0:
                pnl_pct = (mid - decision_input.current_position_entry_price) / decision_input.current_position_entry_price * 100
                if decision_input.current_position_side == "short":
                    pnl_pct = -pnl_pct
                features["position_pnl_pct"] = pnl_pct
                missing["position_pnl_pct"] = False
            else:
                features["position_pnl_pct"] = 0.0
                missing["position_pnl_pct"] = True
        else:
            features["position_pnl_pct"] = 0.0
            missing["position_pnl_pct"] = False  # No position = 0 PnL is valid
        
        # Position duration (placeholder - would need position open time)
        features["position_duration_sec"] = 0.0
        missing["position_duration_sec"] = decision_input.current_position_size != 0
        
        # Build feature vector in consistent order
        x = [features.get(name, 0.0) for name in self._feature_names]
        
        # Compute quality score (1 - fraction of missing features)
        total_features = len(self._feature_names)
        quality_score = max(0.0, 1.0 - quality_issues / total_features)
        
        return FeatureFrame(
            symbol=decision_input.symbol,
            ts_mono=decision_input.ts_mono,
            feature_set_version_id=self._version_id,
            feature_names=self._feature_names,
            x=x,
            quality_score=quality_score,
            missing=missing,
        )
    
    @property
    def feature_names(self) -> List[str]:
        """Get ordered list of feature names."""
        return self._feature_names.copy()
    
    @property
    def version_id(self) -> str:
        """Get feature set version ID."""
        return self._version_id
