"""Unit tests for Doc_Loader.

Validates: Requirements 2.1, 2.2, 2.3
"""

import textwrap
from pathlib import Path

import pytest

from quantgambit.docs.loader import DocLoader, PageDoc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_MARKDOWN = textwrap.dedent("""\
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

    ### Trade Inspector Drawer
    - **Trigger**: Click any fill row in the live tape
    - **Content**: Full trade details, P&L, decision trace link

    ## Actions

    - Start/Pause/Halt bot via RunBar
    - Cancel individual orders
    - Replace order price/size

    ## Settings & Knobs

    - Symbol filter (via SymbolStrip click)
    - Scope selector (fleet/exchange/bot)

    ## Related Pages

    - [Overview](/) — Mission control
    - [Orders & Fills](/orders) — Detailed order flow
""")

NO_FRONTMATTER_MARKDOWN = textwrap.dedent("""\
    # Some Page

    No frontmatter here at all.
""")

EMPTY_FILE = ""

MALFORMED_YAML_MISSING_FIELDS = textwrap.dedent("""\
    ---
    path: /oops
    title: Oops Page
    ---

    # Oops

    Missing group and description.
""")


# ---------------------------------------------------------------------------
# parse_markdown — known fixture
# ---------------------------------------------------------------------------

class TestParseMarkdownKnownFixture:
    """Validates: Requirement 2.1 — parse Markdown Page_Doc files into structured data."""

    def test_frontmatter_fields(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        assert doc.path == "/live"
        assert doc.title == "Live Trading"
        assert doc.group == "Trading"
        assert doc.description == "Active bot status & controls"

    def test_raw_markdown_stored(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        assert doc.raw_markdown == VALID_MARKDOWN

    def test_widgets_extracted(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        assert doc.widgets == ["Status Strip", "Kill Switch Panel"]

    def test_modals_extracted(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        assert doc.modals == ["Replace Order Dialog", "Trade Inspector Drawer"]

    def test_actions_extracted(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        assert doc.actions == [
            "Start/Pause/Halt bot via RunBar",
            "Cancel individual orders",
            "Replace order price/size",
        ]

    def test_settings_extracted(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        assert doc.settings == [
            "Symbol filter (via SymbolStrip click)",
            "Scope selector (fleet/exchange/bot)",
        ]

    def test_sections_contain_expected_headings(self):
        doc = DocLoader.parse_markdown(VALID_MARKDOWN)
        expected = {"Widgets & Cards", "Modals & Drawers", "Actions", "Settings & Knobs", "Related Pages"}
        assert expected.issubset(set(doc.sections.keys()))


# ---------------------------------------------------------------------------
# parse_markdown — error cases
# ---------------------------------------------------------------------------

class TestParseMarkdownErrors:
    """Validates: Requirement 2.1 — error handling for invalid markdown."""

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError, match="Missing YAML frontmatter"):
            DocLoader.parse_markdown(NO_FRONTMATTER_MARKDOWN)

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="Missing YAML frontmatter"):
            DocLoader.parse_markdown(EMPTY_FILE)

    def test_malformed_yaml_missing_required_fields_raises(self):
        with pytest.raises(ValueError, match="Frontmatter missing required field"):
            DocLoader.parse_markdown(MALFORMED_YAML_MISSING_FIELDS)


# ---------------------------------------------------------------------------
# get_page
# ---------------------------------------------------------------------------

class TestGetPage:
    """Validates: Requirement 2.2 — return corresponding Page_Doc by path.
    Validates: Requirement 2.3 — return None for undocumented path.
    """

    def test_get_page_returns_loaded_doc(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "live.md").write_text(VALID_MARKDOWN, encoding="utf-8")

        loader = DocLoader(docs_dir)
        loader.load_all()

        page = loader.get_page("/live")
        assert page is not None
        assert page.path == "/live"
        assert page.title == "Live Trading"

    def test_get_page_returns_none_for_unknown_path(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "live.md").write_text(VALID_MARKDOWN, encoding="utf-8")

        loader = DocLoader(docs_dir)
        loader.load_all()

        assert loader.get_page("/nonexistent") is None


# ---------------------------------------------------------------------------
# list_pages
# ---------------------------------------------------------------------------

class TestListPages:
    """Validates: Requirement 2.6 — list all documented pages."""

    def test_list_pages_returns_correct_entries(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "live.md").write_text(VALID_MARKDOWN, encoding="utf-8")

        loader = DocLoader(docs_dir)
        loader.load_all()

        pages = loader.list_pages()
        assert len(pages) == 1
        assert pages[0] == {
            "path": "/live",
            "title": "Live Trading",
            "group": "Trading",
            "description": "Active bot status & controls",
        }

    def test_list_pages_empty_when_no_docs(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        loader = DocLoader(docs_dir)
        loader.load_all()

        assert loader.list_pages() == []


# ---------------------------------------------------------------------------
# load_all — duplicate paths
# ---------------------------------------------------------------------------

class TestLoadAllDuplicatePaths:
    """Validates: Error handling — duplicate page paths, last file wins."""

    def test_duplicate_paths_last_file_wins(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        md_v1 = VALID_MARKDOWN.replace("Active bot status & controls", "Version 1")
        md_v2 = VALID_MARKDOWN.replace("Active bot status & controls", "Version 2")

        # Files are loaded in sorted order, so "b_live.md" comes after "a_live.md"
        (docs_dir / "a_live.md").write_text(md_v1, encoding="utf-8")
        (docs_dir / "b_live.md").write_text(md_v2, encoding="utf-8")

        loader = DocLoader(docs_dir)
        loader.load_all()

        page = loader.get_page("/live")
        assert page is not None
        assert page.description == "Version 2"

    def test_load_all_skips_unparseable_files(self, tmp_path: Path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        (docs_dir / "good.md").write_text(VALID_MARKDOWN, encoding="utf-8")
        (docs_dir / "bad.md").write_text("not valid markdown at all", encoding="utf-8")

        loader = DocLoader(docs_dir)
        loader.load_all()

        # Good file loaded, bad file skipped
        assert loader.get_page("/live") is not None
        assert len(loader.list_pages()) == 1

    def test_load_all_nonexistent_dir(self):
        loader = DocLoader(Path("/nonexistent/path"))
        loader.load_all()
        assert loader.list_pages() == []
