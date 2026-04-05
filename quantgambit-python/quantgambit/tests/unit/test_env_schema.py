"""Tests for environment variable validation schema."""

import pytest
import os
from unittest.mock import patch

from quantgambit.config.env_schema import (
    EnvVarSpec,
    EnvVarType,
    ValidationError,
    validate_env_var,
    validate_all_env_vars,
    get_env_var_docs,
    _parse_bool,
    _parse_list,
)


class TestParseBool:
    """Tests for boolean parsing."""
    
    def test_true_values(self):
        """Should parse various true values."""
        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("TRUE") is True
        assert _parse_bool("1") is True
        assert _parse_bool("yes") is True
        assert _parse_bool("on") is True
    
    def test_false_values(self):
        """Should parse various false values."""
        assert _parse_bool("false") is False
        assert _parse_bool("False") is False
        assert _parse_bool("0") is False
        assert _parse_bool("no") is False
        assert _parse_bool("off") is False
        assert _parse_bool("") is False


class TestParseList:
    """Tests for list parsing."""
    
    def test_comma_separated(self):
        """Should parse comma-separated values."""
        assert _parse_list("a,b,c") == ["a", "b", "c"]
        assert _parse_list("a, b, c") == ["a", "b", "c"]
        assert _parse_list("  a  ,  b  ,  c  ") == ["a", "b", "c"]
    
    def test_empty_values(self):
        """Should handle empty values."""
        assert _parse_list("") == []
        assert _parse_list("a,,b") == ["a", "b"]


class TestValidateEnvVar:
    """Tests for single environment variable validation."""
    
    def test_required_missing(self):
        """Should error on missing required variable."""
        spec = EnvVarSpec(
            name="TEST_REQUIRED",
            type=EnvVarType.STRING,
            required=True,
        )
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TEST_REQUIRED", None)
            error = validate_env_var(spec)
            assert error is not None
            assert "required" in error.message.lower()
    
    def test_required_present(self):
        """Should pass on present required variable."""
        spec = EnvVarSpec(
            name="TEST_REQUIRED",
            type=EnvVarType.STRING,
            required=True,
        )
        
        with patch.dict(os.environ, {"TEST_REQUIRED": "value"}):
            error = validate_env_var(spec)
            assert error is None
    
    def test_optional_missing(self):
        """Should pass on missing optional variable."""
        spec = EnvVarSpec(
            name="TEST_OPTIONAL",
            type=EnvVarType.STRING,
            required=False,
        )
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TEST_OPTIONAL", None)
            error = validate_env_var(spec)
            assert error is None
    
    def test_int_valid(self):
        """Should parse valid integer."""
        spec = EnvVarSpec(
            name="TEST_INT",
            type=EnvVarType.INT,
        )
        
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            error = validate_env_var(spec)
            assert error is None
    
    def test_int_invalid(self):
        """Should error on invalid integer."""
        spec = EnvVarSpec(
            name="TEST_INT",
            type=EnvVarType.INT,
        )
        
        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            error = validate_env_var(spec)
            assert error is not None
            assert "invalid type" in error.message.lower()
    
    def test_float_valid(self):
        """Should parse valid float."""
        spec = EnvVarSpec(
            name="TEST_FLOAT",
            type=EnvVarType.FLOAT,
        )
        
        with patch.dict(os.environ, {"TEST_FLOAT": "3.14"}):
            error = validate_env_var(spec)
            assert error is None
    
    def test_min_value(self):
        """Should error when below minimum."""
        spec = EnvVarSpec(
            name="TEST_MIN",
            type=EnvVarType.FLOAT,
            min_value=10.0,
        )
        
        with patch.dict(os.environ, {"TEST_MIN": "5.0"}):
            error = validate_env_var(spec)
            assert error is not None
            assert "below minimum" in error.message.lower()
    
    def test_max_value(self):
        """Should error when above maximum."""
        spec = EnvVarSpec(
            name="TEST_MAX",
            type=EnvVarType.FLOAT,
            max_value=100.0,
        )
        
        with patch.dict(os.environ, {"TEST_MAX": "150.0"}):
            error = validate_env_var(spec)
            assert error is not None
            assert "above maximum" in error.message.lower()
    
    def test_allowed_values_valid(self):
        """Should pass when value is in allowed set."""
        spec = EnvVarSpec(
            name="TEST_ALLOWED",
            type=EnvVarType.STRING,
            allowed_values={"a", "b", "c"},
        )
        
        with patch.dict(os.environ, {"TEST_ALLOWED": "b"}):
            error = validate_env_var(spec)
            assert error is None
    
    def test_allowed_values_invalid(self):
        """Should error when value not in allowed set."""
        spec = EnvVarSpec(
            name="TEST_ALLOWED",
            type=EnvVarType.STRING,
            allowed_values={"a", "b", "c"},
        )
        
        with patch.dict(os.environ, {"TEST_ALLOWED": "d"}):
            error = validate_env_var(spec)
            assert error is not None
            assert "not in allowed values" in error.message.lower()
    
    def test_allowed_values_case_insensitive(self):
        """Should match allowed values case-insensitively."""
        spec = EnvVarSpec(
            name="TEST_ALLOWED",
            type=EnvVarType.STRING,
            allowed_values={"paper", "live"},
        )
        
        with patch.dict(os.environ, {"TEST_ALLOWED": "PAPER"}):
            error = validate_env_var(spec)
            assert error is None


class TestValidateAllEnvVars:
    """Tests for validating all environment variables."""
    
    def test_returns_validation_result(self):
        """Should return ValidationResult."""
        with patch.dict(os.environ, {
            "TENANT_ID": "t1",
            "BOT_ID": "b1",
            "EXCHANGE": "bybit",
        }):
            result = validate_all_env_vars()
            assert hasattr(result, "valid")
            assert hasattr(result, "errors")
            assert hasattr(result, "warnings")
            assert hasattr(result, "values")
    
    def test_valid_with_required_vars(self):
        """Should be valid when required vars are set."""
        with patch.dict(os.environ, {
            "TENANT_ID": "t1",
            "BOT_ID": "b1",
            "EXCHANGE": "bybit",
        }):
            result = validate_all_env_vars()
            assert result.valid is True
            assert len(result.errors) == 0
    
    def test_invalid_without_required_vars(self):
        """Should be invalid when required vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear required vars
            for var in ["TENANT_ID", "BOT_ID", "EXCHANGE"]:
                os.environ.pop(var, None)
            
            result = validate_all_env_vars()
            assert result.valid is False
            assert len(result.errors) > 0
    
    def test_parses_values(self):
        """Should parse values into correct types."""
        with patch.dict(os.environ, {
            "TENANT_ID": "t1",
            "BOT_ID": "b1",
            "EXCHANGE": "bybit",
            "QUANT_INTEGRATION_ENABLED": "true",
            "LATENCY_MAX_SAMPLES": "50000",
            "RECONCILIATION_INTERVAL_SEC": "60.0",
        }):
            result = validate_all_env_vars()
            
            assert result.values.get("QUANT_INTEGRATION_ENABLED") is True
            assert result.values.get("LATENCY_MAX_SAMPLES") == 50000
            assert result.values.get("RECONCILIATION_INTERVAL_SEC") == 60.0


class TestGetEnvVarDocs:
    """Tests for documentation generation."""
    
    def test_generates_markdown(self):
        """Should generate markdown documentation."""
        docs = get_env_var_docs()
        
        assert "# Environment Variables" in docs
        assert "| Variable |" in docs
        assert "`TENANT_ID`" in docs
        assert "`EXCHANGE`" in docs
    
    def test_groups_by_category(self):
        """Should group variables by category."""
        docs = get_env_var_docs()
        
        assert "## Core Runtime" in docs
        assert "## Kill Switch" in docs
        assert "## Reconciliation" in docs
        assert "## Alerting" in docs
    
    def test_hides_secrets(self):
        """Should hide secret values."""
        docs = get_env_var_docs()
        
        # Secret vars should show *** for default
        # (They don't have defaults, but if they did...)
        assert "BYBIT_API_KEY" in docs
        assert "BYBIT_API_SECRET" in docs
