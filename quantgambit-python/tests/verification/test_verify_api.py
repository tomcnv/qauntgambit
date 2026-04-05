"""
Unit tests for API verification script.

Tests the verify_api.py script functions for health check parsing,
CORS header validation, and JSON response validation.

Requirements: 1.1, 1.2, 1.3
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

import sys
import os

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from verify_api import (
    VerificationResult,
    verify_api_health,
    verify_api_cors,
    verify_backtest_endpoint,
    REQUIRED_CORS_HEADERS,
)


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""
    
    def test_create_passing_result(self):
        """Test creating a passing verification result."""
        result = VerificationResult(
            name="Test Check",
            passed=True,
            message="Check passed successfully",
            details={"key": "value"},
            error=None
        )
        
        assert result.name == "Test Check"
        assert result.passed is True
        assert result.message == "Check passed successfully"
        assert result.details == {"key": "value"}
        assert result.error is None
    
    def test_create_failing_result(self):
        """Test creating a failing verification result."""
        result = VerificationResult(
            name="Test Check",
            passed=False,
            message="Check failed",
            details={"url": "http://localhost:3002"},
            error="Connection refused"
        )
        
        assert result.name == "Test Check"
        assert result.passed is False
        assert result.message == "Check failed"
        assert result.error == "Connection refused"
    
    def test_result_with_no_optional_fields(self):
        """Test creating a result without optional fields."""
        result = VerificationResult(
            name="Simple Check",
            passed=True,
            message="OK"
        )
        
        assert result.name == "Simple Check"
        assert result.passed is True
        assert result.message == "OK"
        assert result.details is None
        assert result.error is None


@pytest.mark.asyncio
class TestVerifyApiHealth:
    """Tests for verify_api_health function."""
    
    async def test_health_check_success(self):
        """Test successful health check with valid response.
        
        **Validates: Requirements 1.1**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "healthy",
            "service": "quantgambit-api",
            "version": "1.0.0",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is True
        assert result.name == "API Health Check"
        assert "200" in result.message or "valid JSON" in result.message
        assert result.details is not None
        assert result.details["response"]["status"] == "healthy"
    
    async def test_health_check_non_200_status(self):
        """Test health check with non-200 status code.
        
        **Validates: Requirements 1.1**
        """
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is False
        assert "500" in result.message
        assert result.details["status_code"] == 500
    
    async def test_health_check_invalid_json(self):
        """Test health check with invalid JSON response.
        
        **Validates: Requirements 1.1**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Not valid JSON"
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is False
        assert "valid JSON" in result.message
        assert result.error is not None
    
    async def test_health_check_missing_status_field(self):
        """Test health check with missing 'status' field in response.
        
        **Validates: Requirements 1.1**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "service": "quantgambit-api",
            "version": "1.0.0"
            # Missing "status" field
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is False
        assert "missing" in result.message.lower()
        assert "status" in str(result.details.get("missing_fields", []))
    
    async def test_health_check_unhealthy_status(self):
        """Test health check with unhealthy status value.
        
        **Validates: Requirements 1.1**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "unhealthy",
            "service": "quantgambit-api"
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is False
        assert "unhealthy" in result.message
    
    async def test_health_check_connection_error(self):
        """Test health check when server is not running.
        
        **Validates: Requirements 1.1, 1.4**
        """
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is False
        assert "Could not connect" in result.message
        assert result.error is not None
    
    async def test_health_check_timeout(self):
        """Test health check when request times out.
        
        **Validates: Requirements 1.1**
        """
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://localhost:3002")
        
        assert result.passed is False
        assert "timed out" in result.message
        assert result.error is not None
    
    async def test_health_check_custom_base_url(self):
        """Test health check with custom base URL.
        
        **Validates: Requirements 1.1**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_health("http://custom-host:8080")
        
        assert result.passed is True
        assert "http://custom-host:8080/health" in result.details["url"]


@pytest.mark.asyncio
class TestVerifyApiCors:
    """Tests for verify_api_cors function.
    
    **Validates: Requirements 1.2**
    """
    
    async def test_cors_check_success_all_headers_present(self):
        """Test successful CORS check with all required headers present.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is True
        assert result.name == "API CORS Configuration"
        assert "correctly configured" in result.message
        assert result.details is not None
        assert "cors_headers" in result.details
        # Verify all required headers are in the found headers
        for header in REQUIRED_CORS_HEADERS:
            assert header in result.details["cors_headers"]
    
    async def test_cors_check_missing_allow_origin(self):
        """Test CORS check fails when Access-Control-Allow-Origin is missing.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            # Missing Access-Control-Allow-Origin
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is False
        assert "Missing required CORS headers" in result.message
        assert "access-control-allow-origin" in result.details["missing_headers"]
    
    async def test_cors_check_missing_allow_methods(self):
        """Test CORS check fails when Access-Control-Allow-Methods is missing.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Access-Control-Allow-Origin": "*",
            # Missing Access-Control-Allow-Methods
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is False
        assert "Missing required CORS headers" in result.message
        assert "access-control-allow-methods" in result.details["missing_headers"]
    
    async def test_cors_check_missing_allow_headers(self):
        """Test CORS check fails when Access-Control-Allow-Headers is missing.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            # Missing Access-Control-Allow-Headers
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is False
        assert "Missing required CORS headers" in result.message
        assert "access-control-allow-headers" in result.details["missing_headers"]
    
    async def test_cors_check_missing_all_headers(self):
        """Test CORS check fails when all CORS headers are missing.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "application/json",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is False
        assert "Missing required CORS headers" in result.message
        assert len(result.details["missing_headers"]) == 3
    
    async def test_cors_check_connection_error(self):
        """Test CORS check when server is not running.
        
        **Validates: Requirements 1.2, 1.4**
        """
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is False
        assert "Could not connect" in result.message
        assert result.error is not None
    
    async def test_cors_check_timeout(self):
        """Test CORS check when request times out.
        
        **Validates: Requirements 1.2**
        """
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.side_effect = httpx.TimeoutException("Request timed out")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is False
        assert "timed out" in result.message
        assert result.error is not None
    
    async def test_cors_check_custom_base_url(self):
        """Test CORS check with custom base URL.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://custom-host:8080")
        
        assert result.passed is True
        assert "http://custom-host:8080/health" in result.details["url"]
    
    async def test_cors_check_case_insensitive_headers(self):
        """Test CORS check handles case-insensitive header names.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Headers with different casing
        mock_response.headers = {
            "access-control-allow-origin": "*",
            "ACCESS-CONTROL-ALLOW-METHODS": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_api_cors("http://localhost:3002")
        
        assert result.passed is True
        assert "correctly configured" in result.message
    
    async def test_cors_sends_correct_preflight_headers(self):
        """Test that CORS check sends correct preflight request headers.
        
        **Validates: Requirements 1.2**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.options.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            await verify_api_cors("http://localhost:3002")
            
            # Verify OPTIONS was called with correct headers
            mock_client.options.assert_called_once()
            call_args = mock_client.options.call_args
            assert call_args[0][0] == "http://localhost:3002/health"
            headers = call_args[1]["headers"]
            assert headers["Origin"] == "http://localhost:3000"
            assert headers["Access-Control-Request-Method"] == "GET"
            assert headers["Access-Control-Request-Headers"] == "Content-Type"


@pytest.mark.asyncio
class TestVerifyBacktestEndpoint:
    """Tests for verify_backtest_endpoint function.
    
    **Validates: Requirements 1.3**
    """
    
    async def test_backtest_endpoint_success_empty_list(self):
        """Test successful backtest endpoint with empty list response.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is True
        assert result.name == "Backtest Endpoint"
        assert "valid JSON list" in result.message
        assert result.details["backtest_count"] == 0
    
    async def test_backtest_endpoint_success_with_data(self):
        """Test successful backtest endpoint with backtest data.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "bt-001", "status": "completed", "strategy": "momentum"},
            {"id": "bt-002", "status": "running", "strategy": "mean_reversion"},
            {"id": "bt-003", "status": "pending", "strategy": "pairs_trading"},
        ]
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is True
        assert "valid JSON list" in result.message
        assert result.details["backtest_count"] == 3
    
    async def test_backtest_endpoint_non_200_status(self):
        """Test backtest endpoint with non-200 status code.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "500" in result.message
        assert result.details["status_code"] == 500
    
    async def test_backtest_endpoint_404_not_found(self):
        """Test backtest endpoint with 404 status code.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "404" in result.message
        assert result.details["status_code"] == 404
    
    async def test_backtest_endpoint_invalid_json(self):
        """Test backtest endpoint with invalid JSON response.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Not valid JSON content"
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "valid JSON" in result.message
        assert result.error is not None
    
    async def test_backtest_endpoint_returns_object_not_list(self):
        """Test backtest endpoint returns object instead of list.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"backtests": [], "total": 0}
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "dict" in result.message
        assert "expected list" in result.message
        assert result.details["response_type"] == "dict"
    
    async def test_backtest_endpoint_returns_string_not_list(self):
        """Test backtest endpoint returns string instead of list.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = "No backtests found"
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "str" in result.message
        assert "expected list" in result.message
    
    async def test_backtest_endpoint_connection_error(self):
        """Test backtest endpoint when server is not running.
        
        **Validates: Requirements 1.3, 1.4**
        """
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "Could not connect" in result.message
        assert result.error is not None
    
    async def test_backtest_endpoint_timeout(self):
        """Test backtest endpoint when request times out.
        
        **Validates: Requirements 1.3**
        """
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("Request timed out")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://localhost:3002")
        
        assert result.passed is False
        assert "timed out" in result.message
        assert result.error is not None
    
    async def test_backtest_endpoint_custom_base_url(self):
        """Test backtest endpoint with custom base URL.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            result = await verify_backtest_endpoint("http://custom-host:8080")
        
        assert result.passed is True
        assert "http://custom-host:8080/api/research/backtests" in result.details["url"]
    
    async def test_backtest_endpoint_calls_correct_url(self):
        """Test that backtest endpoint calls the correct URL.
        
        **Validates: Requirements 1.3**
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client
            
            await verify_backtest_endpoint("http://localhost:3002")
            
            # Verify GET was called with correct URL
            mock_client.get.assert_called_once_with("http://localhost:3002/api/research/backtests")
