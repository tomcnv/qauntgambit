"""
Tests for persistence removal from Runtime.

Verifies that the Runtime class no longer imports or calls persistence
functions from persistence_bootstrap.py, as persistence is now handled
exclusively by the DataPersistenceWorker.

Feature: bot-integration-fixes
Requirements: 1.1, 1.2, 1.3
"""

import ast
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRuntimePersistenceImports:
    """Tests verifying Runtime does not import persistence_bootstrap functions."""
    
    def test_runtime_module_does_not_import_initialize_persistence(self):
        """Runtime module should NOT import initialize_persistence from persistence_bootstrap.
        
        Validates: Requirement 1.1 - WHEN the Runtime starts THEN the System SHALL NOT
        initialize persistence components via initialize_persistence() from persistence_bootstrap.py
        """
        # Read the source file and parse it as AST
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        tree = ast.parse(source_code)
        
        # Check all import statements
        persistence_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'persistence_bootstrap' in node.module:
                    for alias in node.names:
                        persistence_imports.append(alias.name)
        
        assert 'initialize_persistence' not in persistence_imports, \
            "Runtime should NOT import initialize_persistence from persistence_bootstrap"
    
    def test_runtime_module_does_not_import_start_persistence_background_tasks(self):
        """Runtime module should NOT import start_persistence_background_tasks.
        
        Validates: Requirement 1.2 - WHEN the Runtime starts THEN the System SHALL NOT
        call start_persistence_background_tasks() for orderbook/trade persistence
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        tree = ast.parse(source_code)
        
        persistence_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'persistence_bootstrap' in node.module:
                    for alias in node.names:
                        persistence_imports.append(alias.name)
        
        assert 'start_persistence_background_tasks' not in persistence_imports, \
            "Runtime should NOT import start_persistence_background_tasks from persistence_bootstrap"
    
    def test_runtime_module_does_not_import_stop_persistence(self):
        """Runtime module should NOT import stop_persistence from persistence_bootstrap.
        
        Validates: Requirement 1.3 - WHEN the Runtime shuts down THEN the System SHALL NOT
        call stop_persistence() for orderbook/trade persistence
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        tree = ast.parse(source_code)
        
        persistence_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'persistence_bootstrap' in node.module:
                    for alias in node.names:
                        persistence_imports.append(alias.name)
        
        assert 'stop_persistence' not in persistence_imports, \
            "Runtime should NOT import stop_persistence from persistence_bootstrap"
    
    def test_runtime_module_does_not_import_persistence_components(self):
        """Runtime module should NOT import PersistenceComponents from persistence_bootstrap.
        
        Validates: Requirements 1.1, 1.2, 1.3 - Runtime should not use any persistence
        bootstrap components as persistence is handled by DataPersistenceWorker.
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        tree = ast.parse(source_code)
        
        persistence_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'persistence_bootstrap' in node.module:
                    for alias in node.names:
                        persistence_imports.append(alias.name)
        
        assert 'PersistenceComponents' not in persistence_imports, \
            "Runtime should NOT import PersistenceComponents from persistence_bootstrap"


class TestRuntimeStartNoPersistence:
    """Tests verifying Runtime.start() does not call persistence functions."""
    
    def test_start_does_not_call_initialize_persistence(self):
        """Runtime.start() should NOT call initialize_persistence.
        
        Validates: Requirement 1.1 - WHEN the Runtime starts THEN the System SHALL NOT
        initialize persistence components via initialize_persistence() from persistence_bootstrap.py
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that initialize_persistence is not called anywhere in the source
        assert 'initialize_persistence' not in source_code, \
            "Runtime should NOT call initialize_persistence anywhere in the module"
    
    def test_start_does_not_call_start_persistence_background_tasks(self):
        """Runtime.start() should NOT call start_persistence_background_tasks.
        
        Validates: Requirement 1.2 - WHEN the Runtime starts THEN the System SHALL NOT
        call start_persistence_background_tasks() for orderbook/trade persistence
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        assert 'start_persistence_background_tasks' not in source_code, \
            "Runtime should NOT call start_persistence_background_tasks anywhere in the module"


class TestRuntimeShutdownNoPersistence:
    """Tests verifying Runtime.shutdown() does not call persistence functions."""
    
    def test_shutdown_does_not_call_stop_persistence(self):
        """Runtime.shutdown() should NOT call stop_persistence.
        
        Validates: Requirement 1.3 - WHEN the Runtime shuts down THEN the System SHALL NOT
        call stop_persistence() for orderbook/trade persistence
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that stop_persistence is not called anywhere in the source
        assert 'stop_persistence' not in source_code, \
            "Runtime should NOT call stop_persistence anywhere in the module"


class TestRuntimeRetainsNonDuplicatedComponents:
    """Tests verifying Runtime still initializes non-duplicated components.
    
    Per Requirement 1.6: THE Runtime SHALL retain initialization of DecisionRecorder,
    WarmStartLoader, and LiveDataValidator (these are NOT duplicated in DataPersistenceWorker)
    """
    
    def test_runtime_imports_decision_recorder(self):
        """Runtime should still import DecisionRecorder.
        
        Validates: Requirement 1.6 - Runtime SHALL retain DecisionRecorder initialization
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        tree = ast.parse(source_code)
        
        decision_recorder_imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'decision_recording' in node.module:
                    for alias in node.names:
                        if alias.name == 'DecisionRecorder':
                            decision_recorder_imported = True
                            break
        
        assert decision_recorder_imported, \
            "Runtime should import DecisionRecorder (not duplicated in DataPersistenceWorker)"
    
    def test_runtime_imports_warm_start_loader(self):
        """Runtime should still import WarmStartLoader.
        
        Validates: Requirement 1.6 - Runtime SHALL retain WarmStartLoader initialization
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        tree = ast.parse(source_code)
        
        warm_start_imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'warm_start' in node.module:
                    for alias in node.names:
                        if alias.name == 'WarmStartLoader':
                            warm_start_imported = True
                            break
        
        assert warm_start_imported, \
            "Runtime should import WarmStartLoader (not duplicated in DataPersistenceWorker)"
    
    def test_runtime_source_contains_decision_recorder_initialization(self):
        """Runtime should initialize DecisionRecorder.
        
        Validates: Requirement 1.6 - Runtime SHALL retain DecisionRecorder initialization
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that DecisionRecorder is instantiated
        assert 'self.decision_recorder' in source_code, \
            "Runtime should have decision_recorder attribute"
        assert 'DecisionRecorder(' in source_code, \
            "Runtime should instantiate DecisionRecorder"
    
    def test_runtime_source_contains_warm_start_loader_initialization(self):
        """Runtime should initialize WarmStartLoader.
        
        Validates: Requirement 1.6 - Runtime SHALL retain WarmStartLoader initialization
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that WarmStartLoader is instantiated
        assert 'self.warm_start_loader' in source_code, \
            "Runtime should have warm_start_loader attribute"
        assert 'WarmStartLoader(' in source_code, \
            "Runtime should instantiate WarmStartLoader"


class TestRuntimeNoPersistenceAttribute:
    """Tests verifying Runtime does not have _persistence attribute."""
    
    def test_runtime_does_not_have_persistence_attribute(self):
        """Runtime should NOT have self._persistence attribute.
        
        Validates: Requirements 1.1, 1.2, 1.3 - Runtime should not store
        persistence components as they are handled by DataPersistenceWorker.
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that self._persistence is not used
        assert 'self._persistence' not in source_code, \
            "Runtime should NOT have self._persistence attribute"


class TestDecisionRecorderEnabledEnvVar:
    """Tests for DECISION_RECORDER_ENABLED environment variable support.
    
    Feature: bot-integration-fixes
    Requirements: 5.3, 5.7
    """
    
    def test_runtime_source_checks_decision_recorder_enabled_env_var(self):
        """Runtime should check DECISION_RECORDER_ENABLED environment variable.
        
        Validates: Requirement 5.3 - THE System SHALL support DECISION_RECORDER_ENABLED
        environment variable with default value "true"
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that DECISION_RECORDER_ENABLED is checked
        assert 'DECISION_RECORDER_ENABLED' in source_code, \
            "Runtime should check DECISION_RECORDER_ENABLED environment variable"
    
    def test_runtime_source_defaults_decision_recorder_enabled_to_true(self):
        """Runtime should default DECISION_RECORDER_ENABLED to "true".
        
        Validates: Requirement 5.3 - THE System SHALL support DECISION_RECORDER_ENABLED
        environment variable with default value "true"
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that the default is "true"
        assert 'os.getenv("DECISION_RECORDER_ENABLED", "true")' in source_code, \
            "Runtime should default DECISION_RECORDER_ENABLED to 'true'"
    
    def test_runtime_source_conditionally_initializes_decision_recorder(self):
        """Runtime should conditionally initialize DecisionRecorder based on env var.
        
        Validates: Requirement 5.7 - WHEN DECISION_RECORDER_ENABLED is "false" THEN
        the Runtime SHALL skip DecisionRecorder initialization
        """
        import quantgambit.runtime.app as runtime_module
        source_file = inspect.getfile(runtime_module)
        
        with open(source_file, 'r') as f:
            source_code = f.read()
        
        # Check that decision_recorder_enabled is used in the condition
        assert 'decision_recorder_enabled' in source_code, \
            "Runtime should have decision_recorder_enabled variable"
        
        # Check that the condition includes decision_recorder_enabled
        assert 'if decision_recorder_enabled and timescale_pool:' in source_code, \
            "Runtime should check decision_recorder_enabled before initializing DecisionRecorder"
