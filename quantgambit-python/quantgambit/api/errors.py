"""Comprehensive error handling for the Backtesting API.

Feature: backtesting-api-integration
Requirements: All

This module provides:
- Consistent error response format
- Custom exception classes for different error types
- Error handlers for FastAPI
- Utility functions for error responses
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ============================================================================
# Error Response Models
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response format.
    
    All API errors follow this consistent format for easy client handling.
    """
    error: str  # Error type/code
    message: str  # Human-readable message
    details: Optional[Dict[str, Any]] = None  # Additional context


class ValidationErrorDetail(BaseModel):
    """Detail for validation errors."""
    field: str
    message: str


# ============================================================================
# Custom Exception Classes
# ============================================================================

class APIError(HTTPException):
    """Base class for API errors with consistent response format."""
    
    def __init__(
        self,
        status_code: int,
        error: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.error = error
        self.message = message
        self.details = details
        super().__init__(
            status_code=status_code,
            detail={
                "error": error,
                "message": message,
                "details": details,
            }
        )


class ValidationError(APIError):
    """400 Bad Request - Validation errors."""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=400,
            error="validation_error",
            message=message,
            details=details,
        )


class InvalidDateFormatError(ValidationError):
    """400 Bad Request - Invalid date format."""
    
    def __init__(self, field_name: str, value: str):
        super().__init__(
            message=f"Invalid {field_name} format. Use YYYY-MM-DD or ISO format.",
            details={"field": field_name, "value": value},
        )


class InvalidDateRangeError(ValidationError):
    """400 Bad Request - Invalid date range."""
    
    def __init__(self, start_date: str, end_date: str):
        super().__init__(
            message="start_date must be before end_date",
            details={"start_date": start_date, "end_date": end_date},
        )


class MissingFieldError(ValidationError):
    """400 Bad Request - Required field missing."""
    
    def __init__(self, field_name: str):
        super().__init__(
            message=f"{field_name} is required",
            details={"field": field_name},
        )


class InvalidFieldValueError(ValidationError):
    """400 Bad Request - Invalid field value."""
    
    def __init__(self, field_name: str, message: str, value: Any = None):
        details = {"field": field_name}
        if value is not None:
            details["value"] = value
        super().__init__(
            message=message,
            details=details,
        )


class InvalidFormatError(ValidationError):
    """400 Bad Request - Invalid format parameter."""
    
    def __init__(self, format_value: str, allowed_formats: list[str]):
        super().__init__(
            message=f"Format must be one of: {', '.join(allowed_formats)}",
            details={"format": format_value, "allowed": allowed_formats},
        )


class AuthenticationError(APIError):
    """401 Unauthorized - Authentication errors."""
    
    def __init__(
        self,
        message: str = "Authentication required",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=401,
            error="authentication_error",
            message=message,
            details=details,
        )


class MissingTokenError(AuthenticationError):
    """401 Unauthorized - Missing bearer token."""
    
    def __init__(self):
        super().__init__(
            message="Missing or invalid authorization header. Bearer token required.",
            details={"expected": "Authorization: Bearer <token>"},
        )


class InvalidTokenError(AuthenticationError):
    """401 Unauthorized - Invalid token."""
    
    def __init__(self, reason: str = "invalid_token"):
        super().__init__(
            message="Invalid or expired authentication token",
            details={"reason": reason},
        )


class AuthorizationError(APIError):
    """403 Forbidden - Authorization errors."""
    
    def __init__(
        self,
        message: str = "Access denied",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=403,
            error="authorization_error",
            message=message,
            details=details,
        )


class TenantAccessDeniedError(AuthorizationError):
    """403 Forbidden - Cross-tenant access denied."""
    
    def __init__(self, resource_type: str = "resource"):
        super().__init__(
            message=f"Access denied: {resource_type} belongs to a different tenant",
            details={"resource_type": resource_type},
        )


class NotFoundError(APIError):
    """404 Not Found - Resource not found."""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: str,
    ):
        super().__init__(
            status_code=404,
            error="not_found",
            message=f"{resource_type} not found",
            details={"resource_type": resource_type, "resource_id": resource_id},
        )


class BacktestNotFoundError(NotFoundError):
    """404 Not Found - Backtest run not found."""
    
    def __init__(self, run_id: str):
        super().__init__(
            resource_type="Backtest run",
            resource_id=run_id,
        )


class WFORunNotFoundError(NotFoundError):
    """404 Not Found - WFO run not found."""
    
    def __init__(self, run_id: str):
        super().__init__(
            resource_type="WFO run",
            resource_id=run_id,
        )


class StrategyNotFoundError(NotFoundError):
    """404 Not Found - Strategy not found."""
    
    def __init__(self, strategy_id: str):
        super().__init__(
            resource_type="Strategy",
            resource_id=strategy_id,
        )


class DatasetNotFoundError(NotFoundError):
    """404 Not Found - Dataset not found."""
    
    def __init__(self, symbol: str):
        super().__init__(
            resource_type="Dataset",
            resource_id=symbol,
        )


class ConflictError(APIError):
    """409 Conflict - Resource conflict."""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=409,
            error="conflict",
            message=message,
            details=details,
        )


class InvalidStatusTransitionError(ConflictError):
    """409 Conflict - Invalid status transition."""
    
    def __init__(self, current_status: str, action: str):
        super().__init__(
            message=f"Cannot {action} backtest with status '{current_status}'",
            details={"current_status": current_status, "action": action},
        )


class DuplicateResourceError(ConflictError):
    """409 Conflict - Duplicate resource."""
    
    def __init__(self, resource_type: str, identifier: str):
        super().__init__(
            message=f"{resource_type} already exists",
            details={"resource_type": resource_type, "identifier": identifier},
        )


class ServerError(APIError):
    """500 Internal Server Error - Server errors."""
    
    def __init__(
        self,
        message: str = "An internal server error occurred",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=500,
            error="server_error",
            message=message,
            details=details,
        )


class DatabaseError(ServerError):
    """500 Internal Server Error - Database errors."""
    
    def __init__(self, operation: str = "database operation"):
        super().__init__(
            message=f"Database error during {operation}",
            details={"operation": operation},
        )


class RedisError(ServerError):
    """500 Internal Server Error - Redis errors."""
    
    def __init__(self, operation: str = "Redis operation"):
        super().__init__(
            message=f"Redis error during {operation}",
            details={"operation": operation},
        )


class ExecutionError(ServerError):
    """500 Internal Server Error - Execution errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            details=details,
        )


# ============================================================================
# Error Handler Functions
# ============================================================================

async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError exceptions with consistent response format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error,
            "message": exc.message,
            "details": exc.details,
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle standard HTTPException with consistent response format."""
    # If detail is already a dict with our format, use it
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
        )
    
    # Otherwise, wrap it in our format
    error_type = _status_code_to_error_type(exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_type,
            "message": str(exc.detail) if exc.detail else _status_code_to_message(exc.status_code),
            "details": None,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with consistent response format."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "server_error",
            "message": "An unexpected error occurred",
            "details": None,
        },
    )


def _status_code_to_error_type(status_code: int) -> str:
    """Map HTTP status code to error type."""
    mapping = {
        400: "validation_error",
        401: "authentication_error",
        403: "authorization_error",
        404: "not_found",
        409: "conflict",
        500: "server_error",
    }
    return mapping.get(status_code, "error")


def _status_code_to_message(status_code: int) -> str:
    """Map HTTP status code to default message."""
    mapping = {
        400: "Bad request",
        401: "Authentication required",
        403: "Access denied",
        404: "Resource not found",
        409: "Resource conflict",
        500: "Internal server error",
    }
    return mapping.get(status_code, "An error occurred")


# ============================================================================
# Utility Functions
# ============================================================================

def create_error_response(
    status_code: int,
    error: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """Create a consistent error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "message": message,
            "details": details,
        },
    )


def validate_required_field(value: Any, field_name: str) -> None:
    """Validate that a required field is present and non-empty."""
    if value is None:
        raise MissingFieldError(field_name)
    if isinstance(value, str) and not value.strip():
        raise MissingFieldError(field_name)


def validate_positive_number(value: float, field_name: str) -> None:
    """Validate that a number is positive."""
    if value <= 0:
        raise InvalidFieldValueError(
            field_name=field_name,
            message=f"{field_name} must be positive",
            value=value,
        )


def validate_non_negative_number(value: float, field_name: str) -> None:
    """Validate that a number is non-negative."""
    if value < 0:
        raise InvalidFieldValueError(
            field_name=field_name,
            message=f"{field_name} must be non-negative",
            value=value,
        )


def validate_enum_value(value: str, field_name: str, allowed_values: list[str]) -> None:
    """Validate that a value is one of the allowed values."""
    if value not in allowed_values:
        raise InvalidFieldValueError(
            field_name=field_name,
            message=f"{field_name} must be one of: {', '.join(allowed_values)}",
            value=value,
        )
