"""Copilot tools: settings mutation.

Wraps :class:`SettingsMutationManager` methods as copilot tools so the LLM
can propose, apply, list, and revert settings changes during a conversation.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from quantgambit.copilot.models import SettingsMutation, SettingsSnapshot, ToolDefinition
from quantgambit.copilot.settings_mutation import SettingsMutationManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schemas exposed to the LLM
# ---------------------------------------------------------------------------

PROPOSE_SETTINGS_MUTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "object",
            "description": (
                "Proposed setting changes. Each key is a setting path and "
                "the value is an object with 'old' and 'new' fields."
            ),
        },
        "rationale": {
            "type": "string",
            "description": "Explanation of why these changes are recommended.",
        },
    },
    "required": ["changes", "rationale"],
    "additionalProperties": False,
}

APPLY_SETTINGS_MUTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mutation_id": {
            "type": "string",
            "description": "The ID of the proposed mutation to apply.",
        },
    },
    "required": ["mutation_id"],
    "additionalProperties": False,
}

LIST_SETTINGS_SNAPSHOTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

REVERT_SETTINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "snapshot_id": {
            "type": "string",
            "description": "The ID of the settings snapshot to revert to.",
        },
    },
    "required": ["snapshot_id"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _mutation_to_dict(mutation: SettingsMutation) -> dict[str, Any]:
    """Convert a :class:`SettingsMutation` dataclass to a JSON-serialisable dict."""
    return dataclasses.asdict(mutation)


def _snapshot_to_dict(snapshot: SettingsSnapshot) -> dict[str, Any]:
    """Convert a :class:`SettingsSnapshot` dataclass to a JSON-serialisable dict."""
    return dataclasses.asdict(snapshot)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_settings_tools(
    mutation_manager: SettingsMutationManager,
    user_id: str,
    conversation_id: str,
) -> list[ToolDefinition]:
    """Return :class:`ToolDefinition` instances for all settings mutation tools.

    Parameters
    ----------
    mutation_manager:
        The :class:`SettingsMutationManager` that backs every tool handler.
    user_id:
        User identity bound at registration time.
    conversation_id:
        Conversation identity bound at registration time.
    """

    # -- propose_settings_mutation ------------------------------------------

    async def _propose_handler(
        *, changes: dict, rationale: str, **_: Any
    ) -> dict[str, Any]:
        mutation = await mutation_manager.propose_mutation(
            user_id=user_id,
            conversation_id=conversation_id,
            changes=changes,
            rationale=rationale,
        )
        violations = await mutation_manager.validate_mutation(changes)
        result = _mutation_to_dict(mutation)
        result["constraint_violations"] = violations
        return result

    propose_tool = ToolDefinition(
        name="propose_settings_mutation",
        description=(
            "Propose changes to user account settings (risk parameters, "
            "strategy config, execution policy). Returns the proposed "
            "mutation with any constraint violations. The user must approve "
            "before changes are applied."
        ),
        parameters_schema=PROPOSE_SETTINGS_MUTATION_SCHEMA,
        handler=_propose_handler,
    )

    # -- apply_settings_mutation --------------------------------------------

    async def _apply_handler(*, mutation_id: str, **_: Any) -> dict[str, Any]:
        snapshot = await mutation_manager.apply_mutation(
            mutation_id=mutation_id,
            user_id=user_id,
        )
        return _snapshot_to_dict(snapshot)

    apply_tool = ToolDefinition(
        name="apply_settings_mutation",
        description=(
            "Apply a previously proposed settings mutation after user "
            "approval. Creates a snapshot of the current settings before "
            "applying changes. Returns the created snapshot."
        ),
        parameters_schema=APPLY_SETTINGS_MUTATION_SCHEMA,
        handler=_apply_handler,
    )

    # -- list_settings_snapshots --------------------------------------------

    async def _list_handler(**_: Any) -> list[dict[str, Any]]:
        snapshots = await mutation_manager.list_snapshots(user_id=user_id)
        return [_snapshot_to_dict(s) for s in snapshots]

    list_tool = ToolDefinition(
        name="list_settings_snapshots",
        description=(
            "List versioned settings snapshots for the current user, "
            "ordered by version descending. Useful for reviewing change "
            "history and selecting a snapshot to revert to."
        ),
        parameters_schema=LIST_SETTINGS_SNAPSHOTS_SCHEMA,
        handler=_list_handler,
    )

    # -- revert_settings ----------------------------------------------------

    async def _revert_handler(*, snapshot_id: str, **_: Any) -> dict[str, Any]:
        snapshot = await mutation_manager.revert_to_snapshot(
            snapshot_id=snapshot_id,
            user_id=user_id,
        )
        return _snapshot_to_dict(snapshot)

    revert_tool = ToolDefinition(
        name="revert_settings",
        description=(
            "Revert user settings to a previous snapshot version. "
            "Creates a new snapshot recording the revert and restores "
            "the settings from the selected snapshot."
        ),
        parameters_schema=REVERT_SETTINGS_SCHEMA,
        handler=_revert_handler,
    )

    return [propose_tool, apply_tool, list_tool, revert_tool]
