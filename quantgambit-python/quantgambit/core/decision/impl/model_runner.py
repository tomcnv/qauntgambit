"""
Model runner implementations.

Provides model inference for the decision pipeline.
"""

from typing import Optional, Dict, Any

from quantgambit.core.decision.interfaces import (
    FeatureFrame,
    ModelOutput,
    ModelRunner,
)


class PassthroughModelRunner(ModelRunner):
    """
    Passthrough model that returns a neutral probability.
    
    Use for testing or when no ML model is available.
    The signal comes from rule-based logic in the EdgeTransform.
    """
    
    def __init__(
        self,
        model_version_id: str = "passthrough:1.0.0",
        default_p: float = 0.5,
    ):
        """
        Initialize passthrough model.
        
        Args:
            model_version_id: Version identifier
            default_p: Default probability to return
        """
        self._version_id = model_version_id
        self._default_p = default_p
    
    def infer(self, frame: FeatureFrame) -> ModelOutput:
        """
        Return default probability.
        
        Args:
            frame: Feature frame (ignored)
            
        Returns:
            ModelOutput with default probability
        """
        return ModelOutput(
            model_version_id=self._version_id,
            p_raw=self._default_p,
            extra={},
        )


class ImbalanceModelRunner(ModelRunner):
    """
    Simple model that uses order book imbalance as signal.
    
    Maps imbalance to probability:
    - Positive imbalance (more bids) -> p > 0.5 (bullish)
    - Negative imbalance (more asks) -> p < 0.5 (bearish)
    """
    
    def __init__(
        self,
        model_version_id: str = "imbalance:1.0.0",
        imbalance_feature: str = "imbalance_5",
        sensitivity: float = 2.0,
    ):
        """
        Initialize imbalance model.
        
        Args:
            model_version_id: Version identifier
            imbalance_feature: Which imbalance feature to use
            sensitivity: How sensitive to imbalance (higher = more extreme probs)
        """
        self._version_id = model_version_id
        self._imbalance_feature = imbalance_feature
        self._sensitivity = sensitivity
    
    def infer(self, frame: FeatureFrame) -> ModelOutput:
        """
        Compute probability from imbalance.
        
        Args:
            frame: Feature frame
            
        Returns:
            ModelOutput with imbalance-based probability
        """
        # Find imbalance in features
        imbalance = 0.0
        if self._imbalance_feature in frame["feature_names"]:
            idx = frame["feature_names"].index(self._imbalance_feature)
            imbalance = frame["x"][idx]
        
        # Map imbalance [-1, 1] to probability [0, 1]
        # Using sigmoid-like transformation
        import math
        z = imbalance * self._sensitivity
        p_raw = 1 / (1 + math.exp(-z))
        
        return ModelOutput(
            model_version_id=self._version_id,
            p_raw=p_raw,
            extra={
                "imbalance": imbalance,
                "z": z,
            },
        )


class ONNXModelRunner(ModelRunner):
    """
    Model runner that loads and runs an ONNX model.
    
    Placeholder for production ML model integration.
    """
    
    def __init__(
        self,
        model_path: str,
        model_version_id: Optional[str] = None,
    ):
        """
        Initialize ONNX model runner.
        
        Args:
            model_path: Path to ONNX model file
            model_version_id: Version identifier (derived from path if not provided)
        """
        self._model_path = model_path
        self._version_id = model_version_id or f"onnx:{model_path}"
        self._session = None
        
        # Lazy load - don't require onnxruntime unless used
    
    def _load_model(self):
        """Load ONNX model on first use."""
        if self._session is None:
            try:
                import onnxruntime as ort
                self._session = ort.InferenceSession(self._model_path)
            except ImportError:
                raise ImportError("onnxruntime required for ONNXModelRunner")
    
    def infer(self, frame: FeatureFrame) -> ModelOutput:
        """
        Run ONNX model inference.
        
        Args:
            frame: Feature frame
            
        Returns:
            ModelOutput with model prediction
        """
        self._load_model()
        
        import numpy as np
        
        # Prepare input
        x = np.array([frame["x"]], dtype=np.float32)
        
        # Run inference
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: x})
        
        # Extract probability (assumes binary classification with sigmoid output)
        p_raw = float(outputs[0][0])
        
        return ModelOutput(
            model_version_id=self._version_id,
            p_raw=p_raw,
            extra={
                "raw_output": outputs[0].tolist() if hasattr(outputs[0], "tolist") else outputs[0],
            },
        )
