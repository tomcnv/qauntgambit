"""Unit tests for copilot documentation tools (get_page_docs, search_docs).

Validates: Requirements 5.2, 5.3, 5.5
"""

import textwrap

import pytest

from quantgambit.copilot.tools.doc_search import create_search_docs_tool
from quantgambit.copilot.tools.page_docs import create_get_page_docs_tool
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


def _build_loader() -> DocLoader:
    """Create a DocLoader with two pages pre-loaded (no filesystem)."""
    loader = DocLoader()
    loader._pages["/live"] = DocLoader.parse_markdown(LIVE_MARKDOWN)
    loader._pages["/orders"] = DocLoader.parse_markdown(ORDERS_MARKDOWN)
    return loader


def _build_search_index(loader: DocLoader) -> DocSearchIndex:
    """Build a search index from the loader's pages."""
    index = DocSearchIndex()
    index.build(loader._pages)
    return index


# ---------------------------------------------------------------------------
# get_page_docs — valid path
# ---------------------------------------------------------------------------


class TestGetPageDocsValidPath:
    """Validates: Requirement 5.2 — return full PageDoc content for valid path."""

    @pytest.fixture()
    def tool(self):
        loader = _build_loader()
        return create_get_page_docs_tool(doc_loader=loader)

    @pytest.mark.asyncio
    async def test_returns_success_true(self, tool):
        result = await tool.handler(page_path="/live")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_returns_correct_path(self, tool):
        result = await tool.handler(page_path="/live")
        assert result["path"] == "/live"

    @pytest.mark.asyncio
    async def test_returns_title(self, tool):
        result = await tool.handler(page_path="/live")
        assert result["title"] == "Live Trading"

    @pytest.mark.asyncio
    async def test_returns_group(self, tool):
        result = await tool.handler(page_path="/live")
        assert result["group"] == "Trading"

    @pytest.mark.asyncio
    async def test_returns_widgets(self, tool):
        result = await tool.handler(page_path="/live")
        assert "Status Strip" in result["widgets"]
        assert "Kill Switch Panel" in result["widgets"]

    @pytest.mark.asyncio
    async def test_returns_modals(self, tool):
        result = await tool.handler(page_path="/live")
        assert "Replace Order Dialog" in result["modals"]

    @pytest.mark.asyncio
    async def test_returns_actions(self, tool):
        result = await tool.handler(page_path="/live")
        assert len(result["actions"]) > 0

    @pytest.mark.asyncio
    async def test_returns_content_as_raw_markdown(self, tool):
        result = await tool.handler(page_path="/live")
        assert "# Live Trading" in result["content"]

    @pytest.mark.asyncio
    async def test_second_page_also_works(self, tool):
        result = await tool.handler(page_path="/orders")
        assert result["success"] is True
        assert result["title"] == "Orders & Fills"


# ---------------------------------------------------------------------------
# get_page_docs — invalid path
# ---------------------------------------------------------------------------


class TestGetPageDocsInvalidPath:
    """Validates: Requirement 5.3 — return error with valid paths for invalid path."""

    @pytest.fixture()
    def tool(self):
        loader = _build_loader()
        return create_get_page_docs_tool(doc_loader=loader)

    @pytest.mark.asyncio
    async def test_returns_success_false(self, tool):
        result = await tool.handler(page_path="/nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_returns_error_message(self, tool):
        result = await tool.handler(page_path="/nonexistent")
        assert "error" in result
        assert "/nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_valid_paths_list(self, tool):
        result = await tool.handler(page_path="/nonexistent")
        assert "valid_paths" in result
        assert "/live" in result["valid_paths"]
        assert "/orders" in result["valid_paths"]

    @pytest.mark.asyncio
    async def test_error_format_has_no_content_key(self, tool):
        result = await tool.handler(page_path="/nonexistent")
        assert "content" not in result


# ---------------------------------------------------------------------------
# get_page_docs — tool definition
# ---------------------------------------------------------------------------


class TestGetPageDocsToolDefinition:
    """Validates: Requirement 5.1 — tool registered with JSON Schema."""

    def test_tool_name(self):
        loader = _build_loader()
        tool = create_get_page_docs_tool(doc_loader=loader)
        assert tool.name == "get_page_docs"

    def test_tool_has_description(self):
        loader = _build_loader()
        tool = create_get_page_docs_tool(doc_loader=loader)
        assert len(tool.description) > 0

    def test_schema_requires_page_path(self):
        loader = _build_loader()
        tool = create_get_page_docs_tool(doc_loader=loader)
        assert "page_path" in tool.parameters_schema["properties"]
        assert "page_path" in tool.parameters_schema["required"]


# ---------------------------------------------------------------------------
# search_docs — with query
# ---------------------------------------------------------------------------


class TestSearchDocsWithQuery:
    """Validates: Requirement 5.5 — return matching snippets with paths and sections."""

    @pytest.fixture()
    def tool(self):
        loader = _build_loader()
        index = _build_search_index(loader)
        return create_search_docs_tool(search_index=index)

    @pytest.mark.asyncio
    async def test_returns_success_true(self, tool):
        result = await tool.handler(query="kill switch")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_returns_results_list(self, tool):
        result = await tool.handler(query="kill switch")
        assert isinstance(result["results"], list)
        assert len(result["results"]) > 0

    @pytest.mark.asyncio
    async def test_results_contain_matching_page(self, tool):
        result = await tool.handler(query="kill switch")
        paths = [r["path"] for r in result["results"]]
        assert "/live" in paths

    @pytest.mark.asyncio
    async def test_results_include_section_heading(self, tool):
        result = await tool.handler(query="kill switch")
        sections = [r["section"] for r in result["results"]]
        assert any(s for s in sections)

    @pytest.mark.asyncio
    async def test_search_for_orders_page_content(self, tool):
        result = await tool.handler(query="fill rate")
        paths = [r["path"] for r in result["results"]]
        assert "/orders" in paths

    @pytest.mark.asyncio
    async def test_limit_parameter_respected(self, tool):
        result = await tool.handler(query="trading", limit=1)
        assert len(result["results"]) <= 1


# ---------------------------------------------------------------------------
# search_docs — empty query
# ---------------------------------------------------------------------------


class TestSearchDocsEmptyQuery:
    """Validates: Requirement 5.5 — empty query returns empty results."""

    @pytest.fixture()
    def tool(self):
        loader = _build_loader()
        index = _build_search_index(loader)
        return create_search_docs_tool(search_index=index)

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty_results(self, tool):
        result = await tool.handler(query="")
        assert result["success"] is True
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_stopwords_only_returns_empty_results(self, tool):
        result = await tool.handler(query="the and or")
        assert result["success"] is True
        assert result["results"] == []


# ---------------------------------------------------------------------------
# search_docs — result format
# ---------------------------------------------------------------------------


class TestSearchDocsResultFormat:
    """Validates: Requirement 5.5 — result format includes path, title, section, snippet."""

    @pytest.fixture()
    def tool(self):
        loader = _build_loader()
        index = _build_search_index(loader)
        return create_search_docs_tool(search_index=index)

    @pytest.mark.asyncio
    async def test_each_result_has_path(self, tool):
        result = await tool.handler(query="kill switch")
        for r in result["results"]:
            assert "path" in r
            assert isinstance(r["path"], str)

    @pytest.mark.asyncio
    async def test_each_result_has_title(self, tool):
        result = await tool.handler(query="kill switch")
        for r in result["results"]:
            assert "title" in r
            assert isinstance(r["title"], str)

    @pytest.mark.asyncio
    async def test_each_result_has_section(self, tool):
        result = await tool.handler(query="kill switch")
        for r in result["results"]:
            assert "section" in r
            assert isinstance(r["section"], str)

    @pytest.mark.asyncio
    async def test_each_result_has_snippet(self, tool):
        result = await tool.handler(query="kill switch")
        for r in result["results"]:
            assert "snippet" in r
            assert isinstance(r["snippet"], str)

    @pytest.mark.asyncio
    async def test_each_result_has_score(self, tool):
        result = await tool.handler(query="kill switch")
        for r in result["results"]:
            assert "score" in r
            assert isinstance(r["score"], float)


# ---------------------------------------------------------------------------
# search_docs — tool definition
# ---------------------------------------------------------------------------


class TestSearchDocsToolDefinition:
    """Validates: Requirement 5.4 — tool registered with JSON Schema."""

    def test_tool_name(self):
        index = DocSearchIndex()
        tool = create_search_docs_tool(search_index=index)
        assert tool.name == "search_docs"

    def test_tool_has_description(self):
        index = DocSearchIndex()
        tool = create_search_docs_tool(search_index=index)
        assert len(tool.description) > 0

    def test_schema_requires_query(self):
        index = DocSearchIndex()
        tool = create_search_docs_tool(search_index=index)
        assert "query" in tool.parameters_schema["properties"]
        assert "query" in tool.parameters_schema["required"]

    def test_schema_has_optional_limit(self):
        index = DocSearchIndex()
        tool = create_search_docs_tool(search_index=index)
        assert "limit" in tool.parameters_schema["properties"]
        assert "limit" not in tool.parameters_schema.get("required", [])
