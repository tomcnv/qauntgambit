"""Search_Index — full-text search over Page_Doc documentation.

Builds an inverted index from all PageDoc objects and supports
case-insensitive, tokenized search with TF-IDF-like scoring.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from quantgambit.docs.loader import PageDoc

# ---------------------------------------------------------------------------
# Stopwords — common English words excluded from indexing / queries
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
        "this", "that", "not", "no", "so", "if", "do", "has", "had", "have",
        "will", "can", "may", "its", "all", "each", "any", "our", "we", "you",
        "your", "their", "them", "they", "he", "she", "his", "her",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single search hit."""

    path: str
    title: str
    section: str
    snippet: str
    score: float


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------


class DocSearchIndex:
    """Inverted index over PageDoc content for full-text search."""

    # Section-type weights for scoring (higher = more important)
    _WEIGHT_TITLE = 10.0
    _WEIGHT_WIDGET = 5.0
    _WEIGHT_MODAL = 5.0
    _WEIGHT_ACTION = 4.0
    _WEIGHT_SETTING = 4.0
    _WEIGHT_BODY = 1.0

    def __init__(self) -> None:
        # token -> list of (path, section_heading, snippet_text, weight)
        self._index: dict[str, list[tuple[str, str, str, float]]] = {}
        self._pages: dict[str, PageDoc] = {}
        self._doc_count: int = 0

    # -- public API ----------------------------------------------------------

    def build(self, pages: dict[str, PageDoc]) -> None:
        """Build the inverted index from all *pages*."""
        self._index.clear()
        self._pages = dict(pages)
        self._doc_count = len(pages)

        for doc in pages.values():
            # Index the title
            self._index_text(doc.path, "Title", doc.title, self._WEIGHT_TITLE)

            # Index widget names
            for w in doc.widgets:
                self._index_text(doc.path, "Widgets & Cards", w, self._WEIGHT_WIDGET)

            # Index modal names
            for m in doc.modals:
                self._index_text(doc.path, "Modals & Drawers", m, self._WEIGHT_MODAL)

            # Index action descriptions
            for a in doc.actions:
                self._index_text(doc.path, "Actions", a, self._WEIGHT_ACTION)

            # Index setting names
            for s in doc.settings:
                self._index_text(doc.path, "Settings & Knobs", s, self._WEIGHT_SETTING)

            # Index full section text
            for heading, content in doc.sections.items():
                if heading == "_intro":
                    heading_label = "Overview"
                else:
                    heading_label = heading
                self._index_text(doc.path, heading_label, content, self._WEIGHT_BODY)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search the index for *query*, return up to *limit* ranked results."""
        tokens = self.tokenize(query)
        if not tokens:
            return []

        # Accumulate scores per (path, section)
        scores: dict[tuple[str, str], float] = {}
        snippets: dict[tuple[str, str], str] = {}

        for token in tokens:
            entries = self._index.get(token, [])
            # IDF-like factor
            df = len({e[0] for e in entries})  # number of distinct docs with this token
            idf = math.log(1 + self._doc_count / (1 + df)) if self._doc_count > 0 else 1.0

            for path, section, snippet, weight in entries:
                key = (path, section)
                scores[key] = scores.get(key, 0.0) + weight * idf
                # Keep the first snippet we find for this key
                if key not in snippets:
                    snippets[key] = snippet

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        results: list[SearchResult] = []
        for (path, section), score in ranked[:limit]:
            doc = self._pages.get(path)
            title = doc.title if doc else path
            results.append(
                SearchResult(
                    path=path,
                    title=title,
                    section=section,
                    snippet=snippets.get((path, section), ""),
                    score=score,
                )
            )
        return results

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Lowercase, split on non-alphanumeric, remove stopwords."""
        raw_tokens = _TOKEN_RE.findall(text.lower())
        return [t for t in raw_tokens if t not in _STOPWORDS]

    # -- internal helpers ----------------------------------------------------

    def _index_text(self, path: str, section: str, text: str, weight: float) -> None:
        """Add all tokens from *text* to the inverted index."""
        tokens = self.tokenize(text)
        seen: set[str] = set()
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            self._index.setdefault(token, []).append((path, section, text, weight))
