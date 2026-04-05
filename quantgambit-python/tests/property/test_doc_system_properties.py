"""
Property-based tests for the platform documentation system.

Feature: platform-documentation-system
Tests correctness properties for:
- Property 2: Markdown parse/print round-trip

**Validates: Requirements 2.1, 2.4, 2.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from quantgambit.docs.loader import DocLoader, PageDoc


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Safe characters for frontmatter values — no newlines, no colons at start,
# no "---" sequences that would break frontmatter parsing.
# Values are mapped through .strip() to match the normalisation the parser applies.
_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters=("-", "_", "&", ",", ".", "(", ")"),
    ),
    min_size=1,
    max_size=40,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0 and "---" not in s)

# Route paths like "/live", "/risk/limits", "/bot/123/decisions"
_route_path = st.from_regex(r"/[a-z][a-z0-9\-]{0,15}(/[a-z][a-z0-9\-]{0,15}){0,2}", fullmatch=True)

# Nav groups
_group = st.sampled_from(["Trading", "Risk", "Analysis", "Research", "System"])

# Widget / modal / action / setting names — simple identifiers.
# Stripped to match the normalisation the parser applies to ### headings and - items.
_item_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=("-", "_", "&", " ")),
    min_size=1,
    max_size=30,
).map(lambda s: s.strip()).filter(
    lambda s: len(s) > 0 and not s.startswith("#") and not s.startswith("-")
)


def _unique_list(element_strategy, min_size=0, max_size=5):
    """Generate a list of unique non-empty strings."""
    return st.lists(element_strategy, min_size=min_size, max_size=max_size, unique=True)


def _build_section_content(h3_names: list[str], list_items: list[str]) -> str:
    """Build a section body from ### headings and/or - list items."""
    parts: list[str] = []
    for name in h3_names:
        parts.append(f"### {name}")
        parts.append(f"- **Purpose**: Describes {name}")
        parts.append("")
    for item in list_items:
        parts.append(f"- {item}")
    return "\n".join(parts).strip()


@st.composite
def page_doc_strategy(draw):
    """Generate a random valid PageDoc with consistent sections.

    The strategy builds a PageDoc whose ``sections`` dict is consistent
    with its ``widgets``, ``modals``, ``actions``, and ``settings`` lists,
    so that a round-trip through ``to_markdown`` → ``parse_markdown``
    produces an equivalent object.
    """
    path = draw(_route_path)
    title = draw(_safe_text)
    group = draw(_group)
    description = draw(_safe_text)

    widgets = draw(_unique_list(_item_name, max_size=4))
    modals = draw(_unique_list(_item_name, max_size=3))
    actions = draw(_unique_list(_item_name, max_size=4))
    settings_list = draw(_unique_list(_item_name, max_size=3))

    # Optionally include an intro paragraph
    include_intro = draw(st.booleans())
    intro_text = draw(_safe_text) if include_intro else ""

    # Build sections dict that is consistent with the structured lists
    sections: dict[str, str] = {}

    if intro_text:
        sections["_intro"] = intro_text

    if widgets:
        sections["Widgets & Cards"] = _build_section_content(widgets, [])

    if modals:
        sections["Modals & Drawers"] = _build_section_content(modals, [])

    if actions:
        sections["Actions"] = _build_section_content([], actions)

    if settings_list:
        sections["Settings & Knobs"] = _build_section_content([], settings_list)

    # Optionally add a Related Pages section
    if draw(st.booleans()):
        sections["Related Pages"] = "- [Overview](/) — Mission control"

    return PageDoc(
        path=path,
        title=title,
        group=group,
        description=description,
        raw_markdown="",  # raw_markdown is not part of round-trip equivalence
        sections=sections,
        widgets=widgets,
        modals=modals,
        actions=actions,
        settings=settings_list,
    )


# =============================================================================
# Property 2: Markdown parse/print round-trip
# =============================================================================


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_path(doc: PageDoc):
    """to_markdown → parse_markdown preserves the page path.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.path == doc.path


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_title(doc: PageDoc):
    """to_markdown → parse_markdown preserves the page title.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.title == doc.title


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_group(doc: PageDoc):
    """to_markdown → parse_markdown preserves the nav group.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.group == doc.group


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_description(doc: PageDoc):
    """to_markdown → parse_markdown preserves the description.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.description == doc.description


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_widgets(doc: PageDoc):
    """to_markdown → parse_markdown preserves the widgets list.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.widgets == doc.widgets


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_modals(doc: PageDoc):
    """to_markdown → parse_markdown preserves the modals list.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.modals == doc.modals


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_actions(doc: PageDoc):
    """to_markdown → parse_markdown preserves the actions list.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.actions == doc.actions


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_settings(doc: PageDoc):
    """to_markdown → parse_markdown preserves the settings list.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.settings == doc.settings


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_preserves_sections(doc: PageDoc):
    """to_markdown → parse_markdown preserves all sections.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)
    assert doc2.sections == doc.sections


@given(doc=page_doc_strategy())
@settings(max_examples=200, deadline=None)
def test_property_2_round_trip_full_equivalence(doc: PageDoc):
    """to_markdown → parse_markdown produces a fully equivalent PageDoc.

    Checks all fields at once (path, title, group, description, sections,
    widgets, modals, actions, settings).  raw_markdown is excluded because
    the pretty-printer normalises whitespace.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """
    md = DocLoader.to_markdown(doc)
    doc2 = DocLoader.parse_markdown(md)

    assert doc2.path == doc.path
    assert doc2.title == doc.title
    assert doc2.group == doc.group
    assert doc2.description == doc.description
    assert doc2.sections == doc.sections
    assert doc2.widgets == doc.widgets
    assert doc2.modals == doc.modals
    assert doc2.actions == doc.actions
    assert doc2.settings == doc.settings


# =============================================================================
# Strategies for Property 1: PageDoc structural completeness
# =============================================================================

# Modal fields — each modal must have Trigger, Fields, and Purpose.
_modal_trigger = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=(" ", "-", "_", '"')),
    min_size=3,
    max_size=40,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)

_modal_field_entry = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=(" ", "-", "_", "(", ")")),
    min_size=2,
    max_size=25,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)

_modal_purpose = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=(" ", "-", "_")),
    min_size=3,
    max_size=50,
).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)


@st.composite
def _modal_entry(draw):
    """Generate a single modal with trigger, fields, and purpose."""
    name = draw(_item_name)
    trigger = draw(_modal_trigger)
    fields = draw(st.lists(_modal_field_entry, min_size=1, max_size=3, unique=True))
    purpose = draw(_modal_purpose)
    return name, trigger, fields, purpose


def _build_modal_section(modal_entries: list[tuple[str, str, list[str], str]]) -> str:
    """Build a Modals & Drawers section with trigger, fields, and purpose per modal."""
    parts: list[str] = []
    for name, trigger, fields, purpose in modal_entries:
        parts.append(f"### {name}")
        parts.append(f"- **Trigger**: {trigger}")
        parts.append(f"- **Fields**: {', '.join(fields)}")
        parts.append(f"- **Purpose**: {purpose}")
        parts.append("")
    return "\n".join(parts).strip()


@st.composite
def complete_page_doc_markdown(draw):
    """Generate a valid Page_Doc markdown string with ALL required sections.

    Required sections per Requirement 1.2:
      - page purpose (intro text)
      - Widgets & Cards
      - Actions
      - Modals & Drawers (each modal has trigger, fields, purpose per Req 1.6)
      - Settings & Knobs
      - Related Pages

    Returns the raw markdown string ready for parsing.
    """
    path = draw(_route_path)
    title = draw(_safe_text)
    group = draw(_group)
    description = draw(_safe_text)

    # Purpose / intro text (required)
    purpose = draw(_safe_text)

    # Widgets (at least 1)
    widgets = draw(_unique_list(_item_name, min_size=1, max_size=4))

    # Modals with full fields (at least 1)
    modal_entries = draw(st.lists(_modal_entry(), min_size=1, max_size=3, unique_by=lambda m: m[0]))

    # Actions (at least 1)
    actions = draw(_unique_list(_item_name, min_size=1, max_size=4))

    # Settings (at least 1)
    settings_items = draw(_unique_list(_item_name, min_size=1, max_size=3))

    # Related pages (at least 1 link)
    related_page_title = draw(_safe_text)

    # Build the markdown
    lines = [
        "---",
        f"path: {path}",
        f"title: {title}",
        f"group: {group}",
        f"description: {description}",
        "---",
        "",
        f"# {title}",
        "",
        purpose,
        "",
        "## Widgets & Cards",
        "",
        _build_section_content(widgets, []),
        "",
        "## Modals & Drawers",
        "",
        _build_modal_section(modal_entries),
        "",
        "## Actions",
        "",
        _build_section_content([], actions),
        "",
        "## Settings & Knobs",
        "",
        _build_section_content([], settings_items),
        "",
        "## Related Pages",
        "",
        f"- [{related_page_title}](/) — Related page",
        "",
    ]
    return "\n".join(lines)


# =============================================================================
# Property 1: PageDoc structural completeness
# =============================================================================


REQUIRED_SECTIONS = {"Widgets & Cards", "Modals & Drawers", "Actions", "Settings & Knobs", "Related Pages"}


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_all_required_sections_present(md: str):
    """Parsing a valid Page_Doc SHALL produce a PageDoc with all required sections.

    Required sections: purpose (intro), Widgets & Cards, Actions,
    Modals & Drawers, Settings & Knobs, Related Pages.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    present = set(doc.sections.keys())
    for section in REQUIRED_SECTIONS:
        assert section in present, f"Missing required section: {section}"


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_purpose_section_present(md: str):
    """Parsing a valid Page_Doc SHALL produce a PageDoc with a purpose (intro) section.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    assert "_intro" in doc.sections, "Missing purpose/intro section"
    assert len(doc.sections["_intro"]) > 0, "Purpose/intro section is empty"


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_widgets_extracted(md: str):
    """Parsing a valid Page_Doc SHALL extract at least one widget name.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    assert len(doc.widgets) >= 1, "No widgets extracted from Widgets & Cards section"


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_modals_extracted(md: str):
    """Parsing a valid Page_Doc SHALL extract at least one modal name.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    assert len(doc.modals) >= 1, "No modals extracted from Modals & Drawers section"


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_actions_extracted(md: str):
    """Parsing a valid Page_Doc SHALL extract at least one action.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    assert len(doc.actions) >= 1, "No actions extracted from Actions section"


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_settings_extracted(md: str):
    """Parsing a valid Page_Doc SHALL extract at least one setting.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    assert len(doc.settings) >= 1, "No settings extracted from Settings & Knobs section"


@given(md=complete_page_doc_markdown())
@settings(max_examples=200, deadline=None)
def test_property_1_modal_entries_have_trigger_fields_purpose(md: str):
    """Every modal entry in a parsed PageDoc SHALL contain trigger, fields, and purpose.

    The Modals & Drawers section text is checked to ensure each ### modal
    heading is followed by Trigger, Fields, and Purpose bullet points.

    **Validates: Requirements 1.2, 1.6**
    """
    doc = DocLoader.parse_markdown(md)
    modals_section = doc.sections.get("Modals & Drawers", "")
    assert modals_section, "Modals & Drawers section is empty"

    # Split by ### headings to get individual modal blocks
    import re
    modal_blocks = re.split(r"^### .+$", modals_section, flags=re.MULTILINE)
    # First element is text before the first ### (should be empty or whitespace)
    modal_blocks = [b.strip() for b in modal_blocks[1:] if b.strip()]

    assert len(modal_blocks) >= 1, "No modal blocks found"

    for i, block in enumerate(modal_blocks):
        assert "**Trigger**" in block, f"Modal block {i} missing Trigger field"
        assert "**Fields**" in block, f"Modal block {i} missing Fields field"
        assert "**Purpose**" in block, f"Modal block {i} missing Purpose field"


# =============================================================================
# Strategies for Properties 3, 4, 5: Page lookup & registry list
# =============================================================================


@st.composite
def page_doc_registry_strategy(draw):
    """Generate a list of unique PageDoc objects suitable for loading into a DocLoader.

    Returns a list of PageDocs with unique paths.
    """
    docs = draw(st.lists(page_doc_strategy(), min_size=1, max_size=8, unique_by=lambda d: d.path))
    return docs


def _build_loaded_loader(docs: list[PageDoc]) -> DocLoader:
    """Create a DocLoader pre-populated with the given PageDoc objects (no filesystem)."""
    loader = DocLoader(docs_dir=None)
    for doc in docs:
        loader._pages[doc.path] = doc
    return loader


# =============================================================================
# Property 3: Page lookup returns correct documentation
# =============================================================================


@given(data=st.data(), docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_3_get_page_returns_matching_doc(data, docs: list[PageDoc]):
    """For any loaded PageDoc and any path present in the registry,
    get_page(path) SHALL return the PageDoc whose path matches.

    **Validates: Requirements 2.2, 5.2**
    """
    loader = _build_loaded_loader(docs)
    # Pick a random path from the loaded set
    target = data.draw(st.sampled_from(docs))
    result = loader.get_page(target.path)
    assert result is not None, f"get_page({target.path!r}) returned None"
    assert result.path == target.path


@given(data=st.data(), docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_3_get_page_returns_correct_title(data, docs: list[PageDoc]):
    """get_page(path) SHALL return a PageDoc with the correct title.

    **Validates: Requirements 2.2, 5.2**
    """
    loader = _build_loaded_loader(docs)
    target = data.draw(st.sampled_from(docs))
    result = loader.get_page(target.path)
    assert result is not None
    assert result.title == target.title


@given(data=st.data(), docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_3_get_page_returns_correct_group(data, docs: list[PageDoc]):
    """get_page(path) SHALL return a PageDoc with the correct group.

    **Validates: Requirements 2.2, 5.2**
    """
    loader = _build_loaded_loader(docs)
    target = data.draw(st.sampled_from(docs))
    result = loader.get_page(target.path)
    assert result is not None
    assert result.group == target.group


@given(data=st.data(), docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_3_get_page_identity(data, docs: list[PageDoc]):
    """get_page(path) SHALL return the exact same PageDoc object that was loaded.

    **Validates: Requirements 2.2, 5.2**
    """
    loader = _build_loaded_loader(docs)
    target = data.draw(st.sampled_from(docs))
    result = loader.get_page(target.path)
    assert result is target, "get_page should return the same object reference"


# =============================================================================
# Property 4: Invalid path returns error with valid paths
# =============================================================================

# Paths that are very unlikely to collide with generated route paths
_invalid_path = st.from_regex(r"/zzz[a-z]{3,10}", fullmatch=True)


@given(docs=page_doc_registry_strategy(), bad_path=_invalid_path)
@settings(max_examples=200, deadline=None)
def test_property_4_invalid_path_returns_none(docs: list[PageDoc], bad_path: str):
    """For any path NOT in the registry, get_page(path) SHALL return None.

    **Validates: Requirements 2.3, 5.3**
    """
    loader = _build_loaded_loader(docs)
    valid_paths = {d.path for d in docs}
    # Ensure bad_path is truly absent
    if bad_path in valid_paths:
        return  # skip this example — extremely unlikely but safe
    result = loader.get_page(bad_path)
    assert result is None, f"get_page({bad_path!r}) should return None for unknown path"


@given(docs=page_doc_registry_strategy(), bad_path=_invalid_path)
@settings(max_examples=200, deadline=None)
def test_property_4_all_paths_lists_valid_paths(docs: list[PageDoc], bad_path: str):
    """When a path is not found, all_paths() SHALL list every loaded path
    so the caller can present valid alternatives.

    **Validates: Requirements 2.3, 5.3**
    """
    loader = _build_loaded_loader(docs)
    valid_paths = {d.path for d in docs}
    if bad_path in valid_paths:
        return
    # Confirm the path is missing
    assert loader.get_page(bad_path) is None
    # all_paths() should contain every loaded path
    listed = set(loader.all_paths())
    assert listed == valid_paths, "all_paths() must list exactly the loaded page paths"


# =============================================================================
# Property 5: Registry list completeness
# =============================================================================


@given(docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_5_list_pages_paths_match(docs: list[PageDoc]):
    """list_pages() SHALL return exactly the same set of paths as the loaded docs.

    **Validates: Requirements 2.6**
    """
    loader = _build_loaded_loader(docs)
    listed = loader.list_pages()
    listed_paths = {entry["path"] for entry in listed}
    expected_paths = {d.path for d in docs}
    assert listed_paths == expected_paths


@given(docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_5_list_pages_titles_match(docs: list[PageDoc]):
    """list_pages() SHALL return the correct title for every loaded page.

    **Validates: Requirements 2.6**
    """
    loader = _build_loaded_loader(docs)
    listed = loader.list_pages()
    listed_map = {entry["path"]: entry["title"] for entry in listed}
    for doc in docs:
        assert doc.path in listed_map, f"Path {doc.path!r} missing from list_pages()"
        assert listed_map[doc.path] == doc.title, f"Title mismatch for {doc.path!r}"


@given(docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_5_list_pages_groups_match(docs: list[PageDoc]):
    """list_pages() SHALL return the correct group for every loaded page.

    **Validates: Requirements 2.6**
    """
    loader = _build_loaded_loader(docs)
    listed = loader.list_pages()
    listed_map = {entry["path"]: entry["group"] for entry in listed}
    for doc in docs:
        assert doc.path in listed_map, f"Path {doc.path!r} missing from list_pages()"
        assert listed_map[doc.path] == doc.group, f"Group mismatch for {doc.path!r}"


@given(docs=page_doc_registry_strategy())
@settings(max_examples=200, deadline=None)
def test_property_5_list_pages_count_matches(docs: list[PageDoc]):
    """list_pages() SHALL return exactly the same number of entries as loaded docs — no more, no less.

    **Validates: Requirements 2.6**
    """
    loader = _build_loaded_loader(docs)
    listed = loader.list_pages()
    assert len(listed) == len(docs), f"Expected {len(docs)} entries, got {len(listed)}"


# =============================================================================
# Property 6: Search returns relevant results case-insensitively
# =============================================================================

from quantgambit.docs.search import DocSearchIndex

# ASCII-only item names for search tests — avoids Unicode case-mapping edge
# cases (e.g. ß → SS) that are outside the real-world domain of dashboard
# widget/modal/action/setting names.
_ascii_item_name = st.text(
    alphabet=st.characters(whitelist_categories=(), whitelist_characters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_&"),
    min_size=2,
    max_size=30,
).map(lambda s: s.strip()).filter(
    lambda s: len(s) >= 2 and not s.startswith("#") and not s.startswith("-")
    # Ensure at least one alphanumeric char so tokenizer produces tokens
    and any(c.isalnum() for c in s)
)

_ascii_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=(), whitelist_characters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_&,.()"),
    min_size=2,
    max_size=40,
).map(lambda s: s.strip()).filter(lambda s: len(s) >= 2 and any(c.isalnum() for c in s))


@st.composite
def _searchable_page_doc(draw):
    """Generate a PageDoc with ASCII-only field values suitable for search testing."""
    path = draw(_route_path)
    title = draw(_ascii_safe_text)
    group = draw(_group)
    description = draw(_ascii_safe_text)

    widgets = draw(st.lists(_ascii_item_name, min_size=0, max_size=4, unique=True))
    modals = draw(st.lists(_ascii_item_name, min_size=0, max_size=3, unique=True))
    actions = draw(st.lists(_ascii_item_name, min_size=0, max_size=4, unique=True))
    settings_list = draw(st.lists(_ascii_item_name, min_size=0, max_size=3, unique=True))

    sections: dict[str, str] = {}
    if widgets:
        sections["Widgets & Cards"] = _build_section_content(widgets, [])
    if modals:
        sections["Modals & Drawers"] = _build_section_content(modals, [])
    if actions:
        sections["Actions"] = _build_section_content([], actions)
    if settings_list:
        sections["Settings & Knobs"] = _build_section_content([], settings_list)

    return PageDoc(
        path=path,
        title=title,
        group=group,
        description=description,
        raw_markdown="",
        sections=sections,
        widgets=widgets,
        modals=modals,
        actions=actions,
        settings=settings_list,
    )


@st.composite
def _searchable_registry(draw):
    """Generate a list of searchable PageDocs with unique paths."""
    return draw(st.lists(_searchable_page_doc(), min_size=1, max_size=8, unique_by=lambda d: d.path))


def _build_search_index(docs: list[PageDoc]) -> DocSearchIndex:
    """Build a DocSearchIndex from a list of PageDocs."""
    index = DocSearchIndex()
    pages = {d.path: d for d in docs}
    index.build(pages)
    return index


def _apply_casing(text: str, casing: str) -> str:
    """Transform *text* to the given casing variant."""
    if casing == "upper":
        return text.upper()
    elif casing == "lower":
        return text.lower()
    elif casing == "title":
        return text.title()
    elif casing == "swapcase":
        return text.swapcase()
    return text


_casing_strategy = st.sampled_from(["upper", "lower", "title", "swapcase", "original"])


@given(data=st.data(), docs=_searchable_registry())
@settings(max_examples=200, deadline=None)
def test_property_6_search_title_case_insensitive(data, docs: list[PageDoc]):
    """Searching for a page title in any casing SHALL return results
    that include the containing page path.

    **Validates: Requirements 3.2, 3.4, 3.5, 5.5**
    """
    index = _build_search_index(docs)
    target = data.draw(st.sampled_from(docs))
    casing = data.draw(_casing_strategy)
    query = _apply_casing(target.title, casing)

    # Only test if the query produces searchable tokens
    if not DocSearchIndex.tokenize(query):
        return

    # Use a large limit to avoid truncation when many pages share the same tokens
    results = index.search(query, limit=200)
    result_paths = {r.path for r in results}
    assert target.path in result_paths, (
        f"Searching for title {query!r} (casing={casing}) did not return page {target.path!r}"
    )


@given(data=st.data(), docs=_searchable_registry())
@settings(max_examples=200, deadline=None)
def test_property_6_search_widget_case_insensitive(data, docs: list[PageDoc]):
    """Searching for a widget name in any casing SHALL return results
    that include the containing page path and the 'Widgets & Cards' section.

    **Validates: Requirements 3.2, 3.4, 3.5, 5.5**
    """
    # Filter to docs that have widgets
    docs_with_widgets = [d for d in docs if d.widgets]
    if not docs_with_widgets:
        return

    index = _build_search_index(docs)
    target = data.draw(st.sampled_from(docs_with_widgets))
    widget = data.draw(st.sampled_from(target.widgets))
    casing = data.draw(_casing_strategy)
    query = _apply_casing(widget, casing)

    if not DocSearchIndex.tokenize(query):
        return

    # Use a large limit to avoid truncation when many pages share the same tokens
    results = index.search(query, limit=200)
    result_paths = {r.path for r in results}
    assert target.path in result_paths, (
        f"Searching for widget {query!r} (casing={casing}) did not return page {target.path!r}"
    )

    # Check that the relevant section heading is present in results for this page
    page_sections = {r.section for r in results if r.path == target.path}
    assert "Widgets & Cards" in page_sections, (
        f"Searching for widget {query!r} did not return 'Widgets & Cards' section for {target.path!r}"
    )


@given(data=st.data(), docs=_searchable_registry())
@settings(max_examples=200, deadline=None)
def test_property_6_search_modal_case_insensitive(data, docs: list[PageDoc]):
    """Searching for a modal name in any casing SHALL return results
    that include the containing page path and the 'Modals & Drawers' section.

    **Validates: Requirements 3.2, 3.4, 3.5, 5.5**
    """
    docs_with_modals = [d for d in docs if d.modals]
    if not docs_with_modals:
        return

    index = _build_search_index(docs)
    target = data.draw(st.sampled_from(docs_with_modals))
    modal = data.draw(st.sampled_from(target.modals))
    casing = data.draw(_casing_strategy)
    query = _apply_casing(modal, casing)

    if not DocSearchIndex.tokenize(query):
        return

    # Use a large limit to avoid truncation when many pages share the same tokens
    results = index.search(query, limit=200)
    result_paths = {r.path for r in results}
    assert target.path in result_paths, (
        f"Searching for modal {query!r} (casing={casing}) did not return page {target.path!r}"
    )

    page_sections = {r.section for r in results if r.path == target.path}
    assert "Modals & Drawers" in page_sections, (
        f"Searching for modal {query!r} did not return 'Modals & Drawers' section for {target.path!r}"
    )


@given(data=st.data(), docs=_searchable_registry())
@settings(max_examples=200, deadline=None)
def test_property_6_search_action_case_insensitive(data, docs: list[PageDoc]):
    """Searching for an action description in any casing SHALL return results
    that include the containing page path and the 'Actions' section.

    **Validates: Requirements 3.2, 3.4, 3.5, 5.5**
    """
    docs_with_actions = [d for d in docs if d.actions]
    if not docs_with_actions:
        return

    index = _build_search_index(docs)
    target = data.draw(st.sampled_from(docs_with_actions))
    action = data.draw(st.sampled_from(target.actions))
    casing = data.draw(_casing_strategy)
    query = _apply_casing(action, casing)

    if not DocSearchIndex.tokenize(query):
        return

    # Use a large limit to avoid truncation when many pages share the same tokens
    results = index.search(query, limit=200)
    result_paths = {r.path for r in results}
    assert target.path in result_paths, (
        f"Searching for action {query!r} (casing={casing}) did not return page {target.path!r}"
    )

    page_sections = {r.section for r in results if r.path == target.path}
    assert "Actions" in page_sections, (
        f"Searching for action {query!r} did not return 'Actions' section for {target.path!r}"
    )


@given(data=st.data(), docs=_searchable_registry())
@settings(max_examples=200, deadline=None)
def test_property_6_search_setting_case_insensitive(data, docs: list[PageDoc]):
    """Searching for a setting name in any casing SHALL return results
    that include the containing page path and the 'Settings & Knobs' section.

    **Validates: Requirements 3.2, 3.4, 3.5, 5.5**
    """
    docs_with_settings = [d for d in docs if d.settings]
    if not docs_with_settings:
        return

    index = _build_search_index(docs)
    target = data.draw(st.sampled_from(docs_with_settings))
    setting = data.draw(st.sampled_from(target.settings))
    casing = data.draw(_casing_strategy)
    query = _apply_casing(setting, casing)

    if not DocSearchIndex.tokenize(query):
        return

    # Use a large limit to avoid truncation when many pages share the same tokens
    results = index.search(query, limit=200)
    result_paths = {r.path for r in results}
    assert target.path in result_paths, (
        f"Searching for setting {query!r} (casing={casing}) did not return page {target.path!r}"
    )

    page_sections = {r.section for r in results if r.path == target.path}
    assert "Settings & Knobs" in page_sections, (
        f"Searching for setting {query!r} did not return 'Settings & Knobs' section for {target.path!r}"
    )


# =============================================================================
# Property 8: System prompt includes current page documentation
# =============================================================================

from quantgambit.copilot.prompt import SystemPromptBuilder
from quantgambit.copilot.tools.registry import ToolRegistry


async def _noop_handler(**kwargs):
    return {}


def _build_prompt_builder_with_docs(docs: list[PageDoc]) -> SystemPromptBuilder:
    """Create a SystemPromptBuilder backed by a DocLoader pre-loaded with *docs*."""
    loader = DocLoader(docs_dir=None)
    for doc in docs:
        loader._pages[doc.path] = doc
    registry = ToolRegistry()
    return SystemPromptBuilder(registry, doc_loader=loader)


class TestProperty8SystemPromptPageContext:
    """
    Feature: platform-documentation-system, Property 8: System prompt includes current page documentation

    For any valid page path passed to SystemPromptBuilder.build(), the
    resulting system prompt string SHALL contain a "Current Page Context"
    section that includes the documentation content for that page.

    **Validates: Requirements 4.3, 5.6**
    """

    @given(data=st.data(), docs=page_doc_registry_strategy())
    @settings(max_examples=200, deadline=None)
    def test_current_page_context_section_present(self, data, docs: list[PageDoc]):
        """build(page_path=...) SHALL include a 'Current Page Context' section.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        target = data.draw(st.sampled_from(docs))
        prompt = builder.build(page_path=target.path)
        assert "## Current Page Context" in prompt, (
            f"System prompt missing 'Current Page Context' section for page {target.path!r}"
        )

    @given(data=st.data(), docs=page_doc_registry_strategy())
    @settings(max_examples=200, deadline=None)
    def test_current_page_context_contains_title(self, data, docs: list[PageDoc]):
        """The 'Current Page Context' section SHALL include the page title.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        target = data.draw(st.sampled_from(docs))
        prompt = builder.build(page_path=target.path)
        assert target.title in prompt, (
            f"System prompt missing page title {target.title!r} for page {target.path!r}"
        )

    @given(data=st.data(), docs=page_doc_registry_strategy())
    @settings(max_examples=200, deadline=None)
    def test_current_page_context_contains_path(self, data, docs: list[PageDoc]):
        """The 'Current Page Context' section SHALL include the page path.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        target = data.draw(st.sampled_from(docs))
        prompt = builder.build(page_path=target.path)
        assert target.path in prompt, (
            f"System prompt missing page path {target.path!r}"
        )

    @given(data=st.data(), docs=page_doc_registry_strategy())
    @settings(max_examples=200, deadline=None)
    def test_current_page_context_contains_description(self, data, docs: list[PageDoc]):
        """The 'Current Page Context' section SHALL include the page description.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        target = data.draw(st.sampled_from(docs))
        prompt = builder.build(page_path=target.path)
        assert target.description in prompt, (
            f"System prompt missing description {target.description!r} for page {target.path!r}"
        )

    @given(data=st.data(), docs=page_doc_registry_strategy())
    @settings(max_examples=200, deadline=None)
    def test_current_page_context_contains_section_content(self, data, docs: list[PageDoc]):
        """The 'Current Page Context' section SHALL include the documentation
        section content for the page.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        target = data.draw(st.sampled_from(docs))
        prompt = builder.build(page_path=target.path)

        # Every non-intro section heading should appear in the prompt
        for heading in target.sections:
            if heading == "_intro":
                # Intro content should be present directly
                assert target.sections["_intro"] in prompt, (
                    f"System prompt missing intro content for page {target.path!r}"
                )
            else:
                assert heading in prompt, (
                    f"System prompt missing section heading {heading!r} for page {target.path!r}"
                )

    @given(docs=page_doc_registry_strategy())
    @settings(max_examples=200, deadline=None)
    def test_no_page_context_without_page_path(self, docs: list[PageDoc]):
        """build() without page_path SHALL NOT include a 'Current Page Context' section.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        prompt = builder.build()
        assert "Current Page Context" not in prompt, (
            "System prompt should not contain 'Current Page Context' when no page_path is given"
        )

    @given(docs=page_doc_registry_strategy(), bad_path=_invalid_path)
    @settings(max_examples=200, deadline=None)
    def test_no_page_context_for_unknown_path(self, docs: list[PageDoc], bad_path: str):
        """build(page_path=...) with an unknown path SHALL NOT include a
        'Current Page Context' section.

        **Validates: Requirements 4.3, 5.6**
        """
        builder = _build_prompt_builder_with_docs(docs)
        valid_paths = {d.path for d in docs}
        if bad_path in valid_paths:
            return  # skip — extremely unlikely but safe
        prompt = builder.build(page_path=bad_path)
        assert "Current Page Context" not in prompt, (
            f"System prompt should not contain 'Current Page Context' for unknown path {bad_path!r}"
        )
