"""Unit tests for docs API endpoints (``quantgambit/api/docs_endpoints.py``).

Tests use ``httpx.AsyncClient`` with a minimal FastAPI app that includes the
docs router.  DocLoader and DocSearchIndex are populated with in-memory
fixtures — no filesystem access required.

Validates: Requirements 2.6, 3.2
"""

from __future__ import annotations

import textwrap

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from quantgambit.api.docs_endpoints import create_docs_router
from quantgambit.docs.loader import DocLoader
from quantgambit.docs.search import DocSearchIndex

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LIVE_MARKDOWN = textwrap.dedent("""\
    ---
    path: /live
    title: Live Trading
    group: Trading
    description: Active bot status & controls
    ---

    # Live Trading

    Real-time execution monitoring and control.

    ## Widgets & Cards

    ### Status Strip
    - **Purpose**: Shows heartbeat, WebSocket, last decision

    ### Kill Switch Panel
    - **Purpose**: Emergency controls to halt trading

    ## Modals & Drawers

    ### Replace Order Dialog
    - **Trigger**: Click "Replace" on a pending order
    - **Fields**: New price, New size

    ## Actions

    - Start/Pause/Halt bot via RunBar
    - Cancel individual orders

    ## Settings & Knobs

    - Symbol filter (via SymbolStrip click)

    ## Related Pages

    - [Overview](/) — Mission control
""")

ORDERS_MARKDOWN = textwrap.dedent("""\
    ---
    path: /orders
    title: Orders & Fills
    group: Trading
    description: Order flow and fill analysis
    ---

    # Orders & Fills

    Detailed order flow monitoring.

    ## Widgets & Cards

    ### Fill Rate KPI
    - **Purpose**: Shows fill rate percentage

    ### Latency Distribution
    - **Purpose**: Histogram of order latencies

    ## Modals & Drawers

    ### Trade Inspector Drawer
    - **Trigger**: Click any row in the orders table

    ## Actions

    - Filter orders by symbol
    - Export order history

    ## Settings & Knobs

    - Date range filter

    ## Related Pages

    - [Live Trading](/live) — Real-time monitoring
""")


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with the docs router for testing."""
    loader = DocLoader()
    loader._pages["/live"] = DocLoader.parse_markdown(LIVE_MARKDOWN)
    loader._pages["/orders"] = DocLoader.parse_markdown(ORDERS_MARKDOWN)

    index = DocSearchIndex()
    index.build(loader._pages)

    app = FastAPI()
    router = create_docs_router(doc_loader=loader, search_index=index)
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Tests: GET /docs/pages  (list all pages)
# ---------------------------------------------------------------------------


class TestListPages:
    """Tests for GET /docs/pages — list all documented pages."""

    @pytest.mark.asyncio
    async def test_returns_list(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_each_entry_has_required_fields(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages")
        for entry in resp.json():
            assert "path" in entry
            assert "title" in entry
            assert "group" in entry
            assert "description" in entry

    @pytest.mark.asyncio
    async def test_contains_live_page(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages")
        paths = [e["path"] for e in resp.json()]
        assert "/live" in paths

    @pytest.mark.asyncio
    async def test_contains_orders_page(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages")
        paths = [e["path"] for e in resp.json()]
        assert "/orders" in paths


# ---------------------------------------------------------------------------
# Tests: GET /docs/pages/{path}  (get single page — valid)
# ---------------------------------------------------------------------------


class TestGetPageValid:
    """Tests for GET /docs/pages/live — returns full doc for /live page (200)."""

    @pytest.mark.asyncio
    async def test_returns_200(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_correct_path(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        assert resp.json()["path"] == "/live"

    @pytest.mark.asyncio
    async def test_returns_title(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        assert resp.json()["title"] == "Live Trading"

    @pytest.mark.asyncio
    async def test_returns_group(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        assert resp.json()["group"] == "Trading"

    @pytest.mark.asyncio
    async def test_returns_widgets(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        widgets = resp.json()["widgets"]
        assert "Status Strip" in widgets
        assert "Kill Switch Panel" in widgets

    @pytest.mark.asyncio
    async def test_returns_modals(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        assert "Replace Order Dialog" in resp.json()["modals"]

    @pytest.mark.asyncio
    async def test_returns_markdown(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/live")
        assert "Kill Switch Panel" in resp.json()["markdown"]


# ---------------------------------------------------------------------------
# Tests: GET /docs/pages/{path}  (get single page — invalid / 404)
# ---------------------------------------------------------------------------


class TestGetPageInvalid:
    """Tests for GET /docs/pages/nonexistent — returns 404 with error and valid_paths."""

    @pytest.mark.asyncio
    async def test_returns_404(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_error_message(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/nonexistent")
        assert resp.json()["error"] == "Page not documented"

    @pytest.mark.asyncio
    async def test_returns_valid_paths(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/pages/nonexistent")
        valid = resp.json()["valid_paths"]
        assert "/live" in valid
        assert "/orders" in valid


# ---------------------------------------------------------------------------
# Tests: GET /docs/search  (search with results)
# ---------------------------------------------------------------------------


class TestSearchWithResults:
    """Tests for GET /docs/search?q=kill+switch — returns matching results."""

    @pytest.mark.asyncio
    async def test_returns_200(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/search", params={"q": "kill switch"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_results_contain_live_page(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/search", params={"q": "kill switch"})
        paths = [r["path"] for r in resp.json()["results"]]
        assert "/live" in paths

    @pytest.mark.asyncio
    async def test_each_result_has_required_fields(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/search", params={"q": "kill switch"})
        for r in resp.json()["results"]:
            assert "path" in r
            assert "title" in r
            assert "section" in r
            assert "snippet" in r
            assert "score" in r


# ---------------------------------------------------------------------------
# Tests: GET /docs/search  (empty / no-match queries)
# ---------------------------------------------------------------------------


class TestSearchEmpty:
    """Tests for empty and no-match search queries."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_results(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/search", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    @pytest.mark.asyncio
    async def test_nonexistent_term_returns_empty_results(self):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/docs/search", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        assert resp.json()["results"] == []
