"""Copilot tool: get_page_docs.

Returns the full Page_Doc documentation for a given dashboard page path.
"""

from __future__ import annotations

import logging
from typing import Any

from quantgambit.copilot.models import ToolDefinition
from quantgambit.docs.loader import DocLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

GET_PAGE_DOCS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_path": {
            "type": "string",
            "description": "Dashboard page route path (e.g. '/live', '/orders').",
        },
    },
    "required": ["page_path"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _get_page_docs_handler(
    *,
    doc_loader: DocLoader,
    page_path: str,
) -> dict[str, Any]:
    """Return documentation for *page_path*, or error with valid paths."""
    doc = doc_loader.get_page(page_path)
    if doc is None:
        return {
            "success": False,
            "error": f"No documentation found for path: {page_path}",
            "valid_paths": doc_loader.all_paths(),
        }
    return {
        "success": True,
        "path": doc.path,
        "title": doc.title,
        "group": doc.group,
        "description": doc.description,
        "content": doc.raw_markdown,
        "widgets": doc.widgets,
        "modals": doc.modals,
        "actions": doc.actions,
        "settings": doc.settings,
    }


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_get_page_docs_tool(doc_loader: DocLoader) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``get_page_docs`` bound to *doc_loader*."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _get_page_docs_handler(doc_loader=doc_loader, **kwargs)

    return ToolDefinition(
        name="get_page_docs",
        description=(
            "Get the full documentation for a dashboard page. "
            "Returns page purpose, widgets, cards, modals, actions, "
            "settings, and related pages. Use the page_path parameter "
            "with a route like '/live' or '/orders'."
        ),
        parameters_schema=GET_PAGE_DOCS_SCHEMA,
        handler=handler,
    )
