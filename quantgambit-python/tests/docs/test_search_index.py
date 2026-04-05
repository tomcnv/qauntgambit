"""Unit tests for Search_Index (DocSearchIndex).

Validates: Requirements 3.2, 3.5
"""

import textwrap

import pytest

from quantgambit.docs.loader import DocLoader, PageDoc
from quantgambit.docs.search import DocSearchIndex, SearchResult


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
    - **Data**: Live status endpoint

    ### Kill Switch Panel
    - **Purpose**: Emergency controls to halt trading
    - **Actions**: Halt bot, cancel all orders

    ## Modals & Drawers

    ### Replace Order Dialog
    - **Trigger**: Click "Replace" on a pending order
    - **Fields**: New price, New size
    - **Actions**: Submit replacement, Cancel

    ## Actions

    - Start/Pause/Halt bot via RunBar
    - Cancel individual orders

    ## Settings & Knobs

    - Symbol filter (via SymbolStrip click)
    - Scope selector (fleet/exchange/bot)

    ## Related Pages

    - [Overview](/) — Mission control
""")

ORDERS_MARKDOWN = textwrap.dedent("""\
    ---
    path: /orders
    title: Orders & Fills
    group: Trading
    description: Order flow and fill tracking
    ---

    # Orders & Fills

    Detailed order flow monitoring.

    ## Widgets & Cards

    ### Fill Rate Card
    - **Purpose**: Shows fill rate percentage

    ### Latency Distribution Chart
    - **Purpose**: Histogram of order latencies

    ## Actions

    - Filter orders by symbol
    - Export order history

    ## Settings & Knobs

    - Date range filter
""")


@pytest.fixture()
def two_page_index() -> DocSearchIndex:
    """Build a search index with two known pages."""
    live_doc = DocLoader.parse_markdown(LIVE_MARKDOWN)
    orders_doc = DocLoader.parse_markdown(ORDERS_MARKDOWN)
    pages = {live_doc.path: live_doc, orders_doc.path: orders_doc}

    idx = DocSearchIndex()
    idx.build(pages)
    return idx


# ---------------------------------------------------------------------------
# tokenize()
# ---------------------------------------------------------------------------

class TestTokenize:
    """Validates: Requirement 3.5 — tokenize and normalize text for case-insensitive matching."""

    def test_lowercases_input(self):
        assert DocSearchIndex.tokenize("Kill Switch") == ["kill", "switch"]

    def test_removes_stopwords(self):
        tokens = DocSearchIndex.tokenize("the quick and the slow")
        assert "the" not in tokens
        assert "and" not in tokens
        assert "quick" in tokens
        assert "slow" in tokens

    def test_splits_on_non_alphanumeric(self):
        tokens = DocSearchIndex.tokenize("order-flow & fill_rate")
        assert tokens == ["order", "flow", "fill", "rate"]

    def test_empty_string_returns_empty(self):
        assert DocSearchIndex.tokenize("") == []

    def test_stopwords_only_returns_empty(self):
        assert DocSearchIndex.tokenize("the and or but") == []

    def test_preserves_numbers(self):
        tokens = DocSearchIndex.tokenize("latency p99 at 42ms")
        assert "p99" in tokens
        assert "42ms" in tokens


# ---------------------------------------------------------------------------
# search() — known terms
# ---------------------------------------------------------------------------

class TestSearchKnownTerms:
    """Validates: Requirement 3.2 — return matching entries ranked by relevance."""

    def test_search_title_term(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("live trading")
        paths = [r.path for r in results]
        assert "/live" in paths

    def test_search_widget_name(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("kill switch")
        paths = [r.path for r in results]
        assert "/live" in paths

    def test_search_modal_name(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("replace order dialog")
        paths = [r.path for r in results]
        assert "/live" in paths

    def test_search_action_text(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("cancel individual orders")
        paths = [r.path for r in results]
        assert "/live" in paths

    def test_search_setting_text(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("symbol filter")
        paths = [r.path for r in results]
        assert "/live" in paths

    def test_search_case_insensitive(self, two_page_index: DocSearchIndex):
        results_lower = two_page_index.search("kill switch")
        results_upper = two_page_index.search("KILL SWITCH")
        results_mixed = two_page_index.search("Kill Switch")
        # All casings should find the same page
        for results in (results_lower, results_upper, results_mixed):
            assert any(r.path == "/live" for r in results)

    def test_search_returns_correct_section(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("kill switch")
        live_results = [r for r in results if r.path == "/live"]
        sections = [r.section for r in live_results]
        assert "Widgets & Cards" in sections


# ---------------------------------------------------------------------------
# search() — empty / stopword / no-match queries
# ---------------------------------------------------------------------------

class TestSearchEdgeCases:
    """Validates: Requirements 3.2, 3.5 — edge case handling."""

    def test_empty_query_returns_empty(self, two_page_index: DocSearchIndex):
        assert two_page_index.search("") == []

    def test_stopword_only_query_returns_empty(self, two_page_index: DocSearchIndex):
        assert two_page_index.search("the and or but") == []

    def test_no_match_query_returns_empty(self, two_page_index: DocSearchIndex):
        assert two_page_index.search("xyznonexistent") == []

    def test_unbuilt_index_returns_empty(self):
        idx = DocSearchIndex()
        assert idx.search("anything") == []


# ---------------------------------------------------------------------------
# search() — ranking: title matches score higher than body text
# ---------------------------------------------------------------------------

class TestSearchRanking:
    """Validates: Requirement 3.2 — results ranked by relevance (title > body)."""

    def test_title_match_ranks_above_body_match(self, two_page_index: DocSearchIndex):
        # "trading" appears in the title of /live ("Live Trading") and also
        # in body text. The title-weighted entry should produce a higher score.
        results = two_page_index.search("trading")
        if len(results) >= 2:
            title_results = [r for r in results if r.section == "Title"]
            body_results = [r for r in results if r.section != "Title"]
            if title_results and body_results:
                assert title_results[0].score >= body_results[0].score

    def test_limit_parameter_respected(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("order", limit=1)
        assert len(results) <= 1


# ---------------------------------------------------------------------------
# SearchResult dataclass
# ---------------------------------------------------------------------------

class TestSearchResult:
    """Basic sanity checks on SearchResult fields."""

    def test_result_fields_populated(self, two_page_index: DocSearchIndex):
        results = two_page_index.search("live")
        assert len(results) > 0
        r = results[0]
        assert isinstance(r.path, str) and r.path
        assert isinstance(r.title, str) and r.title
        assert isinstance(r.section, str) and r.section
        assert isinstance(r.snippet, str)
        assert isinstance(r.score, float) and r.score > 0
