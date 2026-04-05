"""Tool registry for the Trading Copilot Agent.

Manages registration, lookup, schema validation, and execution of copilot tools.
"""

from __future__ import annotations

import logging
import time

import jsonschema

from quantgambit.copilot.models import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry of available tools with JSON Schema validation and execution."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition. Overwrites if name already exists."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        """Return the tool definition for *name*, or ``None`` if not found."""
        return self._tools.get(name)

    def list_definitions(self) -> list[dict]:
        """Return tool definitions in LLM function-calling schema format.

        Each entry contains ``name``, ``description``, and ``parameters``
        (the JSON Schema for the tool's parameters).
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            }
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, parameters: dict) -> ToolResult:
        """Validate *parameters* and execute the tool identified by *name*.

        Returns a ``ToolResult`` with ``success=False`` when:
        - the tool is not registered
        - parameters fail JSON Schema validation
        - the handler raises an exception
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                data=None,
                error=f"Tool '{name}' not found",
            )

        # Validate parameters against the tool's JSON Schema.
        try:
            jsonschema.validate(instance=parameters, schema=tool.parameters_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult(
                success=False,
                data=None,
                error=f"Parameter validation failed: {exc.message}",
            )

        # Execute the handler, measuring wall-clock duration.
        start = time.perf_counter()
        try:
            data = await tool.handler(**parameters)
        except Exception as exc:  # noqa: BLE001
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception("Tool '%s' raised an exception", name)
            return ToolResult(
                success=False,
                data=None,
                error=str(exc),
                duration_ms=duration_ms,
            )

        duration_ms = (time.perf_counter() - start) * 1000
        return ToolResult(
            success=True,
            data=data,
            duration_ms=duration_ms,
        )
