"""Doc_Loader — parse, index, and serve Page_Doc markdown files.

Implements the Documentation_Registry described in the platform-documentation-system spec.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PageDoc:
    """Structured representation of a single Page_Doc markdown file."""

    path: str  # route path, e.g. "/live"
    title: str  # human-readable page title
    group: str  # nav group: Trading, Risk, Analysis, Research, System
    description: str  # one-line description
    raw_markdown: str = ""  # full original markdown
    sections: dict[str, str] = field(default_factory=dict)  # heading -> body
    widgets: list[str] = field(default_factory=list)  # widget/card names
    modals: list[str] = field(default_factory=list)  # modal/drawer names
    actions: list[str] = field(default_factory=list)  # available actions
    settings: list[str] = field(default_factory=list)  # settings/knobs


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FM_FIELD_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, remaining body) from *text*.

    Raises ``ValueError`` if the frontmatter block is missing or lacks
    required fields.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("Missing YAML frontmatter block")
    fm_block = m.group(1)
    body = text[m.end():]
    fields = {k: v.strip() for k, v in _FM_FIELD_RE.findall(fm_block)}
    for key in ("path", "title", "group", "description"):
        if key not in fields:
            raise ValueError(f"Frontmatter missing required field: {key}")
    return fields, body


def _render_frontmatter(doc: PageDoc) -> str:
    """Render the YAML frontmatter block for *doc*."""
    lines = [
        "---",
        f"path: {doc.path}",
        f"title: {doc.title}",
        f"group: {doc.group}",
        f"description: {doc.description}",
        "---",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section parsing helpers
# ---------------------------------------------------------------------------

_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_H3_RE = re.compile(r"^### (.+)$", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^- (.+)$", re.MULTILINE)


def _split_h2_sections(body: str) -> dict[str, str]:
    """Split *body* into ``{heading: content}`` by ``## `` headings."""
    parts = _H2_RE.split(body)
    # parts[0] is text before the first ## heading (intro text)
    sections: dict[str, str] = {}
    # If there's intro text before any ## heading, capture it
    intro = parts[0].strip()
    if intro:
        sections["_intro"] = intro
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[heading] = content
    return sections


def _extract_h3_names(section_text: str) -> list[str]:
    """Return all ``### Name`` headings from *section_text*."""
    return [m.strip() for m in _H3_RE.findall(section_text)]


def _extract_list_items(section_text: str) -> list[str]:
    """Return all top-level ``- item`` entries from *section_text*."""
    return [m.strip() for m in _LIST_ITEM_RE.findall(section_text)]


# ---------------------------------------------------------------------------
# Core parse / print
# ---------------------------------------------------------------------------

class DocLoader:
    """Load, index, and serve Page_Doc markdown files."""

    def __init__(self, docs_dir: Path | None = None):
        self._docs_dir = docs_dir
        self._pages: dict[str, PageDoc] = {}

    # -- bulk operations -----------------------------------------------------

    def load_all(self) -> None:
        """Parse all ``.md`` files in *docs_dir* into PageDoc objects."""
        if self._docs_dir is None or not self._docs_dir.exists():
            logger.warning("Docs directory %s does not exist — no docs loaded", self._docs_dir)
            return
        for md_file in sorted(self._docs_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                doc = self.parse_markdown(content)
                if doc.path in self._pages:
                    logger.warning("Duplicate page path %s in %s — overwriting", doc.path, md_file.name)
                self._pages[doc.path] = doc
            except Exception:
                logger.exception("Failed to parse %s — skipping", md_file.name)

    def get_page(self, path: str) -> PageDoc | None:
        """Return the PageDoc for *path*, or ``None``."""
        return self._pages.get(path)

    def list_pages(self) -> list[dict]:
        """Return ``[{path, title, group, description}, ...]`` for every loaded page."""
        return [
            {"path": d.path, "title": d.title, "group": d.group, "description": d.description}
            for d in self._pages.values()
        ]

    def all_paths(self) -> list[str]:
        """Return sorted list of all loaded page paths."""
        return sorted(self._pages.keys())

    # -- static helpers ------------------------------------------------------

    @staticmethod
    def parse_markdown(content: str) -> PageDoc:
        """Parse a single markdown string into a :class:`PageDoc`."""
        fm, body = _parse_frontmatter(content)

        # Strip the H1 title line (e.g. "# Live Trading") from the body
        # so it doesn't end up in _intro (to_markdown re-emits it from doc.title).
        body = re.sub(r"^# .+\n*", "", body.lstrip())

        sections = _split_h2_sections(body)

        # Extract structured lists from well-known sections
        widgets = _extract_h3_names(sections.get("Widgets & Cards", ""))
        modals = _extract_h3_names(sections.get("Modals & Drawers", ""))
        actions = _extract_list_items(sections.get("Actions", ""))
        settings = _extract_list_items(sections.get("Settings & Knobs", ""))

        return PageDoc(
            path=fm["path"],
            title=fm["title"],
            group=fm["group"],
            description=fm["description"],
            raw_markdown=content,
            sections=sections,
            widgets=widgets,
            modals=modals,
            actions=actions,
            settings=settings,
        )

    @staticmethod
    def to_markdown(doc: PageDoc) -> str:
        """Pretty-print a :class:`PageDoc` back to valid markdown."""
        parts: list[str] = []

        # Frontmatter
        parts.append(_render_frontmatter(doc))
        parts.append("")  # blank line after frontmatter

        # Title
        parts.append(f"# {doc.title}")
        parts.append("")

        # Sections — render in a deterministic order.
        # First the intro (if any), then well-known sections, then any extras.
        well_known_order = [
            "Widgets & Cards",
            "Modals & Drawers",
            "Actions",
            "Settings & Knobs",
            "Related Pages",
        ]

        # Intro text (stored under "_intro" key)
        intro = doc.sections.get("_intro", "")
        if intro:
            parts.append(intro)
            parts.append("")

        rendered: set[str] = {"_intro"}

        for heading in well_known_order:
            if heading in doc.sections:
                parts.append(f"## {heading}")
                parts.append("")
                parts.append(doc.sections[heading])
                parts.append("")
                rendered.add(heading)

        # Any remaining custom sections
        for heading, content in doc.sections.items():
            if heading not in rendered:
                parts.append(f"## {heading}")
                parts.append("")
                parts.append(content)
                parts.append("")
                rendered.add(heading)

        return "\n".join(parts).rstrip("\n") + "\n"
