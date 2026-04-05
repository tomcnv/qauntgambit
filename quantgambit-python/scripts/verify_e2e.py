#!/usr/bin/env python3
"""End-to-end verification script that runs all verification checks.

This script orchestrates all verification scripts (API, database, pipeline)
and generates a comprehensive summary report.

Usage:
    python scripts/verify_e2e.py [--base-url URL] [--db-url URL] [--redis-url URL]

Requirements: 4.6, 5.6
- 4.6: THE System SHALL provide a verification script that tests the live trading pipeline
- 5.6: THE System SHALL provide a verification script that creates and runs a test backtest
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verify_api import main as verify_api_main
from verify_db import main as verify_db_main
from verify_pipeline import main as verify_pipeline_main


@dataclass
class VerificationSuiteResult:
    """Result of a verification suite run."""
    name: str
    exit_code: int
    passed: bool
    duration_seconds: float
    error: Optional[str] = None


@dataclass
class E2EVerificationReport:
    """Complete end-to-end verification report."""
    timestamp: datetime
    suite_results: list[VerificationSuiteResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    
    @property
    def all_passed(self) -> bool:
        """Check if all verification suites passed."""
        return all(r.passed for r in self.suite_results)
    
    @property
    def passed_count(self) -> int:
        """Count of passed verification suites."""
        return sum(1 for r in self.suite_results if r.passed)
    
    @property
    def total_count(self) -> int:
        """Total count of verification suites."""
        return len(self.suite_results)


async def run_verification_suite(
    name: str,
    main_func,
    description: str,
) -> VerificationSuiteResult:
    """Run a verification suite and capture its result.
    
    Args:
        name: Name of the verification suite
        main_func: The main() function to call (async or sync)
        description: Description of what the suite verifies
        
    Returns:
        VerificationSuiteResult with status and timing
    """
    print(f"\n{'#' * 70}")
    print(f"# Running: {name}")
    print(f"# {description}")
    print(f"{'#' * 70}")
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        # Run the verification suite
        if asyncio.iscoroutinefunction(main_func):
            exit_code = await main_func()
        else:
            exit_code = main_func()
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        return VerificationSuiteResult(
            name=name,
            exit_code=exit_code,
            passed=(exit_code == 0),
            duration_seconds=duration,
            error=None
        )
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        print(f"\n❌ ERROR: {name} raised an exception: {e}")
        
        return VerificationSuiteResult(
            name=name,
            exit_code=1,
            passed=False,
            duration_seconds=duration,
            error=str(e)
        )


def print_summary_report(report: E2EVerificationReport) -> None:
    """Print a formatted summary report of all verification results.
    
    Args:
        report: The E2EVerificationReport to print
    """
    print("\n")
    print("=" * 70)
    print("END-TO-END VERIFICATION SUMMARY REPORT")
    print("=" * 70)
    print(f"Timestamp: {report.timestamp.isoformat()}")
    print(f"Total Duration: {report.total_duration_seconds:.2f} seconds")
    print("-" * 70)
    
    # Print individual suite results
    print("\nVerification Suite Results:")
    print("-" * 70)
    
    for result in report.suite_results:
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status}: {result.name} ({result.duration_seconds:.2f}s)")
        if result.error:
            print(f"         Error: {result.error}")
    
    # Print overall summary
    print("-" * 70)
    print(f"\nOverall: {report.passed_count}/{report.total_count} verification suites passed")
    
    if report.all_passed:
        print("\n🎉 ALL VERIFICATIONS PASSED!")
        print("   The system is ready for use.")
    else:
        print("\n⚠️  SOME VERIFICATIONS FAILED!")
        print("   Please review the failures above and take corrective action.")
        print("\n   Common fixes:")
        print("   - Ensure all services are running (Bot API, TimescaleDB, Redis)")
        print("   - Run database migrations: python scripts/run_migrations.py")
        print("   - Check environment variables in .env file")
        print("   - Review individual verification script output for details")
    
    print("=" * 70)


async def run_all_verifications() -> int:
    """Run all verification scripts and collect results.
    
    Returns:
        Exit code: 0 if all verifications pass, 1 if any fail
    """
    start_time = asyncio.get_event_loop().time()
    
    # Create the report
    report = E2EVerificationReport(
        timestamp=datetime.now(timezone.utc)
    )
    
    # Define verification suites to run
    verification_suites = [
        (
            "API Verification",
            verify_api_main,
            "Verifies Bot API health, CORS, and backtest endpoints"
        ),
        (
            "Database Verification",
            verify_db_main,
            "Verifies database tables, columns, and foreign keys"
        ),
        (
            "Pipeline Verification",
            verify_pipeline_main,
            "Verifies decision recording, backtest execution, and warm start"
        ),
    ]
    
    # Run each verification suite
    for name, main_func, description in verification_suites:
        result = await run_verification_suite(name, main_func, description)
        report.suite_results.append(result)
        
        # Add a small delay between suites to allow cleanup
        await asyncio.sleep(0.1)
    
    # Calculate total duration
    end_time = asyncio.get_event_loop().time()
    report.total_duration_seconds = end_time - start_time
    
    # Print summary report
    print_summary_report(report)
    
    # Return appropriate exit code
    return 0 if report.all_passed else 1


def main() -> int:
    """Entry point for the end-to-end verification script.
    
    Returns:
        Exit code: 0 if all verifications pass, 1 if any fail
    """
    parser = argparse.ArgumentParser(
        description="Run all end-to-end verification checks for the trading bot"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("BOT_API_URL", "http://localhost:3002"),
        help="Base URL of the Bot API (default: http://localhost:3002)"
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides environment variables)"
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL (overrides environment variables)"
    )
    args = parser.parse_args()
    
    # Set environment variables for child scripts if provided via CLI
    if args.base_url:
        os.environ["BOT_API_URL"] = args.base_url
    if args.db_url:
        os.environ["BOT_DB_URL"] = args.db_url
    if args.redis_url:
        os.environ["BOT_REDIS_URL"] = args.redis_url
    
    print("=" * 70)
    print("END-TO-END INTEGRATION VERIFICATION")
    print("=" * 70)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    print(f"Bot API URL: {args.base_url}")
    print("=" * 70)
    
    return asyncio.run(run_all_verifications())


if __name__ == "__main__":
    raise SystemExit(main())
