"""API endpoints for the platform documentation system.

Exposes documentation pages and search via REST endpoints.

Requirements: 2.6, 3.2
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from quantgambit.docs.loader import DocLoader
from quantgambit.docs.search import DocSearchIndex


def create_docs_router(
    doc_loader: DocLoader,
    search_index: DocSearchIndex,
) -> APIRouter:
    """Create the documentation API router.

    Args:
        doc_loader: Pre-loaded DocLoader instance.
        search_index: Pre-built DocSearchIndex instance.

    Returns:
        FastAPI router with documentation endpoints.
    """
    router = APIRouter(prefix="/docs", tags=["docs"])

    @router.get("/pages")
    async def list_pages():
        """List all documented pages (path, title, group, description)."""
        return doc_loader.list_pages()

    @router.get("/pages/{path:path}")
    async def get_page(path: str):
        """Get full documentation for a specific page.

        Returns 404 with valid_paths when the page is not documented.
        """
        # Normalise: ensure leading slash
        lookup = path if path.startswith("/") else f"/{path}"
        doc = doc_loader.get_page(lookup)
        if doc is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Page not documented",
                    "valid_paths": doc_loader.all_paths(),
                },
            )
        return {
            "path": doc.path,
            "title": doc.title,
            "group": doc.group,
            "description": doc.description,
            "markdown": doc.raw_markdown,
            "widgets": doc.widgets,
            "modals": doc.modals,
            "actions": doc.actions,
            "settings": doc.settings,
        }

    @router.get("/search")
    async def search_docs(
        q: str = Query("", description="Search query"),
        limit: int = Query(10, ge=1, le=100, description="Max results"),
    ):
        """Search documentation content."""
        if not q.strip():
            return {"results": []}
        results = search_index.search(q, limit=limit)
        return {
            "results": [
                {
                    "path": r.path,
                    "title": r.title,
                    "section": r.section,
                    "snippet": r.snippet,
                    "score": r.score,
                }
                for r in results
            ]
        }

    return router
