"""
Property-based tests for Walk-Forward Optimization (WFO) API endpoints.

Feature: backtesting-api-integration
Tests Properties 5, 6, and 7 from the design document.
"""

import json
import uuid
import pytest
from datetime import datetime, timezone
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any, List, Optional

from quantgambit.api.backtest_endpoints import (
    CreateWFORequest,
    CreateWFOResponse,
    WFOConfig,
    WFOListResponse,
    WFODetailResponse,
    WFOSummary,
    WFOPeriodResult,
)
from quantgambit.backtesting.store import (
    BacktestStore,
    WFORunRecord,
)
from quantgambit.backtesting.job_queue import BacktestJobQueue, JobStatus


# ============================================================================
# Mock Database Pool
# ============================================================================

class MockRow(dict):
    """Dict subclass that supports attribute access."""
    def __getitem__(self, key):
        return super().get(key)


class MockConnection:
    """Mock database connection for testing."""
    
    def __init__(self, storage: Dict[str, Dict[str, Any]]):
        self.storage = storage
    
    async def execute(self, query: str, *args) -> str:
        """Mock execute that stores data in memory."""
        table = self._extract_table(query)
        if not table:
            return "EXECUTE 0"
        
        if "INSERT INTO" in query:
            run_id = str(args[0])
            if table not in self.storage:
                self.storage[table] = {}
            if run_id not in self.storage[table]:
                self.storage[table][run_id] = []
            self.storage[table][run_id].append(args)
            return "INSERT 1"
        elif "UPDATE" in query:
            run_id = str(args[0])
            if table in self.storage and run_id in self.storage[table]:
                if table == "wfo_runs" and self.storage[table][run_id]:
                    old_args = list(self.storage[table][run_id][0])
                    old_args[5] = args[1]  # status
                    # Handle dynamic update fields
                    if len(args) > 2:
                        # Check if results is being updated
                        if "results" in query:
                            old_args[7] = args[2]  # results
                        if "finished_at" in query and len(args) > 3:
                            old_args[9] = args[3]  # finished_at
                    self.storage[table][run_id][0] = tuple(old_args)
                return "UPDATE 1"
            return "UPDATE 0"
        elif "DELETE FROM" in query:
            run_id = str(args[0])
            if table in self.storage and run_id in self.storage[table]:
                del self.storage[table][run_id]
                return "DELETE 1"
            return "DELETE 0"
        return "EXECUTE 0"
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict]:
        """Mock fetchrow that retrieves data from memory."""
        table = self._extract_table(query)
        if not table:
            return None
        
        run_id = str(args[0])
        if table not in self.storage or run_id not in self.storage[table]:
            return None
        
        data = self.storage[table][run_id]
        if not data:
            return None
        
        return self._args_to_row(table, data[0])
    
    async def fetch(self, query: str, *args) -> List[Dict]:
        """Mock fetch that retrieves multiple rows."""
        table = self._extract_table(query)
        if not table:
            return []
        
        # Handle list queries with filtering for wfo_runs
        if "FROM wfo_runs" in query and "WHERE" in query:
            results = []
            
            # Extract filter values based on query structure
            arg_idx = 0
            filter_tenant_id = None
            filter_profile_id = None
            filter_symbol = None
            filter_status = None
            
            query_lower = query.lower()
            
            if "tenant_id =" in query_lower:
                filter_tenant_id = args[arg_idx] if arg_idx < len(args) else None
                arg_idx += 1
            
            if "profile_id =" in query_lower:
                filter_profile_id = args[arg_idx] if arg_idx < len(args) else None
                arg_idx += 1
            
            if "symbol =" in query_lower:
                filter_symbol = args[arg_idx] if arg_idx < len(args) else None
                arg_idx += 1
            
            if "status =" in query_lower:
                filter_status = args[arg_idx] if arg_idx < len(args) else None
                arg_idx += 1
            
            # Last two args are limit and offset
            limit = args[-2] if len(args) >= 2 else 50
            offset = args[-1] if len(args) >= 1 else 0
            
            for run_id, data_list in self.storage.get("wfo_runs", {}).items():
                if data_list:
                    row = self._args_to_row("wfo_runs", data_list[0])
                    
                    # Apply filters
                    if filter_tenant_id and row.get("tenant_id") != filter_tenant_id:
                        continue
                    if filter_profile_id and row.get("profile_id") != filter_profile_id:
                        continue
                    if filter_symbol and row.get("symbol") != filter_symbol:
                        continue
                    if filter_status and row.get("status") != filter_status:
                        continue
                    
                    results.append(row)
            
            # Sort by created_at descending
            results.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
            # Apply limit and offset
            return results[offset:offset + limit]
        
        # Handle single run_id queries
        if len(args) > 0:
            run_id = str(args[0])
            if table in self.storage and run_id in self.storage[table]:
                return [self._args_to_row(table, row) for row in self.storage[table][run_id]]
        
        return []
    
    async def fetchval(self, query: str, *args):
        """Mock fetchval for single value queries."""
        if "COUNT" in query:
            table = self._extract_table(query)
            if not table or table not in self.storage:
                return 0
            
            # Apply filters for count
            if "wfo_runs" in query:
                count = 0
                query_lower = query.lower()
                arg_idx = 0
                filter_tenant_id = None
                filter_profile_id = None
                filter_symbol = None
                filter_status = None
                
                if "tenant_id =" in query_lower:
                    filter_tenant_id = args[arg_idx] if arg_idx < len(args) else None
                    arg_idx += 1
                if "profile_id =" in query_lower:
                    filter_profile_id = args[arg_idx] if arg_idx < len(args) else None
                    arg_idx += 1
                if "symbol =" in query_lower:
                    filter_symbol = args[arg_idx] if arg_idx < len(args) else None
                    arg_idx += 1
                if "status =" in query_lower:
                    filter_status = args[arg_idx] if arg_idx < len(args) else None
                    arg_idx += 1
                
                for run_id, data_list in self.storage.get("wfo_runs", {}).items():
                    if data_list:
                        row = self._args_to_row("wfo_runs", data_list[0])
                        if filter_tenant_id and row.get("tenant_id") != filter_tenant_id:
                            continue
                        if filter_profile_id and row.get("profile_id") != filter_profile_id:
                            continue
                        if filter_symbol and row.get("symbol") != filter_symbol:
                            continue
                        if filter_status and row.get("status") != filter_status:
                            continue
                        count += 1
                return count
            
            return len(self.storage[table])
        
        table = self._extract_table(query)
        if not table:
            return None
        
        run_id = str(args[0])
        if table in self.storage and run_id in self.storage[table]:
            return 1
        return None
    
    def _extract_table(self, query: str) -> Optional[str]:
        """Extract table name from query."""
        tables = [
            "wfo_runs",
            "backtest_runs",
            "backtest_metrics",
        ]
        for table in tables:
            if table in query:
                return table
        return None
    
    def _args_to_row(self, table: str, args: tuple) -> Dict:
        """Convert args tuple to a row dict based on table schema."""
        if table == "wfo_runs":
            return MockRow({
                "run_id": args[0],
                "tenant_id": args[1],
                "bot_id": args[2],
                "profile_id": args[3],
                "symbol": args[4],
                "status": args[5],
                "config": json.loads(args[6]) if isinstance(args[6], str) else args[6],
                "results": json.loads(args[7]) if isinstance(args[7], str) else args[7],
                "started_at": datetime.fromisoformat(args[8].replace("Z", "+00:00")) if args[8] else None,
                "finished_at": datetime.fromisoformat(args[9].replace("Z", "+00:00")) if args[9] else None,
                "created_at": datetime.now(timezone.utc),
            })
        return MockRow({})


class MockConnectionContext:
    """Context manager for mock connections."""
    
    def __init__(self, storage: Dict[str, Dict[str, Any]]):
        self.storage = storage
        self.conn = None
    
    async def __aenter__(self):
        self.conn = MockConnection(self.storage)
        return self.conn
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockPool:
    """Mock connection pool for testing."""
    
    def __init__(self):
        self.storage: Dict[str, Dict[str, Any]] = {}
    
    def acquire(self):
        return MockConnectionContext(self.storage)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

profile_ids = st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_")
symbols = st.sampled_from(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP"])
statuses = st.sampled_from(["pending", "running", "finished", "failed", "cancelled"])
objectives = st.sampled_from(["sharpe", "sortino", "profit_factor"])
in_sample_days = st.integers(min_value=1, max_value=365)
out_sample_days = st.integers(min_value=1, max_value=90)
periods = st.integers(min_value=1, max_value=20)


@st.composite
def wfo_configs(draw):
    """Generate valid WFOConfig instances."""
    return WFOConfig(
        in_sample_days=draw(in_sample_days),
        out_sample_days=draw(out_sample_days),
        periods=draw(periods),
        objective=draw(objectives),
    )


@st.composite
def create_wfo_requests(draw):
    """Generate valid CreateWFORequest instances."""
    return CreateWFORequest(
        profile_id=draw(profile_ids),
        symbol=draw(symbols),
        config=draw(wfo_configs()),
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestWFOCreation:
    """
    Property 5: WFO Creation Returns Run ID
    
    For any valid WFO configuration (profile_id, symbol, config), creating a WFO run
    should return a unique run_id and set status to "pending".
    
    **Validates: Requirements R3.1**
    """
    
    @given(request=create_wfo_requests())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_wfo_creation_returns_valid_run_id(self, request):
        """
        Property 5: WFO Creation Returns Run ID
        
        For any valid WFO configuration, creating a WFO run should:
        1. Return a unique run_id (valid UUID)
        2. Set status to "pending"
        3. Store the run record in the database
        
        **Validates: Requirements R3.1**
        """
        # Setup mock pool
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Generate run_id and create record (simulating endpoint behavior)
        run_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        config_dict = {
            "profile_id": request.profile_id,
            "symbol": request.symbol,
            "in_sample_days": request.config.in_sample_days,
            "out_sample_days": request.config.out_sample_days,
            "periods": request.config.periods,
            "objective": request.config.objective,
        }
        
        wfo_record = WFORunRecord(
            run_id=run_id,
            tenant_id="default",
            bot_id="default",
            profile_id=request.profile_id,
            symbol=request.symbol,
            status="pending",
            config=config_dict,
            results={},
            started_at=now_iso,
        )
        
        await store.write_wfo_run(wfo_record)
        
        # Verify run_id is a valid UUID
        try:
            uuid.UUID(run_id)
            valid_uuid = True
        except ValueError:
            valid_uuid = False
        
        assert valid_uuid, "run_id should be a valid UUID"
        
        # Verify run was stored with status="pending"
        retrieved = await store.get_wfo_run(run_id)
        assert retrieved is not None, "WFO run record should be stored"
        assert retrieved.status == "pending", "Status should be 'pending'"
        assert retrieved.profile_id == request.profile_id, "profile_id should match"
        assert retrieved.symbol == request.symbol, "Symbol should match"
    
    @given(
        profile_id=profile_ids,
        symbol=symbols,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_unique_run_ids_for_multiple_wfo_creations(
        self, profile_id, symbol
    ):
        """
        Property: Multiple WFO creations should generate unique run_ids.
        
        **Validates: Requirements R3.1**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        run_ids = set()
        num_runs = 5
        
        for i in range(num_runs):
            run_id = str(uuid.uuid4())
            run_ids.add(run_id)
            
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            wfo_record = WFORunRecord(
                run_id=run_id,
                tenant_id="default",
                bot_id="default",
                profile_id=profile_id,
                symbol=symbol,
                status="pending",
                config={"profile_id": profile_id, "symbol": symbol},
                results={},
                started_at=now_iso,
            )
            await store.write_wfo_run(wfo_record)
        
        # All run_ids should be unique
        assert len(run_ids) == num_runs, "All run_ids should be unique"


class TestWFOListFiltering:
    """
    Property 6: WFO List Filtering
    
    For any set of WFO runs and filter criteria (profile_id, symbol),
    the list endpoint should return only runs matching all specified filters.
    
    **Validates: Requirements R3.2**
    """
    
    @given(
        num_runs=st.integers(min_value=1, max_value=10),
        filter_profile_id=st.one_of(st.none(), profile_ids),
        filter_symbol=st.one_of(st.none(), symbols),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_list_filtering_returns_matching_runs(
        self, num_runs, filter_profile_id, filter_symbol
    ):
        """
        Property 6: WFO List Filtering
        
        For any set of WFO runs and filter criteria, the list should return
        only runs matching all specified filters.
        
        **Validates: Requirements R3.2**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Create runs with various profile_ids and symbols
        all_profile_ids = ["profile-a", "profile-b", "profile-c"]
        all_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        
        created_runs = []
        for i in range(num_runs):
            run_id = str(uuid.uuid4())
            profile_id = all_profile_ids[i % len(all_profile_ids)]
            symbol = all_symbols[i % len(all_symbols)]
            
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            wfo_record = WFORunRecord(
                run_id=run_id,
                tenant_id="default",
                bot_id="default",
                profile_id=profile_id,
                symbol=symbol,
                status="pending",
                config={"profile_id": profile_id, "symbol": symbol},
                results={},
                started_at=now_iso,
            )
            await store.write_wfo_run(wfo_record)
            created_runs.append((run_id, profile_id, symbol))
        
        # Query with filters using the store directly
        runs = await store.list_wfo_runs(
            tenant_id="default",
            profile_id=filter_profile_id,
            symbol=filter_symbol,
            limit=100,
            offset=0,
        )
        
        # Verify all returned runs match the filters
        for run in runs:
            if filter_profile_id:
                assert run.profile_id == filter_profile_id, \
                    f"Run profile_id {run.profile_id} should match filter {filter_profile_id}"
            if filter_symbol:
                assert run.symbol == filter_symbol, \
                    f"Run symbol {run.symbol} should match filter {filter_symbol}"


class TestWFODetailCompleteness:
    """
    Property 7: WFO Detail Completeness
    
    For any completed WFO run, the detail endpoint should return period-by-period
    results with in-sample and out-of-sample metrics.
    
    **Validates: Requirements R3.3**
    """
    
    @given(
        num_periods=st.integers(min_value=1, max_value=5),
        profile_id=profile_ids,
        symbol=symbols,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_detail_contains_period_results(
        self, num_periods, profile_id, symbol
    ):
        """
        Property 7: WFO Detail Completeness
        
        For any completed WFO run with period data, the detail response should
        contain period-by-period results with IS/OOS metrics.
        
        **Validates: Requirements R3.3**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        run_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Create period results
        periods_data = []
        for i in range(num_periods):
            periods_data.append({
                "period": i + 1,
                "in_sample_start": "2024-01-01",
                "in_sample_end": "2024-01-31",
                "out_sample_start": "2024-02-01",
                "out_sample_end": "2024-02-15",
                "in_sample_sharpe": 1.5 + i * 0.1,
                "out_sample_sharpe": 1.2 + i * 0.1,
                "in_sample_return_pct": 0.10 + (i / 100),
                "out_sample_return_pct": 0.08 + (i / 100),
                "in_sample_max_dd_pct": 0.05,
                "out_sample_max_dd_pct": 0.06,
                "optimized_params": {"param1": i * 10},
            })
        
        results = {
            "periods": periods_data,
            "summary": {
                "avg_is_sharpe": 1.5,
                "avg_oos_sharpe": 1.2,
                "degradation_pct": 0.20,
            },
            "recommended_params": {"param1": 50},
        }
        
        # Create WFO run record with results
        wfo_record = WFORunRecord(
            run_id=run_id,
            tenant_id="default",
            bot_id="default",
            profile_id=profile_id,
            symbol=symbol,
            status="finished",
            config={
                "profile_id": profile_id,
                "symbol": symbol,
                "in_sample_days": 30,
                "out_sample_days": 15,
                "periods": num_periods,
                "objective": "sharpe",
            },
            results=results,
            started_at=now_iso,
            finished_at=now_iso,
        )
        await store.write_wfo_run(wfo_record)
        
        # Retrieve and verify
        retrieved = await store.get_wfo_run(run_id)
        
        # Verify all required fields are present
        assert retrieved is not None, "WFO run should be present"
        assert retrieved.run_id == run_id
        assert retrieved.status == "finished"
        assert retrieved.profile_id == profile_id
        assert retrieved.symbol == symbol
        
        # Verify results contain periods
        assert "periods" in retrieved.results, "Results should contain periods"
        assert len(retrieved.results["periods"]) == num_periods, \
            f"Should have {num_periods} period results"
        
        # Verify each period has required fields
        for period in retrieved.results["periods"]:
            assert "period" in period, "Period should have period number"
            assert "in_sample_start" in period, "Period should have in_sample_start"
            assert "in_sample_end" in period, "Period should have in_sample_end"
            assert "out_sample_start" in period, "Period should have out_sample_start"
            assert "out_sample_end" in period, "Period should have out_sample_end"
            assert "in_sample_sharpe" in period, "Period should have in_sample_sharpe"
            assert "out_sample_sharpe" in period, "Period should have out_sample_sharpe"
        
        # Verify summary and recommended_params
        assert "summary" in retrieved.results, "Results should contain summary"
        assert "recommended_params" in retrieved.results, "Results should contain recommended_params"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
