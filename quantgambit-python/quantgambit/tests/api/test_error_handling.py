"""Unit tests for API error handling.

Feature: backtesting-api-integration
Requirements: All

Tests:
- Validation errors (400)
- Not found scenarios (404)
- Conflict errors (409)
- Error response format consistency
"""

import pytest
from fastapi import HTTPException

from quantgambit.api.errors import (
    APIError,
    ValidationError,
    InvalidDateFormatError,
    InvalidDateRangeError,
    MissingFieldError,
    InvalidFieldValueError,
    InvalidFormatError,
    AuthenticationError,
    MissingTokenError,
    InvalidTokenError,
    AuthorizationError,
    TenantAccessDeniedError,
    NotFoundError,
    BacktestNotFoundError,
    WFORunNotFoundError,
    StrategyNotFoundError,
    DatasetNotFoundError,
    ConflictError,
    InvalidStatusTransitionError,
    DuplicateResourceError,
    ServerError,
    DatabaseError,
    RedisError,
    ExecutionError,
    validate_required_field,
    validate_positive_number,
    validate_non_negative_number,
    validate_enum_value,
)


class TestValidationErrors:
    """Tests for validation error classes (400 Bad Request)."""
    
    def test_validation_error_basic(self):
        """Test basic ValidationError."""
        error = ValidationError("Invalid input")
        assert error.status_code == 400
        assert error.error == "validation_error"
        assert error.message == "Invalid input"
        assert error.details is None
    
    def test_validation_error_with_details(self):
        """Test ValidationError with details."""
        error = ValidationError("Invalid input", {"field": "name"})
        assert error.status_code == 400
        assert error.details == {"field": "name"}
    
    def test_invalid_date_format_error(self):
        """Test InvalidDateFormatError."""
        error = InvalidDateFormatError("start_date", "not-a-date")
        assert error.status_code == 400
        assert error.error == "validation_error"
        assert "start_date" in error.message
        assert error.details["field"] == "start_date"
        assert error.details["value"] == "not-a-date"
    
    def test_invalid_date_range_error(self):
        """Test InvalidDateRangeError."""
        error = InvalidDateRangeError("2024-01-10", "2024-01-01")
        assert error.status_code == 400
        assert "start_date must be before end_date" in error.message
        assert error.details["start_date"] == "2024-01-10"
        assert error.details["end_date"] == "2024-01-01"
    
    def test_missing_field_error(self):
        """Test MissingFieldError."""
        error = MissingFieldError("strategy_id")
        assert error.status_code == 400
        assert "strategy_id is required" in error.message
        assert error.details["field"] == "strategy_id"
    
    def test_invalid_field_value_error(self):
        """Test InvalidFieldValueError."""
        error = InvalidFieldValueError("initial_capital", "must be positive", -100)
        assert error.status_code == 400
        assert "must be positive" in error.message
        assert error.details["field"] == "initial_capital"
        assert error.details["value"] == -100
    
    def test_invalid_format_error(self):
        """Test InvalidFormatError."""
        error = InvalidFormatError("xml", ["json", "csv"])
        assert error.status_code == 400
        assert "json" in error.message
        assert "csv" in error.message
        assert error.details["format"] == "xml"
        assert error.details["allowed"] == ["json", "csv"]


class TestAuthenticationErrors:
    """Tests for authentication error classes (401 Unauthorized)."""
    
    def test_authentication_error_basic(self):
        """Test basic AuthenticationError."""
        error = AuthenticationError()
        assert error.status_code == 401
        assert error.error == "authentication_error"
        assert "Authentication required" in error.message
    
    def test_missing_token_error(self):
        """Test MissingTokenError."""
        error = MissingTokenError()
        assert error.status_code == 401
        assert "Bearer token required" in error.message
        assert "Authorization" in str(error.details)
    
    def test_invalid_token_error(self):
        """Test InvalidTokenError."""
        error = InvalidTokenError("expired")
        assert error.status_code == 401
        assert "Invalid or expired" in error.message
        assert error.details["reason"] == "expired"


class TestAuthorizationErrors:
    """Tests for authorization error classes (403 Forbidden)."""
    
    def test_authorization_error_basic(self):
        """Test basic AuthorizationError."""
        error = AuthorizationError()
        assert error.status_code == 403
        assert error.error == "authorization_error"
        assert "Access denied" in error.message
    
    def test_tenant_access_denied_error(self):
        """Test TenantAccessDeniedError."""
        error = TenantAccessDeniedError("backtest")
        assert error.status_code == 403
        assert "different tenant" in error.message
        assert error.details["resource_type"] == "backtest"


class TestNotFoundErrors:
    """Tests for not found error classes (404 Not Found)."""
    
    def test_not_found_error_basic(self):
        """Test basic NotFoundError."""
        error = NotFoundError("Resource", "123")
        assert error.status_code == 404
        assert error.error == "not_found"
        assert "Resource not found" in error.message
        assert error.details["resource_type"] == "Resource"
        assert error.details["resource_id"] == "123"
    
    def test_backtest_not_found_error(self):
        """Test BacktestNotFoundError."""
        error = BacktestNotFoundError("run-123")
        assert error.status_code == 404
        assert "Backtest run not found" in error.message
        assert error.details["resource_id"] == "run-123"
    
    def test_wfo_run_not_found_error(self):
        """Test WFORunNotFoundError."""
        error = WFORunNotFoundError("wfo-456")
        assert error.status_code == 404
        assert "WFO run not found" in error.message
        assert error.details["resource_id"] == "wfo-456"
    
    def test_strategy_not_found_error(self):
        """Test StrategyNotFoundError."""
        error = StrategyNotFoundError("unknown_strategy")
        assert error.status_code == 404
        assert "Strategy not found" in error.message
    
    def test_dataset_not_found_error(self):
        """Test DatasetNotFoundError."""
        error = DatasetNotFoundError("BTC-USDT")
        assert error.status_code == 404
        assert "Dataset not found" in error.message


class TestConflictErrors:
    """Tests for conflict error classes (409 Conflict)."""
    
    def test_conflict_error_basic(self):
        """Test basic ConflictError."""
        error = ConflictError("Resource already exists")
        assert error.status_code == 409
        assert error.error == "conflict"
        assert "Resource already exists" in error.message
    
    def test_invalid_status_transition_error(self):
        """Test InvalidStatusTransitionError."""
        error = InvalidStatusTransitionError("completed", "cancel")
        assert error.status_code == 409
        assert "Cannot cancel" in error.message
        assert "completed" in error.message
        assert error.details["current_status"] == "completed"
        assert error.details["action"] == "cancel"
    
    def test_duplicate_resource_error(self):
        """Test DuplicateResourceError."""
        error = DuplicateResourceError("Backtest", "test-run")
        assert error.status_code == 409
        assert "already exists" in error.message
        assert error.details["resource_type"] == "Backtest"


class TestServerErrors:
    """Tests for server error classes (500 Internal Server Error)."""
    
    def test_server_error_basic(self):
        """Test basic ServerError."""
        error = ServerError()
        assert error.status_code == 500
        assert error.error == "server_error"
        assert "internal server error" in error.message.lower()
    
    def test_database_error(self):
        """Test DatabaseError."""
        error = DatabaseError("creating backtest")
        assert error.status_code == 500
        assert "Database error" in error.message
        assert error.details["operation"] == "creating backtest"
    
    def test_redis_error(self):
        """Test RedisError."""
        error = RedisError("scanning datasets")
        assert error.status_code == 500
        assert "Redis error" in error.message
        assert error.details["operation"] == "scanning datasets"
    
    def test_execution_error(self):
        """Test ExecutionError."""
        error = ExecutionError("Backtest execution failed", {"run_id": "123"})
        assert error.status_code == 500
        assert "Backtest execution failed" in error.message
        assert error.details["run_id"] == "123"


class TestValidationUtilities:
    """Tests for validation utility functions."""
    
    def test_validate_required_field_valid(self):
        """Test validate_required_field with valid input."""
        # Should not raise
        validate_required_field("value", "field_name")
        validate_required_field(123, "field_name")
        validate_required_field(["item"], "field_name")
    
    def test_validate_required_field_none(self):
        """Test validate_required_field with None."""
        with pytest.raises(MissingFieldError) as exc_info:
            validate_required_field(None, "field_name")
        assert exc_info.value.status_code == 400
        assert "field_name is required" in exc_info.value.message
    
    def test_validate_required_field_empty_string(self):
        """Test validate_required_field with empty string."""
        with pytest.raises(MissingFieldError) as exc_info:
            validate_required_field("", "field_name")
        assert exc_info.value.status_code == 400
    
    def test_validate_required_field_whitespace(self):
        """Test validate_required_field with whitespace string."""
        with pytest.raises(MissingFieldError) as exc_info:
            validate_required_field("   ", "field_name")
        assert exc_info.value.status_code == 400
    
    def test_validate_positive_number_valid(self):
        """Test validate_positive_number with valid input."""
        # Should not raise
        validate_positive_number(1, "field_name")
        validate_positive_number(0.001, "field_name")
        validate_positive_number(1000000, "field_name")
    
    def test_validate_positive_number_zero(self):
        """Test validate_positive_number with zero."""
        with pytest.raises(InvalidFieldValueError) as exc_info:
            validate_positive_number(0, "field_name")
        assert exc_info.value.status_code == 400
        assert "must be positive" in exc_info.value.message
    
    def test_validate_positive_number_negative(self):
        """Test validate_positive_number with negative."""
        with pytest.raises(InvalidFieldValueError) as exc_info:
            validate_positive_number(-5, "field_name")
        assert exc_info.value.status_code == 400
    
    def test_validate_non_negative_number_valid(self):
        """Test validate_non_negative_number with valid input."""
        # Should not raise
        validate_non_negative_number(0, "field_name")
        validate_non_negative_number(1, "field_name")
        validate_non_negative_number(0.0, "field_name")
    
    def test_validate_non_negative_number_negative(self):
        """Test validate_non_negative_number with negative."""
        with pytest.raises(InvalidFieldValueError) as exc_info:
            validate_non_negative_number(-1, "field_name")
        assert exc_info.value.status_code == 400
        assert "must be non-negative" in exc_info.value.message
    
    def test_validate_enum_value_valid(self):
        """Test validate_enum_value with valid input."""
        # Should not raise
        validate_enum_value("json", "format", ["json", "csv"])
        validate_enum_value("csv", "format", ["json", "csv"])
    
    def test_validate_enum_value_invalid(self):
        """Test validate_enum_value with invalid input."""
        with pytest.raises(InvalidFieldValueError) as exc_info:
            validate_enum_value("xml", "format", ["json", "csv"])
        assert exc_info.value.status_code == 400
        assert "must be one of" in exc_info.value.message
        assert "json" in exc_info.value.message
        assert "csv" in exc_info.value.message


class TestErrorResponseFormat:
    """Tests for consistent error response format."""
    
    def test_api_error_detail_format(self):
        """Test that APIError detail follows consistent format."""
        error = APIError(400, "test_error", "Test message", {"key": "value"})
        detail = error.detail
        
        assert isinstance(detail, dict)
        assert "error" in detail
        assert "message" in detail
        assert "details" in detail
        assert detail["error"] == "test_error"
        assert detail["message"] == "Test message"
        assert detail["details"] == {"key": "value"}
    
    def test_all_error_types_have_consistent_format(self):
        """Test that all error types produce consistent format."""
        errors = [
            ValidationError("test"),
            InvalidDateFormatError("field", "value"),
            MissingFieldError("field"),
            AuthenticationError(),
            MissingTokenError(),
            AuthorizationError(),
            NotFoundError("Resource", "123"),
            BacktestNotFoundError("123"),
            ConflictError("test"),
            InvalidStatusTransitionError("status", "action"),
            ServerError(),
            DatabaseError("operation"),
        ]
        
        for error in errors:
            detail = error.detail
            assert isinstance(detail, dict), f"{type(error).__name__} detail is not dict"
            assert "error" in detail, f"{type(error).__name__} missing 'error' key"
            assert "message" in detail, f"{type(error).__name__} missing 'message' key"
            assert "details" in detail, f"{type(error).__name__} missing 'details' key"
            assert isinstance(detail["error"], str), f"{type(error).__name__} error is not string"
            assert isinstance(detail["message"], str), f"{type(error).__name__} message is not string"
