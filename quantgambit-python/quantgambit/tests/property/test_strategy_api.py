"""
Property-based tests for Strategy Registry API endpoint.

Feature: backtesting-api-integration
Tests Property 8 from the design document.

Property 8: Strategy List Completeness
For any strategy registry query, the response should contain id, name,
description, parameters, and default values for each strategy.

**Validates: Requirements R4.1**
"""

import pytest
from hypothesis import given, strategies as st, settings
from typing import List, Any, Optional

from quantgambit.api.backtest_endpoints import (
    StrategyInfo,
    StrategyParameter,
    StrategyListResponse,
    get_strategy_registry,
    STRATEGY_REGISTRY,
)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Strategy for generating parameter types
param_types = st.sampled_from(["float", "int", "bool", "str"])

# Strategy for generating parameter names
param_names = st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_")

# Strategy for generating strategy IDs
strategy_ids = st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-")

# Strategy for generating strategy names
strategy_names = st.text(min_size=1, max_size=100, alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_")

# Strategy for generating descriptions
descriptions = st.text(min_size=1, max_size=500)


@st.composite
def strategy_parameters(draw) -> List[StrategyParameter]:
    """Generate a list of strategy parameters."""
    num_params = draw(st.integers(min_value=0, max_value=5))
    params = []
    
    for i in range(num_params):
        param_type = draw(param_types)
        param_name = draw(param_names)
        
        # Generate appropriate default value based on type
        if param_type == "float":
            default = draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
            min_val = draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)))
            max_val = draw(st.one_of(st.none(), st.floats(min_value=50.0, max_value=100.0, allow_nan=False, allow_infinity=False)))
        elif param_type == "int":
            default = draw(st.integers(min_value=0, max_value=100))
            min_val = draw(st.one_of(st.none(), st.floats(min_value=0, max_value=50)))
            max_val = draw(st.one_of(st.none(), st.floats(min_value=50, max_value=100)))
        elif param_type == "bool":
            default = draw(st.booleans())
            min_val = None
            max_val = None
        else:  # str
            default = draw(st.text(min_size=0, max_size=20))
            min_val = None
            max_val = None
        
        params.append(StrategyParameter(
            name=param_name,
            type=param_type,
            description=f"Parameter {param_name} description",
            default=default,
            min_value=min_val,
            max_value=max_val,
        ))
    
    return params


@st.composite
def strategy_infos(draw) -> StrategyInfo:
    """Generate a valid StrategyInfo instance."""
    params = draw(strategy_parameters())
    
    # Build default values from parameters
    default_values = {}
    for param in params:
        if param.default is not None:
            default_values[param.name] = param.default
    
    return StrategyInfo(
        id=draw(strategy_ids),
        name=draw(strategy_names),
        description=draw(descriptions),
        parameters=params,
        default_values=default_values,
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestStrategyListCompleteness:
    """
    Property 8: Strategy List Completeness
    
    For any strategy registry query, the response should contain id, name,
    description, parameters, and default values for each strategy.
    
    **Validates: Requirements R4.1**
    """
    
    def test_registry_returns_strategies(self):
        """
        Property 8: Strategy List Completeness - Registry returns strategies
        
        The strategy registry should return a non-empty list of strategies.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        
        assert strategies is not None, "Strategy registry should not be None"
        assert len(strategies) > 0, "Strategy registry should contain at least one strategy"
    
    @settings(max_examples=100)
    @given(strategy_index=st.integers(min_value=0, max_value=len(STRATEGY_REGISTRY) - 1))
    def test_each_strategy_has_required_fields(self, strategy_index: int):
        """
        Property 8: Strategy List Completeness - Required fields present
        
        For any strategy in the registry, it should have all required fields:
        id, name, description, parameters, and default_values.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        strategy = strategies[strategy_index]
        
        # Verify required fields are present and non-empty
        assert strategy.id is not None and len(strategy.id) > 0, \
            f"Strategy should have a non-empty id"
        assert strategy.name is not None and len(strategy.name) > 0, \
            f"Strategy {strategy.id} should have a non-empty name"
        assert strategy.description is not None and len(strategy.description) > 0, \
            f"Strategy {strategy.id} should have a non-empty description"
        assert strategy.parameters is not None, \
            f"Strategy {strategy.id} should have parameters (can be empty list)"
        assert strategy.default_values is not None, \
            f"Strategy {strategy.id} should have default_values (can be empty dict)"
    
    @settings(max_examples=100)
    @given(strategy_index=st.integers(min_value=0, max_value=len(STRATEGY_REGISTRY) - 1))
    def test_parameters_have_required_fields(self, strategy_index: int):
        """
        Property 8: Strategy List Completeness - Parameter fields present
        
        For any parameter in any strategy, it should have all required fields:
        name, type, and description.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        strategy = strategies[strategy_index]
        
        for param in strategy.parameters:
            assert param.name is not None and len(param.name) > 0, \
                f"Parameter in strategy {strategy.id} should have a non-empty name"
            assert param.type is not None and len(param.type) > 0, \
                f"Parameter {param.name} in strategy {strategy.id} should have a non-empty type"
            assert param.description is not None and len(param.description) > 0, \
                f"Parameter {param.name} in strategy {strategy.id} should have a non-empty description"
    
    @settings(max_examples=100)
    @given(strategy_index=st.integers(min_value=0, max_value=len(STRATEGY_REGISTRY) - 1))
    def test_default_values_match_parameters(self, strategy_index: int):
        """
        Property 8: Strategy List Completeness - Default values consistency
        
        For any strategy, the default_values dict should contain values for
        parameters that have defaults defined.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        strategy = strategies[strategy_index]
        
        # Check that parameters with defaults have corresponding entries in default_values
        for param in strategy.parameters:
            if param.default is not None:
                assert param.name in strategy.default_values, \
                    f"Parameter {param.name} with default should be in default_values for strategy {strategy.id}"
                assert strategy.default_values[param.name] == param.default, \
                    f"Default value for {param.name} should match in strategy {strategy.id}"
    
    @settings(max_examples=100)
    @given(strategy_index=st.integers(min_value=0, max_value=len(STRATEGY_REGISTRY) - 1))
    def test_parameter_types_are_valid(self, strategy_index: int):
        """
        Property 8: Strategy List Completeness - Valid parameter types
        
        For any parameter, the type should be one of the valid types:
        float, int, bool, str.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        strategy = strategies[strategy_index]
        
        valid_types = {"float", "int", "bool", "str"}
        
        for param in strategy.parameters:
            assert param.type in valid_types, \
                f"Parameter {param.name} in strategy {strategy.id} has invalid type {param.type}"
    
    @settings(max_examples=100)
    @given(strategy_index=st.integers(min_value=0, max_value=len(STRATEGY_REGISTRY) - 1))
    def test_numeric_parameters_have_valid_bounds(self, strategy_index: int):
        """
        Property 8: Strategy List Completeness - Valid numeric bounds
        
        For any numeric parameter (float or int), if min_value and max_value
        are both specified, min_value should be less than or equal to max_value.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        strategy = strategies[strategy_index]
        
        for param in strategy.parameters:
            if param.type in ("float", "int"):
                if param.min_value is not None and param.max_value is not None:
                    assert param.min_value <= param.max_value, \
                        f"Parameter {param.name} in strategy {strategy.id}: min_value should be <= max_value"
                
                # If default is specified and bounds exist, default should be within bounds
                if param.default is not None:
                    if param.min_value is not None:
                        assert param.default >= param.min_value, \
                            f"Parameter {param.name} in strategy {strategy.id}: default should be >= min_value"
                    if param.max_value is not None:
                        assert param.default <= param.max_value, \
                            f"Parameter {param.name} in strategy {strategy.id}: default should be <= max_value"
    
    def test_strategy_ids_are_unique(self):
        """
        Property 8: Strategy List Completeness - Unique strategy IDs
        
        All strategy IDs in the registry should be unique.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        
        ids = [s.id for s in strategies]
        unique_ids = set(ids)
        
        assert len(ids) == len(unique_ids), \
            f"Strategy IDs should be unique. Found duplicates: {[id for id in ids if ids.count(id) > 1]}"
    
    def test_response_model_structure(self):
        """
        Property 8: Strategy List Completeness - Response model structure
        
        The StrategyListResponse should correctly wrap the strategies list
        and include the total count.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        strategies = get_strategy_registry()
        
        response = StrategyListResponse(
            strategies=strategies,
            total=len(strategies),
        )
        
        assert response.strategies == strategies, "Response should contain all strategies"
        assert response.total == len(strategies), "Response total should match strategy count"
    
    @given(strategy=strategy_infos())
    @settings(max_examples=100)
    def test_generated_strategy_has_valid_structure(self, strategy: StrategyInfo):
        """
        Property 8: Strategy List Completeness - Generated strategies valid
        
        For any generated StrategyInfo, it should have a valid structure
        with all required fields.
        
        **Validates: Requirements R4.1**
        """
        # Feature: backtesting-api-integration, Property 8: Strategy List Completeness
        
        # Verify required fields
        assert strategy.id is not None
        assert strategy.name is not None
        assert strategy.description is not None
        assert strategy.parameters is not None
        assert strategy.default_values is not None
        
        # Verify parameters have required fields
        for param in strategy.parameters:
            assert param.name is not None
            assert param.type is not None
            assert param.description is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
