"""Test fixtures for quantgambit tests.

This package contains reusable test fixtures for various testing scenarios.
"""

from quantgambit.tests.fixtures.parity_fixtures import (
    # Decision sequences
    KNOWN_GOOD_ACCEPTED_DECISIONS,
    KNOWN_GOOD_REJECTED_DECISIONS,
    KNOWN_GOOD_EDGE_CASE_DECISIONS,
    # Test configurations
    STANDARD_TEST_CONFIG,
    MODIFIED_TEST_CONFIG,
    PARITY_TEST_CONFIG,
    # Helper functions
    create_test_decision,
    create_test_config,
    create_decision_sequence,
    get_expected_outcome,
    # Fixture classes
    ParityTestFixtures,
)

__all__ = [
    # Decision sequences
    "KNOWN_GOOD_ACCEPTED_DECISIONS",
    "KNOWN_GOOD_REJECTED_DECISIONS",
    "KNOWN_GOOD_EDGE_CASE_DECISIONS",
    # Test configurations
    "STANDARD_TEST_CONFIG",
    "MODIFIED_TEST_CONFIG",
    "PARITY_TEST_CONFIG",
    # Helper functions
    "create_test_decision",
    "create_test_config",
    "create_decision_sequence",
    "get_expected_outcome",
    # Fixture classes
    "ParityTestFixtures",
]
