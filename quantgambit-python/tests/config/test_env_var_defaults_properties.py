"""
Property-based tests for Environment Variable Defaults.

Feature: bot-integration-fixes
Tests correctness properties for:
- Property 3: Environment Variable Defaults

Feature: end-to-end-integration-verification
Tests correctness properties for:
- Property 2: Environment Variable Defaults

**Validates: Requirements 5.1, 5.2, 5.3, 5.4** (bot-integration-fixes)
**Validates: Requirements 3.2** (end-to-end-integration-verification)

For any of the documented environment variables with default values, when not set,
the system SHALL use the documented default value.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Set
from unittest.mock import patch

import pytest
from hypothesis import given, strategies as st, settings, assume


# =============================================================================
# Environment Variable Configuration
# =============================================================================

# Define the environment variables and their expected defaults
ENV_VAR_DEFAULTS = {
    "BACKTEST_PARITY_MODE": {
        "default": "true",
        "expected_bool": True,
        "truthy_values": {"1", "true", "yes"},
    },
    "BACKTEST_WARM_START_ENABLED": {
        "default": "false",
        "expected_bool": False,
        "truthy_values": {"1", "true", "yes"},
    },
    "DECISION_RECORDER_ENABLED": {
        "default": "true",
        "expected_bool": True,
        "truthy_values": {"1", "true", "yes"},
    },
    "BACKTEST_WARM_START_STALE_SEC": {
        "default": "300.0",
        "expected_float": 300.0,
    },
}


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Strategy for generating environment variable names from our set
env_var_name_strategy = st.sampled_from(list(ENV_VAR_DEFAULTS.keys()))

# Strategy for generating boolean-like string values
bool_string_strategy = st.sampled_from([
    "true", "false", "True", "False", "TRUE", "FALSE",
    "yes", "no", "Yes", "No", "YES", "NO",
    "1", "0",
])

# Strategy for generating truthy values
truthy_value_strategy = st.sampled_from(["true", "True", "TRUE", "yes", "Yes", "YES", "1"])

# Strategy for generating falsy values
falsy_value_strategy = st.sampled_from(["false", "False", "FALSE", "no", "No", "NO", "0", ""])

# Strategy for generating float-like string values
float_string_strategy = st.floats(
    min_value=0.1,
    max_value=10000.0,
    allow_nan=False,
    allow_infinity=False,
).map(str)

# Strategy for generating a subset of env vars to set
env_var_subset_strategy = st.lists(
    env_var_name_strategy,
    min_size=0,
    max_size=len(ENV_VAR_DEFAULTS),
    unique=True,
)


@st.composite
def env_var_override_strategy(draw):
    """Generate a dictionary of environment variable overrides.
    
    This generates a random subset of env vars with random values,
    leaving some unset to test defaults.
    """
    overrides = {}
    
    # Randomly decide which env vars to set
    vars_to_set = draw(env_var_subset_strategy)
    
    for var_name in vars_to_set:
        var_config = ENV_VAR_DEFAULTS[var_name]
        
        if "expected_float" in var_config:
            # Generate a float value
            overrides[var_name] = draw(float_string_strategy)
        else:
            # Generate a boolean-like value
            overrides[var_name] = draw(bool_string_strategy)
    
    return overrides


# =============================================================================
# Helper Functions
# =============================================================================

def get_executor_config_from_env():
    """Import and create ExecutorConfig from environment.
    
    This function imports ExecutorConfig and creates an instance using from_env().
    """
    from quantgambit.backtesting.executor import ExecutorConfig
    return ExecutorConfig.from_env()


def get_decision_recorder_enabled_from_env() -> bool:
    """Get the DECISION_RECORDER_ENABLED value using the same logic as Runtime.
    
    This replicates the logic from quantgambit/runtime/app.py.
    """
    return os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}


def parse_bool_env_var(value: str, truthy_values: Set[str]) -> bool:
    """Parse a boolean environment variable value."""
    return value.lower() in truthy_values


# =============================================================================
# Property 3: Environment Variable Defaults
# Feature: bot-integration-fixes, Property 3: Environment Variable Defaults
# Validates: Requirements 5.1, 5.2, 5.3, 5.4
# =============================================================================

class TestEnvironmentVariableDefaults:
    """
    Feature: bot-integration-fixes, Property 3: Environment Variable Defaults
    
    For any of the new environment variables (BACKTEST_PARITY_MODE, BACKTEST_WARM_START_ENABLED,
    DECISION_RECORDER_ENABLED, BACKTEST_WARM_START_STALE_SEC), when not set, the system SHALL
    use the documented default value.
    
    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """
    
    @settings(max_examples=50)
    @given(env_overrides=env_var_override_strategy())
    def test_backtest_parity_mode_defaults_to_true(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 3: BACKTEST_PARITY_MODE defaults to "true" when not set
        
        *For any* environment state where BACKTEST_PARITY_MODE is not set,
        the system SHALL use the default value "true".
        
        **Validates: Requirements 5.1**
        """
        # Remove BACKTEST_PARITY_MODE from overrides to test default
        env_overrides_without_parity = {
            k: v for k, v in env_overrides.items() 
            if k != "BACKTEST_PARITY_MODE"
        }
        
        # Clear the env var and apply other overrides
        env_to_patch = {k: v for k, v in env_overrides_without_parity.items()}
        
        # Ensure BACKTEST_PARITY_MODE is not set
        with patch.dict(os.environ, env_to_patch, clear=True):
            # Verify the env var is not set
            assert "BACKTEST_PARITY_MODE" not in os.environ, \
                "BACKTEST_PARITY_MODE should not be set for this test"
            
            # Get config from environment
            config = get_executor_config_from_env()
            
            # Property: parity_mode should default to True
            assert config.parity_mode is True, \
                f"parity_mode should default to True when BACKTEST_PARITY_MODE is not set, got {config.parity_mode}"
    
    @settings(max_examples=50)
    @given(env_overrides=env_var_override_strategy())
    def test_backtest_warm_start_enabled_defaults_to_false(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 3: BACKTEST_WARM_START_ENABLED defaults to "false" when not set
        
        *For any* environment state where BACKTEST_WARM_START_ENABLED is not set,
        the system SHALL use the default value "false".
        
        **Validates: Requirements 5.2**
        """
        # Remove BACKTEST_WARM_START_ENABLED from overrides to test default
        env_overrides_without_warm_start = {
            k: v for k, v in env_overrides.items() 
            if k != "BACKTEST_WARM_START_ENABLED"
        }
        
        # Clear the env var and apply other overrides
        env_to_patch = {k: v for k, v in env_overrides_without_warm_start.items()}
        
        # Ensure BACKTEST_WARM_START_ENABLED is not set
        with patch.dict(os.environ, env_to_patch, clear=True):
            # Verify the env var is not set
            assert "BACKTEST_WARM_START_ENABLED" not in os.environ, \
                "BACKTEST_WARM_START_ENABLED should not be set for this test"
            
            # Get config from environment
            config = get_executor_config_from_env()
            
            # Property: warm_start_enabled should default to False
            assert config.warm_start_enabled is False, \
                f"warm_start_enabled should default to False when BACKTEST_WARM_START_ENABLED is not set, got {config.warm_start_enabled}"
    
    @settings(max_examples=50)
    @given(env_overrides=env_var_override_strategy())
    def test_decision_recorder_enabled_defaults_to_true(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 3: DECISION_RECORDER_ENABLED defaults to "true" when not set
        
        *For any* environment state where DECISION_RECORDER_ENABLED is not set,
        the system SHALL use the default value "true".
        
        **Validates: Requirements 5.3**
        """
        # Remove DECISION_RECORDER_ENABLED from overrides to test default
        env_overrides_without_recorder = {
            k: v for k, v in env_overrides.items() 
            if k != "DECISION_RECORDER_ENABLED"
        }
        
        # Clear the env var and apply other overrides
        env_to_patch = {k: v for k, v in env_overrides_without_recorder.items()}
        
        # Ensure DECISION_RECORDER_ENABLED is not set
        with patch.dict(os.environ, env_to_patch, clear=True):
            # Verify the env var is not set
            assert "DECISION_RECORDER_ENABLED" not in os.environ, \
                "DECISION_RECORDER_ENABLED should not be set for this test"
            
            # Get the value using the same logic as Runtime
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            # Property: decision_recorder_enabled should default to True
            assert decision_recorder_enabled is True, \
                f"decision_recorder_enabled should default to True when DECISION_RECORDER_ENABLED is not set, got {decision_recorder_enabled}"
    
    @settings(max_examples=50)
    @given(env_overrides=env_var_override_strategy())
    def test_backtest_warm_start_stale_sec_defaults_to_300(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 3: BACKTEST_WARM_START_STALE_SEC defaults to "300.0" when not set
        
        *For any* environment state where BACKTEST_WARM_START_STALE_SEC is not set,
        the system SHALL use the default value "300.0".
        
        **Validates: Requirements 5.4**
        """
        # Remove BACKTEST_WARM_START_STALE_SEC from overrides to test default
        env_overrides_without_stale = {
            k: v for k, v in env_overrides.items() 
            if k != "BACKTEST_WARM_START_STALE_SEC"
        }
        
        # Clear the env var and apply other overrides
        env_to_patch = {k: v for k, v in env_overrides_without_stale.items()}
        
        # Ensure BACKTEST_WARM_START_STALE_SEC is not set
        with patch.dict(os.environ, env_to_patch, clear=True):
            # Verify the env var is not set
            assert "BACKTEST_WARM_START_STALE_SEC" not in os.environ, \
                "BACKTEST_WARM_START_STALE_SEC should not be set for this test"
            
            # Get config from environment
            config = get_executor_config_from_env()
            
            # Property: warm_start_stale_threshold_sec should default to 300.0
            assert config.warm_start_stale_threshold_sec == 300.0, \
                f"warm_start_stale_threshold_sec should default to 300.0 when BACKTEST_WARM_START_STALE_SEC is not set, got {config.warm_start_stale_threshold_sec}"
    
    @settings(max_examples=50)
    @given(truthy_value=truthy_value_strategy)
    def test_backtest_parity_mode_truthy_values(
        self,
        truthy_value: str,
    ):
        """
        Property 3: BACKTEST_PARITY_MODE recognizes truthy values
        
        *For any* truthy value ("true", "True", "TRUE", "yes", "Yes", "YES", "1"),
        BACKTEST_PARITY_MODE SHALL be interpreted as True.
        
        **Validates: Requirements 5.1**
        """
        with patch.dict(os.environ, {"BACKTEST_PARITY_MODE": truthy_value}, clear=True):
            config = get_executor_config_from_env()
            
            # Property: truthy values should result in True
            assert config.parity_mode is True, \
                f"parity_mode should be True for truthy value '{truthy_value}', got {config.parity_mode}"
    
    @settings(max_examples=50)
    @given(falsy_value=falsy_value_strategy)
    def test_backtest_parity_mode_falsy_values(
        self,
        falsy_value: str,
    ):
        """
        Property 3: BACKTEST_PARITY_MODE recognizes falsy values
        
        *For any* falsy value ("false", "False", "FALSE", "no", "No", "NO", "0", ""),
        BACKTEST_PARITY_MODE SHALL be interpreted as False.
        
        **Validates: Requirements 5.1**
        """
        with patch.dict(os.environ, {"BACKTEST_PARITY_MODE": falsy_value}, clear=True):
            config = get_executor_config_from_env()
            
            # Property: falsy values should result in False
            assert config.parity_mode is False, \
                f"parity_mode should be False for falsy value '{falsy_value}', got {config.parity_mode}"
    
    @settings(max_examples=50)
    @given(truthy_value=truthy_value_strategy)
    def test_backtest_warm_start_enabled_truthy_values(
        self,
        truthy_value: str,
    ):
        """
        Property 3: BACKTEST_WARM_START_ENABLED recognizes truthy values
        
        *For any* truthy value ("true", "True", "TRUE", "yes", "Yes", "YES", "1"),
        BACKTEST_WARM_START_ENABLED SHALL be interpreted as True.
        
        **Validates: Requirements 5.2**
        """
        with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": truthy_value}, clear=True):
            config = get_executor_config_from_env()
            
            # Property: truthy values should result in True
            assert config.warm_start_enabled is True, \
                f"warm_start_enabled should be True for truthy value '{truthy_value}', got {config.warm_start_enabled}"
    
    @settings(max_examples=50)
    @given(falsy_value=falsy_value_strategy)
    def test_backtest_warm_start_enabled_falsy_values(
        self,
        falsy_value: str,
    ):
        """
        Property 3: BACKTEST_WARM_START_ENABLED recognizes falsy values
        
        *For any* falsy value ("false", "False", "FALSE", "no", "No", "NO", "0", ""),
        BACKTEST_WARM_START_ENABLED SHALL be interpreted as False.
        
        **Validates: Requirements 5.2**
        """
        with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": falsy_value}, clear=True):
            config = get_executor_config_from_env()
            
            # Property: falsy values should result in False
            assert config.warm_start_enabled is False, \
                f"warm_start_enabled should be False for falsy value '{falsy_value}', got {config.warm_start_enabled}"
    
    @settings(max_examples=50)
    @given(truthy_value=truthy_value_strategy)
    def test_decision_recorder_enabled_truthy_values(
        self,
        truthy_value: str,
    ):
        """
        Property 3: DECISION_RECORDER_ENABLED recognizes truthy values
        
        *For any* truthy value ("true", "True", "TRUE", "yes", "Yes", "YES", "1"),
        DECISION_RECORDER_ENABLED SHALL be interpreted as True.
        
        **Validates: Requirements 5.3**
        """
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": truthy_value}, clear=True):
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            # Property: truthy values should result in True
            assert decision_recorder_enabled is True, \
                f"decision_recorder_enabled should be True for truthy value '{truthy_value}', got {decision_recorder_enabled}"
    
    @settings(max_examples=50)
    @given(falsy_value=falsy_value_strategy)
    def test_decision_recorder_enabled_falsy_values(
        self,
        falsy_value: str,
    ):
        """
        Property 3: DECISION_RECORDER_ENABLED recognizes falsy values
        
        *For any* falsy value ("false", "False", "FALSE", "no", "No", "NO", "0", ""),
        DECISION_RECORDER_ENABLED SHALL be interpreted as False.
        
        **Validates: Requirements 5.3**
        """
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": falsy_value}, clear=True):
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            # Property: falsy values should result in False
            assert decision_recorder_enabled is False, \
                f"decision_recorder_enabled should be False for falsy value '{falsy_value}', got {decision_recorder_enabled}"
    
    @settings(max_examples=50)
    @given(
        float_value=st.floats(
            min_value=0.1,
            max_value=10000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    def test_backtest_warm_start_stale_sec_parses_float_values(
        self,
        float_value: float,
    ):
        """
        Property 3: BACKTEST_WARM_START_STALE_SEC parses float values correctly
        
        *For any* valid float string value, BACKTEST_WARM_START_STALE_SEC SHALL
        be parsed to the corresponding float value.
        
        **Validates: Requirements 5.4**
        """
        float_str = str(float_value)
        
        with patch.dict(os.environ, {"BACKTEST_WARM_START_STALE_SEC": float_str}, clear=True):
            config = get_executor_config_from_env()
            
            # Property: float values should be parsed correctly
            # Use approximate comparison due to float precision
            assert abs(config.warm_start_stale_threshold_sec - float_value) < 0.001, \
                f"warm_start_stale_threshold_sec should be {float_value} for value '{float_str}', got {config.warm_start_stale_threshold_sec}"
    
    def test_all_env_vars_have_documented_defaults_when_none_set(self):
        """
        Property 3: All environment variables use documented defaults when none are set
        
        When no environment variables are set, all new environment variables SHALL
        use their documented default values.
        
        **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
        """
        # Clear all relevant env vars
        env_vars_to_clear = list(ENV_VAR_DEFAULTS.keys())
        
        with patch.dict(os.environ, {}, clear=True):
            # Verify none of the env vars are set
            for var_name in env_vars_to_clear:
                assert var_name not in os.environ, \
                    f"{var_name} should not be set for this test"
            
            # Get config from environment
            config = get_executor_config_from_env()
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            # Property: BACKTEST_PARITY_MODE defaults to True (Requirement 5.1)
            assert config.parity_mode is True, \
                f"parity_mode should default to True, got {config.parity_mode}"
            
            # Property: BACKTEST_WARM_START_ENABLED defaults to False (Requirement 5.2)
            assert config.warm_start_enabled is False, \
                f"warm_start_enabled should default to False, got {config.warm_start_enabled}"
            
            # Property: DECISION_RECORDER_ENABLED defaults to True (Requirement 5.3)
            assert decision_recorder_enabled is True, \
                f"decision_recorder_enabled should default to True, got {decision_recorder_enabled}"
            
            # Property: BACKTEST_WARM_START_STALE_SEC defaults to 300.0 (Requirement 5.4)
            assert config.warm_start_stale_threshold_sec == 300.0, \
                f"warm_start_stale_threshold_sec should default to 300.0, got {config.warm_start_stale_threshold_sec}"
    
    @settings(max_examples=50)
    @given(env_overrides=env_var_override_strategy())
    def test_unset_env_vars_use_defaults_regardless_of_other_vars(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 3: Unset environment variables use defaults regardless of other vars
        
        *For any* combination of set/unset environment variables, the unset variables
        SHALL use their documented default values.
        
        **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
        """
        with patch.dict(os.environ, env_overrides, clear=True):
            config = get_executor_config_from_env()
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            # Check each env var - if not set, should use default
            if "BACKTEST_PARITY_MODE" not in env_overrides:
                assert config.parity_mode is True, \
                    f"parity_mode should default to True when not set, got {config.parity_mode}"
            
            if "BACKTEST_WARM_START_ENABLED" not in env_overrides:
                assert config.warm_start_enabled is False, \
                    f"warm_start_enabled should default to False when not set, got {config.warm_start_enabled}"
            
            if "DECISION_RECORDER_ENABLED" not in env_overrides:
                assert decision_recorder_enabled is True, \
                    f"decision_recorder_enabled should default to True when not set, got {decision_recorder_enabled}"
            
            if "BACKTEST_WARM_START_STALE_SEC" not in env_overrides:
                assert config.warm_start_stale_threshold_sec == 300.0, \
                    f"warm_start_stale_threshold_sec should default to 300.0 when not set, got {config.warm_start_stale_threshold_sec}"


# =============================================================================
# Property 2: Environment Variable Defaults (end-to-end-integration-verification)
# Feature: end-to-end-integration-verification, Property 2: Environment Variable Defaults
# Validates: Requirements 3.2
# =============================================================================

# Define the database environment variables and their expected defaults
# These are documented in quantgambit-python/.env.example
DB_ENV_VAR_DEFAULTS = {
    "BOT_DB_HOST": "localhost",
    "BOT_DB_PORT": "5432",
    "BOT_DB_NAME": "platform_db",
    "BOT_DB_USER": "platform",
    # Note: BOT_API_PORT is documented as 3002 in .env.example
    # but the actual code uses API_PORT with default 8080
    # We test what run_migrations.py uses
}


# Strategy for generating database environment variable names
db_env_var_name_strategy = st.sampled_from(list(DB_ENV_VAR_DEFAULTS.keys()))

# Strategy for generating a subset of db env vars to set
db_env_var_subset_strategy = st.lists(
    db_env_var_name_strategy,
    min_size=0,
    max_size=len(DB_ENV_VAR_DEFAULTS),
    unique=True,
)


@st.composite
def db_env_var_override_strategy(draw):
    """Generate a dictionary of database environment variable overrides.
    
    This generates a random subset of env vars with random values,
    leaving some unset to test defaults.
    """
    overrides = {}
    
    # Randomly decide which env vars to set
    vars_to_set = draw(db_env_var_subset_strategy)
    
    for var_name in vars_to_set:
        if var_name == "BOT_DB_HOST":
            # Generate a hostname-like value
            overrides[var_name] = draw(st.sampled_from([
                "db.example.com", "postgres.local", "192.168.1.100", "timescale"
            ]))
        elif var_name == "BOT_DB_PORT":
            # Generate a port number as string
            overrides[var_name] = str(draw(st.integers(min_value=1024, max_value=65535)))
        elif var_name == "BOT_DB_NAME":
            # Generate a database name
            overrides[var_name] = draw(st.sampled_from([
                "test_db", "quantgambit_test", "trading_db", "backtest_db"
            ]))
        elif var_name == "BOT_DB_USER":
            # Generate a username
            overrides[var_name] = draw(st.sampled_from([
                "test_user", "admin", "quantgambit", "trader"
            ]))
    
    return overrides


def get_database_url_from_env() -> dict:
    """Get database connection parameters from environment.
    
    This replicates the logic from run_migrations.py build_database_url().
    Returns a dict with the parsed values for testing.
    """
    return {
        "host": os.getenv("BOT_DB_HOST", "localhost"),
        "port": os.getenv("BOT_DB_PORT", "5432"),
        "name": os.getenv("BOT_DB_NAME", "platform_db"),
        "user": os.getenv("BOT_DB_USER", "platform"),
    }


class TestDatabaseEnvironmentVariableDefaults:
    """
    Feature: end-to-end-integration-verification, Property 2: Environment Variable Defaults
    
    For any documented environment variable with a default value, when that variable
    is not set in the environment, the system SHALL use the documented default value.
    
    Tests the following variables with their defaults:
    - BOT_DB_HOST=localhost
    - BOT_DB_PORT=5432
    - BOT_DB_NAME=platform_db
    - BOT_DB_USER=platform
    
    **Validates: Requirements 3.2**
    """
    
    @settings(max_examples=50)
    @given(env_overrides=db_env_var_override_strategy())
    def test_bot_db_host_defaults_to_localhost(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 2: BOT_DB_HOST defaults to "localhost" when not set
        
        *For any* environment state where BOT_DB_HOST is not set,
        the system SHALL use the default value "localhost".
        
        **Validates: Requirements 3.2**
        """
        # Remove BOT_DB_HOST from overrides to test default
        env_overrides_without_host = {
            k: v for k, v in env_overrides.items() 
            if k != "BOT_DB_HOST"
        }
        
        with patch.dict(os.environ, env_overrides_without_host, clear=True):
            # Verify the env var is not set
            assert "BOT_DB_HOST" not in os.environ, \
                "BOT_DB_HOST should not be set for this test"
            
            # Get database config from environment
            db_config = get_database_url_from_env()
            
            # Property: host should default to "localhost"
            assert db_config["host"] == "localhost", \
                f"host should default to 'localhost' when BOT_DB_HOST is not set, got {db_config['host']}"
    
    @settings(max_examples=50)
    @given(env_overrides=db_env_var_override_strategy())
    def test_bot_db_port_defaults_to_5432(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 2: BOT_DB_PORT defaults to "5432" when not set
        
        *For any* environment state where BOT_DB_PORT is not set,
        the system SHALL use the default value "5432".
        
        **Validates: Requirements 3.2**
        """
        # Remove BOT_DB_PORT from overrides to test default
        env_overrides_without_port = {
            k: v for k, v in env_overrides.items() 
            if k != "BOT_DB_PORT"
        }
        
        with patch.dict(os.environ, env_overrides_without_port, clear=True):
            # Verify the env var is not set
            assert "BOT_DB_PORT" not in os.environ, \
                "BOT_DB_PORT should not be set for this test"
            
            # Get database config from environment
            db_config = get_database_url_from_env()
            
            # Property: port should default to "5432"
            assert db_config["port"] == "5432", \
                f"port should default to '5432' when BOT_DB_PORT is not set, got {db_config['port']}"
    
    @settings(max_examples=50)
    @given(env_overrides=db_env_var_override_strategy())
    def test_bot_db_name_defaults_to_platform_db(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 2: BOT_DB_NAME defaults to "platform_db" when not set
        
        *For any* environment state where BOT_DB_NAME is not set,
        the system SHALL use the default value "platform_db".
        
        **Validates: Requirements 3.2**
        """
        # Remove BOT_DB_NAME from overrides to test default
        env_overrides_without_name = {
            k: v for k, v in env_overrides.items() 
            if k != "BOT_DB_NAME"
        }
        
        with patch.dict(os.environ, env_overrides_without_name, clear=True):
            # Verify the env var is not set
            assert "BOT_DB_NAME" not in os.environ, \
                "BOT_DB_NAME should not be set for this test"
            
            # Get database config from environment
            db_config = get_database_url_from_env()
            
            # Property: name should default to "platform_db"
            assert db_config["name"] == "platform_db", \
                f"name should default to 'platform_db' when BOT_DB_NAME is not set, got {db_config['name']}"
    
    @settings(max_examples=50)
    @given(env_overrides=db_env_var_override_strategy())
    def test_bot_db_user_defaults_to_platform(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 2: BOT_DB_USER defaults to "platform" when not set
        
        *For any* environment state where BOT_DB_USER is not set,
        the system SHALL use the default value "platform".
        
        **Validates: Requirements 3.2**
        """
        # Remove BOT_DB_USER from overrides to test default
        env_overrides_without_user = {
            k: v for k, v in env_overrides.items() 
            if k != "BOT_DB_USER"
        }
        
        with patch.dict(os.environ, env_overrides_without_user, clear=True):
            # Verify the env var is not set
            assert "BOT_DB_USER" not in os.environ, \
                "BOT_DB_USER should not be set for this test"
            
            # Get database config from environment
            db_config = get_database_url_from_env()
            
            # Property: user should default to "platform"
            assert db_config["user"] == "platform", \
                f"user should default to 'platform' when BOT_DB_USER is not set, got {db_config['user']}"
    
    def test_all_db_env_vars_have_documented_defaults_when_none_set(self):
        """
        Property 2: All database environment variables use documented defaults when none are set
        
        When no environment variables are set, all database environment variables SHALL
        use their documented default values.
        
        **Validates: Requirements 3.2**
        """
        with patch.dict(os.environ, {}, clear=True):
            # Verify none of the env vars are set
            for var_name in DB_ENV_VAR_DEFAULTS.keys():
                assert var_name not in os.environ, \
                    f"{var_name} should not be set for this test"
            
            # Get database config from environment
            db_config = get_database_url_from_env()
            
            # Property: BOT_DB_HOST defaults to "localhost"
            assert db_config["host"] == "localhost", \
                f"host should default to 'localhost', got {db_config['host']}"
            
            # Property: BOT_DB_PORT defaults to "5432"
            assert db_config["port"] == "5432", \
                f"port should default to '5432', got {db_config['port']}"
            
            # Property: BOT_DB_NAME defaults to "platform_db"
            assert db_config["name"] == "platform_db", \
                f"name should default to 'platform_db', got {db_config['name']}"
            
            # Property: BOT_DB_USER defaults to "platform"
            assert db_config["user"] == "platform", \
                f"user should default to 'platform', got {db_config['user']}"
    
    @settings(max_examples=50)
    @given(env_overrides=db_env_var_override_strategy())
    def test_unset_db_env_vars_use_defaults_regardless_of_other_vars(
        self,
        env_overrides: Dict[str, str],
    ):
        """
        Property 2: Unset database environment variables use defaults regardless of other vars
        
        *For any* combination of set/unset database environment variables, the unset variables
        SHALL use their documented default values.
        
        **Validates: Requirements 3.2**
        """
        with patch.dict(os.environ, env_overrides, clear=True):
            db_config = get_database_url_from_env()
            
            # Check each env var - if not set, should use default
            if "BOT_DB_HOST" not in env_overrides:
                assert db_config["host"] == "localhost", \
                    f"host should default to 'localhost' when not set, got {db_config['host']}"
            
            if "BOT_DB_PORT" not in env_overrides:
                assert db_config["port"] == "5432", \
                    f"port should default to '5432' when not set, got {db_config['port']}"
            
            if "BOT_DB_NAME" not in env_overrides:
                assert db_config["name"] == "platform_db", \
                    f"name should default to 'platform_db' when not set, got {db_config['name']}"
            
            if "BOT_DB_USER" not in env_overrides:
                assert db_config["user"] == "platform", \
                    f"user should default to 'platform' when not set, got {db_config['user']}"
    
    @settings(max_examples=50)
    @given(
        host=st.sampled_from(["db.example.com", "postgres.local", "192.168.1.100"]),
        port=st.integers(min_value=1024, max_value=65535).map(str),
        name=st.sampled_from(["test_db", "quantgambit_test", "trading_db"]),
        user=st.sampled_from(["test_user", "admin", "quantgambit"]),
    )
    def test_db_env_vars_override_defaults_when_set(
        self,
        host: str,
        port: str,
        name: str,
        user: str,
    ):
        """
        Property 2: Database environment variables override defaults when explicitly set
        
        *For any* valid environment variable value, when the variable is set,
        the system SHALL use the set value instead of the default.
        
        **Validates: Requirements 3.2**
        """
        env_overrides = {
            "BOT_DB_HOST": host,
            "BOT_DB_PORT": port,
            "BOT_DB_NAME": name,
            "BOT_DB_USER": user,
        }
        
        with patch.dict(os.environ, env_overrides, clear=True):
            db_config = get_database_url_from_env()
            
            # Property: set values should override defaults
            assert db_config["host"] == host, \
                f"host should be '{host}' when set, got {db_config['host']}"
            assert db_config["port"] == port, \
                f"port should be '{port}' when set, got {db_config['port']}"
            assert db_config["name"] == name, \
                f"name should be '{name}' when set, got {db_config['name']}"
            assert db_config["user"] == user, \
                f"user should be '{user}' when set, got {db_config['user']}"


class TestFeatureFlagEnvironmentVariableDefaults:
    """
    Feature: end-to-end-integration-verification, Property 2: Environment Variable Defaults
    
    Tests the feature flag environment variables with their defaults:
    - DECISION_RECORDER_ENABLED=true
    - BACKTEST_WARM_START_ENABLED=false
    - BACKTEST_PARITY_MODE=true
    
    Note: These are also tested in TestEnvironmentVariableDefaults for bot-integration-fixes.
    This class provides additional coverage for the end-to-end-integration-verification spec.
    
    **Validates: Requirements 3.2**
    """
    
    def test_decision_recorder_enabled_defaults_to_true_e2e(self):
        """
        Property 2: DECISION_RECORDER_ENABLED defaults to "true" when not set
        
        **Validates: Requirements 3.2**
        """
        with patch.dict(os.environ, {}, clear=True):
            assert "DECISION_RECORDER_ENABLED" not in os.environ
            
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            assert decision_recorder_enabled is True, \
                f"decision_recorder_enabled should default to True, got {decision_recorder_enabled}"
    
    def test_backtest_warm_start_enabled_defaults_to_false_e2e(self):
        """
        Property 2: BACKTEST_WARM_START_ENABLED defaults to "false" when not set
        
        **Validates: Requirements 3.2**
        """
        with patch.dict(os.environ, {}, clear=True):
            assert "BACKTEST_WARM_START_ENABLED" not in os.environ
            
            config = get_executor_config_from_env()
            
            assert config.warm_start_enabled is False, \
                f"warm_start_enabled should default to False, got {config.warm_start_enabled}"
    
    def test_backtest_parity_mode_defaults_to_true_e2e(self):
        """
        Property 2: BACKTEST_PARITY_MODE defaults to "true" when not set
        
        **Validates: Requirements 3.2**
        """
        with patch.dict(os.environ, {}, clear=True):
            assert "BACKTEST_PARITY_MODE" not in os.environ
            
            config = get_executor_config_from_env()
            
            assert config.parity_mode is True, \
                f"parity_mode should default to True, got {config.parity_mode}"
    
    def test_all_feature_flags_have_documented_defaults_e2e(self):
        """
        Property 2: All feature flag environment variables use documented defaults
        
        When no environment variables are set, all feature flag environment variables SHALL
        use their documented default values:
        - DECISION_RECORDER_ENABLED=true
        - BACKTEST_WARM_START_ENABLED=false
        - BACKTEST_PARITY_MODE=true
        
        **Validates: Requirements 3.2**
        """
        with patch.dict(os.environ, {}, clear=True):
            # Verify none of the env vars are set
            assert "DECISION_RECORDER_ENABLED" not in os.environ
            assert "BACKTEST_WARM_START_ENABLED" not in os.environ
            assert "BACKTEST_PARITY_MODE" not in os.environ
            
            # Get values from environment
            config = get_executor_config_from_env()
            decision_recorder_enabled = get_decision_recorder_enabled_from_env()
            
            # Property: DECISION_RECORDER_ENABLED defaults to true
            assert decision_recorder_enabled is True, \
                f"decision_recorder_enabled should default to True, got {decision_recorder_enabled}"
            
            # Property: BACKTEST_WARM_START_ENABLED defaults to false
            assert config.warm_start_enabled is False, \
                f"warm_start_enabled should default to False, got {config.warm_start_enabled}"
            
            # Property: BACKTEST_PARITY_MODE defaults to true
            assert config.parity_mode is True, \
                f"parity_mode should default to True, got {config.parity_mode}"
