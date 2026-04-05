"""
Property-based tests for ToolRegistry.

Feature: trading-copilot-agent
Tests correctness properties for:
- Property 12: Tool registry schema invariant
- Property 13: Tool call parameter validation
- Property 14: Tool call observability events

**Validates: Requirements 8.1, 8.2, 8.5**
"""

from __future__ import annotations

import asyncio

import jsonschema
import pytest
from hypothesis import given, settings, strategies as st

from quantgambit.copilot.models import ToolDefinition, ToolResult
from quantgambit.copilot.tools.registry import ToolRegistry


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Non-empty strings for tool names and descriptions
non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

# Strategy for valid JSON Schema property types
json_schema_types = st.sampled_from(["string", "number", "integer", "boolean"])

# Strategy for generating a valid JSON Schema with 1-5 properties

@st.composite
def json_schema_strategy(draw):
    """Generate a valid JSON Schema object with random properties and required fields."""
    num_props = draw(st.integers(min_value=1, max_value=5))
    properties = {}
    prop_names = []
    for i in range(num_props):
        prop_name = f"prop_{i}"
        prop_names.append(prop_name)
        prop_type = draw(json_schema_types)
        properties[prop_name] = {"type": prop_type}

    # Pick a subset of properties as required
    num_required = draw(st.integers(min_value=0, max_value=num_props))
    required = draw(
        st.lists(
            st.sampled_from(prop_names),
            min_size=num_required,
            max_size=num_required,
            unique=True,
        )
    )

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return schema


@st.composite
def tool_definition_strategy(draw):
    """Generate a ToolDefinition with non-empty name, description, and valid JSON Schema."""
    name = draw(non_empty_text)
    description = draw(non_empty_text)
    schema = draw(json_schema_strategy())

    async def dummy_handler(**kwargs):
        return {"ok": True}

    return ToolDefinition(
        name=name,
        description=description,
        parameters_schema=schema,
        handler=dummy_handler,
    )


# Strategy for generating parameters that violate a given schema
@st.composite
def violating_params_strategy(draw, schema):
    """Generate parameters that violate the given JSON Schema.

    Strategies:
    1. Include a required field with the wrong type
    2. Omit a required field
    3. Include an unknown field (when additionalProperties=False)
    """
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    additional_props = schema.get("additionalProperties", True)

    violation_methods = []

    if required:
        violation_methods.append("wrong_type")
        violation_methods.append("missing_required")
    if not additional_props and properties:
        violation_methods.append("extra_field")

    # Fallback: if no violation methods available, use wrong type on any property
    if not violation_methods:
        if properties:
            violation_methods.append("wrong_type_any")
        else:
            # Schema has no properties — pass an object with an extra field
            return {"__unexpected__": "value"}

    method = draw(st.sampled_from(violation_methods))

    if method == "missing_required":
        # Build valid params but omit one required field
        params = {}
        for pname, pdef in properties.items():
            if pname not in required:
                continue
            params[pname] = _generate_value_for_type(draw, pdef["type"])
        # Remove one required field
        field_to_remove = draw(st.sampled_from(required))
        params.pop(field_to_remove, None)
        return params

    if method in ("wrong_type", "wrong_type_any"):
        # Pick a property and give it the wrong type
        target_fields = required if method == "wrong_type" else list(properties.keys())
        field_name = draw(st.sampled_from(target_fields))
        expected_type = properties[field_name]["type"]
        wrong_value = _generate_wrong_type_value(draw, expected_type)
        # Build otherwise-valid params
        params = {}
        for pname, pdef in properties.items():
            if pname == field_name:
                params[pname] = wrong_value
            else:
                params[pname] = _generate_value_for_type(draw, pdef["type"])
        return params

    if method == "extra_field":
        # Build valid params plus an extra unknown field
        params = {}
        for pname, pdef in properties.items():
            params[pname] = _generate_value_for_type(draw, pdef["type"])
        params["__unknown_extra_field__"] = "unexpected"
        return params

    return {"__fallback__": "invalid"}


def _generate_value_for_type(draw, json_type: str):
    """Generate a valid value for a JSON Schema type."""
    if json_type == "string":
        return draw(st.text(min_size=0, max_size=20))
    elif json_type == "number":
        return draw(st.floats(allow_nan=False, allow_infinity=False))
    elif json_type == "integer":
        return draw(st.integers(min_value=-1000, max_value=1000))
    elif json_type == "boolean":
        return draw(st.booleans())
    return draw(st.text(min_size=1, max_size=10))


def _generate_wrong_type_value(draw, expected_type: str):
    """Generate a value that does NOT match the expected JSON Schema type."""
    # Map each type to a strategy that produces a different type
    wrong_generators = {
        "string": st.integers(min_value=-100, max_value=100),
        "number": st.text(min_size=1, max_size=10),
        "integer": st.text(min_size=1, max_size=10),
        "boolean": st.text(min_size=1, max_size=10),
    }
    return draw(wrong_generators.get(expected_type, st.integers()))


# =============================================================================
# Property 12: Tool registry schema invariant
# Feature: trading-copilot-agent, Property 12: Tool registry schema invariant
#
# For any tool registered in the ToolRegistry, the tool definition SHALL have
# a non-empty name, a non-empty description, and a valid JSON Schema for its
# parameters.
#
# **Validates: Requirements 8.1**
# =============================================================================


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
def test_property_12_registered_tool_has_non_empty_name(tool_def: ToolDefinition):
    """
    Property 12: Tool registry schema invariant — name is non-empty.

    After registering a tool, retrieving it should yield a definition
    whose name is a non-empty string.

    **Validates: Requirements 8.1**
    """
    registry = ToolRegistry()
    registry.register(tool_def)

    retrieved = registry.get(tool_def.name)
    assert retrieved is not None
    assert isinstance(retrieved.name, str)
    assert len(retrieved.name.strip()) > 0


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
def test_property_12_registered_tool_has_non_empty_description(tool_def: ToolDefinition):
    """
    Property 12: Tool registry schema invariant — description is non-empty.

    After registering a tool, retrieving it should yield a definition
    whose description is a non-empty string.

    **Validates: Requirements 8.1**
    """
    registry = ToolRegistry()
    registry.register(tool_def)

    retrieved = registry.get(tool_def.name)
    assert retrieved is not None
    assert isinstance(retrieved.description, str)
    assert len(retrieved.description.strip()) > 0


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
def test_property_12_registered_tool_has_valid_json_schema(tool_def: ToolDefinition):
    """
    Property 12: Tool registry schema invariant — parameters_schema is valid JSON Schema.

    After registering a tool, the parameters_schema should be a valid
    JSON Schema (validatable by jsonschema.Draft7Validator).

    **Validates: Requirements 8.1**
    """
    registry = ToolRegistry()
    registry.register(tool_def)

    retrieved = registry.get(tool_def.name)
    assert retrieved is not None
    # Validate that the schema itself is a valid JSON Schema
    jsonschema.Draft7Validator.check_schema(retrieved.parameters_schema)


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
def test_property_12_list_definitions_contains_registered_tool(tool_def: ToolDefinition):
    """
    Property 12: Tool registry schema invariant — list_definitions includes registered tools.

    The list_definitions output should contain an entry for every registered
    tool with non-empty name, non-empty description, and a valid schema.

    **Validates: Requirements 8.1**
    """
    registry = ToolRegistry()
    registry.register(tool_def)

    definitions = registry.list_definitions()
    assert len(definitions) >= 1

    matching = [d for d in definitions if d["name"] == tool_def.name]
    assert len(matching) == 1

    entry = matching[0]
    assert isinstance(entry["name"], str) and len(entry["name"].strip()) > 0
    assert isinstance(entry["description"], str) and len(entry["description"].strip()) > 0
    jsonschema.Draft7Validator.check_schema(entry["parameters"])


# =============================================================================
# Property 13: Tool call parameter validation
# Feature: trading-copilot-agent, Property 13: Tool call parameter validation
#
# For any tool call with parameters that do not conform to the tool's parameter
# schema, the ToolRegistry.execute method SHALL reject the call and return a
# ToolResult with success=False.
#
# **Validates: Requirements 8.2**
# =============================================================================


# We need a fixed schema for the violating_params_strategy since @st.composite
# strategies with arguments require special handling. We'll use a set of
# representative schemas and generate violations for each.

_REPRESENTATIVE_SCHEMAS = [
    {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["symbol"],
        "additionalProperties": False,
    },
    {
        "type": "object",
        "properties": {
            "start_time": {"type": "number"},
            "end_time": {"type": "number"},
            "active": {"type": "boolean"},
        },
        "required": ["start_time", "end_time"],
        "additionalProperties": False,
    },
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "enabled": {"type": "boolean"},
        },
        "required": ["name", "count", "enabled"],
        "additionalProperties": False,
    },
]


@st.composite
def schema_and_violation_strategy(draw):
    """Draw a representative schema and generate violating parameters for it."""
    schema = draw(st.sampled_from(_REPRESENTATIVE_SCHEMAS))
    bad_params = draw(violating_params_strategy(schema))
    return schema, bad_params


@settings(max_examples=100)
@given(data=schema_and_violation_strategy())
@pytest.mark.asyncio
async def test_property_13_invalid_params_return_failure(data):
    """
    Property 13: Tool call parameter validation.

    For any tool call with parameters that do not conform to the tool's
    parameter schema, execute() SHALL return ToolResult(success=False).

    **Validates: Requirements 8.2**
    """
    schema, bad_params = data

    async def dummy_handler(**kwargs):
        return {"ok": True}

    tool = ToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters_schema=schema,
        handler=dummy_handler,
    )

    registry = ToolRegistry()
    registry.register(tool)

    # Verify the params actually violate the schema (sanity check)
    try:
        jsonschema.validate(instance=bad_params, schema=schema)
        # If validation passes, the params are actually valid — skip this case
        pytest.skip("Generated params happened to be valid; skipping")
    except jsonschema.ValidationError:
        pass

    result = await registry.execute("test_tool", bad_params)

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.error is not None


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
@pytest.mark.asyncio
async def test_property_13_unknown_tool_returns_failure(tool_def: ToolDefinition):
    """
    Property 13: Tool call parameter validation — unknown tool name.

    Calling execute() with a tool name that is not registered SHALL return
    ToolResult(success=False).

    **Validates: Requirements 8.2**
    """
    registry = ToolRegistry()
    registry.register(tool_def)

    result = await registry.execute("nonexistent_tool_name", {})

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.error is not None


# =============================================================================
# Property 14: Tool call observability events
# Feature: trading-copilot-agent, Property 14: Tool call observability events
#
# For any tool execution (successful or failed), the returned ToolResult SHALL
# contain a non-negative duration_ms and a boolean success field.
#
# **Validates: Requirements 8.5**
# =============================================================================


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
@pytest.mark.asyncio
async def test_property_14_successful_execution_has_observability_fields(
    tool_def: ToolDefinition,
):
    """
    Property 14: Tool call observability events — successful execution.

    For a successful tool execution, the ToolResult SHALL have
    success=True (boolean), and duration_ms >= 0.

    **Validates: Requirements 8.5**
    """
    registry = ToolRegistry()
    registry.register(tool_def)

    # Build valid parameters for the tool
    valid_params = _build_valid_params(tool_def.parameters_schema)

    result = await registry.execute(tool_def.name, valid_params)

    assert isinstance(result, ToolResult)
    assert isinstance(result.success, bool)
    assert result.success is True
    assert isinstance(result.duration_ms, float)
    assert result.duration_ms >= 0.0


@settings(max_examples=100)
@given(tool_def=tool_definition_strategy())
@pytest.mark.asyncio
async def test_property_14_failed_handler_has_observability_fields(
    tool_def: ToolDefinition,
):
    """
    Property 14: Tool call observability events — failed handler.

    When a tool handler raises an exception, the ToolResult SHALL have
    success=False (boolean), and duration_ms >= 0.

    **Validates: Requirements 8.5**
    """
    async def failing_handler(**kwargs):
        raise RuntimeError("Simulated tool failure")

    failing_tool = ToolDefinition(
        name=tool_def.name,
        description=tool_def.description,
        parameters_schema=tool_def.parameters_schema,
        handler=failing_handler,
    )

    registry = ToolRegistry()
    registry.register(failing_tool)

    valid_params = _build_valid_params(failing_tool.parameters_schema)

    result = await registry.execute(failing_tool.name, valid_params)

    assert isinstance(result, ToolResult)
    assert isinstance(result.success, bool)
    assert result.success is False
    assert isinstance(result.duration_ms, float)
    assert result.duration_ms >= 0.0
    assert result.error is not None


@settings(max_examples=100)
@given(data=schema_and_violation_strategy())
@pytest.mark.asyncio
async def test_property_14_validation_failure_has_observability_fields(data):
    """
    Property 14: Tool call observability events — validation failure.

    When parameter validation fails, the ToolResult SHALL have
    success=False (boolean) and duration_ms >= 0.

    **Validates: Requirements 8.5**
    """
    schema, bad_params = data

    async def dummy_handler(**kwargs):
        return {"ok": True}

    tool = ToolDefinition(
        name="obs_test_tool",
        description="Observability test tool",
        parameters_schema=schema,
        handler=dummy_handler,
    )

    registry = ToolRegistry()
    registry.register(tool)

    # Verify the params actually violate the schema
    try:
        jsonschema.validate(instance=bad_params, schema=schema)
        pytest.skip("Generated params happened to be valid; skipping")
    except jsonschema.ValidationError:
        pass

    result = await registry.execute("obs_test_tool", bad_params)

    assert isinstance(result, ToolResult)
    assert isinstance(result.success, bool)
    assert result.success is False
    assert isinstance(result.duration_ms, float)
    assert result.duration_ms >= 0.0


def _build_valid_params(schema: dict) -> dict:
    """Build a minimal set of valid parameters for a JSON Schema."""
    params = {}
    properties = schema.get("properties", {})
    for pname, pdef in properties.items():
        ptype = pdef.get("type", "string")
        if ptype == "string":
            params[pname] = "test_value"
        elif ptype == "number":
            params[pname] = 1.0
        elif ptype == "integer":
            params[pname] = 1
        elif ptype == "boolean":
            params[pname] = True
        else:
            params[pname] = "fallback"
    return params
