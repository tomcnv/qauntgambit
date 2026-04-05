"""Copilot tool: search_docs.

Searches across all page documentation and returns matching snippets
with page paths and section headings.
"""

from __future__ import annotations

import logging
from typing import Any

from quantgambit.copilot.models import ToolDefinition
from quantgambit.docs.search import DocSearchIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

SEARCH_DOCS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query to find relevant documentation.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results to return (default 5).",
            "default": 5,
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _search_docs_handler(
    *,
    search_index: DocSearchIndex,
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Search documentation for *query*, return up to *limit* results."""
    results = search_index.search(query, limit=limit)
    return {
        "success": True,
        "query": query,
        "results": [
            {
                "path": r.path,
                "title": r.title,
                "section": r.section,
                "snippet": r.snippet,
                "score": r.score,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_search_docs_tool(search_index: DocSearchIndex) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``search_docs`` bound to *search_index*."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _search_docs_handler(search_index=search_index, **kwargs)

    return ToolDefinition(
        name="search_docs",
        description=(
            "Search across all dashboard page documentation. "
            "Returns matching snippets with page paths and section headings. "
            "Use to find information about specific features, widgets, or settings."
        ),
        parameters_schema=SEARCH_DOCS_SCHEMA,
        handler=handler,
    )
