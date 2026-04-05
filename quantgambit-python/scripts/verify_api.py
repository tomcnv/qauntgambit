#!/usr/bin/env python3
"""API verification script for the Bot API server.

This script verifies that the Bot API server is running and accessible,
with correct health check responses and CORS configuration.

Usage:
    python scripts/verify_api.py [--base-url URL]
"""

import argparse
import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


@dataclass
class VerificationResult:
    """Result of a verification check."""
    name: str
    passed: bool
    message: str
    details: Optional[dict[str, Any]] = None
    error: Optional[str] = None


# Required CORS headers for dashboard communication
REQUIRED_CORS_HEADERS = [
    "access-control-allow-origin",
    "access-control-allow-methods",
    "access-control-allow-headers",
]


async def verify_api_health(base_url: str = "http://localhost:3002") -> VerificationResult:
    """Verify the API health endpoint responds correctly.
    
    Args:
        base_url: Base URL of the Bot API
        
    Returns:
        VerificationResult with status and details
    """
    name = "API Health Check"
    endpoint = f"{base_url}/health"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint)
            
            # Check status code
            if response.status_code != 200:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Health endpoint returned status {response.status_code}, expected 200",
                    details={"status_code": response.status_code, "url": endpoint},
                    error=None
                )
            
            # Check response is valid JSON
            try:
                data = response.json()
            except Exception as e:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message="Health endpoint did not return valid JSON",
                    details={"url": endpoint, "response_text": response.text[:200]},
                    error=str(e)
                )
            
            # Check for expected fields in health response
            expected_fields = ["status"]
            missing_fields = [f for f in expected_fields if f not in data]
            
            if missing_fields:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Health response missing expected fields: {missing_fields}",
                    details={"url": endpoint, "response": data, "missing_fields": missing_fields},
                    error=None
                )
            
            # Check status value
            if data.get("status") != "healthy":
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Health status is '{data.get('status')}', expected 'healthy'",
                    details={"url": endpoint, "response": data},
                    error=None
                )
            
            return VerificationResult(
                name=name,
                passed=True,
                message="Health endpoint responded with 200 and valid JSON",
                details={"url": endpoint, "response": data},
                error=None
            )
            
    except httpx.ConnectError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Could not connect to Bot API at {endpoint}",
            details={"url": endpoint},
            error=str(e)
        )
    except httpx.TimeoutException as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Request to {endpoint} timed out",
            details={"url": endpoint},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Unexpected error verifying health endpoint",
            details={"url": endpoint},
            error=str(e)
        )


async def verify_backtest_endpoint(base_url: str = "http://localhost:3002") -> VerificationResult:
    """Verify the backtest list endpoint responds correctly.
    
    Sends a GET request to the backtests endpoint and verifies it returns
    a valid JSON response (expected to be a list/array of backtest runs).
    
    Args:
        base_url: Base URL of the Bot API
        
    Returns:
        VerificationResult with status and details
    """
    name = "Backtest Endpoint"
    endpoint = f"{base_url}/api/research/backtests"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint)
            
            # Check status code
            if response.status_code != 200:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Backtest endpoint returned status {response.status_code}, expected 200",
                    details={"status_code": response.status_code, "url": endpoint},
                    error=None
                )
            
            # Check response is valid JSON
            try:
                data = response.json()
            except Exception as e:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message="Backtest endpoint did not return valid JSON",
                    details={"url": endpoint, "response_text": response.text[:200]},
                    error=str(e)
                )
            
            # Verify response is a list (array of backtests)
            if not isinstance(data, list):
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Backtest endpoint returned {type(data).__name__}, expected list",
                    details={"url": endpoint, "response_type": type(data).__name__},
                    error=None
                )
            
            return VerificationResult(
                name=name,
                passed=True,
                message=f"Backtest endpoint returned valid JSON list with {len(data)} items",
                details={"url": endpoint, "backtest_count": len(data)},
                error=None
            )
            
    except httpx.ConnectError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Could not connect to Bot API at {endpoint}",
            details={"url": endpoint},
            error=str(e)
        )
    except httpx.TimeoutException as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Request to {endpoint} timed out",
            details={"url": endpoint},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Unexpected error verifying backtest endpoint",
            details={"url": endpoint},
            error=str(e)
        )


async def verify_api_cors(base_url: str = "http://localhost:3002") -> VerificationResult:
    """Verify CORS headers are correctly configured.
    
    Sends an OPTIONS preflight request to verify the API returns
    the required CORS headers for cross-origin requests from the dashboard.
    
    Args:
        base_url: Base URL of the Bot API
        
    Returns:
        VerificationResult with status and details
    """
    name = "API CORS Configuration"
    endpoint = f"{base_url}/health"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Send OPTIONS preflight request with Origin header
            response = await client.options(
                endpoint,
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Content-Type",
                }
            )
            
            # Get response headers (case-insensitive)
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            
            # Check for required CORS headers
            missing_headers = []
            found_headers = {}
            
            for header in REQUIRED_CORS_HEADERS:
                if header in response_headers:
                    found_headers[header] = response_headers[header]
                else:
                    missing_headers.append(header)
            
            if missing_headers:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Missing required CORS headers: {missing_headers}",
                    details={
                        "url": endpoint,
                        "missing_headers": missing_headers,
                        "found_headers": found_headers,
                        "status_code": response.status_code,
                    },
                    error=None
                )
            
            return VerificationResult(
                name=name,
                passed=True,
                message="CORS headers are correctly configured",
                details={
                    "url": endpoint,
                    "cors_headers": found_headers,
                    "status_code": response.status_code,
                },
                error=None
            )
            
    except httpx.ConnectError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Could not connect to Bot API at {endpoint}",
            details={"url": endpoint},
            error=str(e)
        )
    except httpx.TimeoutException as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Request to {endpoint} timed out",
            details={"url": endpoint},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Unexpected error verifying CORS configuration",
            details={"url": endpoint},
            error=str(e)
        )


def print_result(result: VerificationResult) -> None:
    """Print a verification result in a formatted way."""
    status = "✅ PASS" if result.passed else "❌ FAIL"
    print(f"\n{status}: {result.name}")
    print(f"  Message: {result.message}")
    if result.details:
        print(f"  Details: {result.details}")
    if result.error:
        print(f"  Error: {result.error}")


async def main() -> int:
    """Run all API verification checks."""
    parser = argparse.ArgumentParser(description="Verify Bot API server connectivity")
    parser.add_argument(
        "--base-url",
        default=os.getenv("BOT_API_URL", "http://localhost:3002"),
        help="Base URL of the Bot API (default: http://localhost:3002)"
    )
    args = parser.parse_args()
    
    print(f"=" * 60)
    print(f"API Verification - Bot API at {args.base_url}")
    print(f"=" * 60)
    
    results: list[VerificationResult] = []
    
    # Run health check verification
    health_result = await verify_api_health(args.base_url)
    results.append(health_result)
    print_result(health_result)
    
    # Run CORS verification
    cors_result = await verify_api_cors(args.base_url)
    results.append(cors_result)
    print_result(cors_result)
    
    # Run backtest endpoint verification
    backtest_result = await verify_backtest_endpoint(args.base_url)
    results.append(backtest_result)
    print_result(backtest_result)
    
    # Summary
    print(f"\n{'=' * 60}")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Summary: {passed}/{total} checks passed")
    print(f"{'=' * 60}")
    
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
