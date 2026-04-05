"""
Property-based tests for Model Abstraction Layer.

Feature: trading-copilot-agent
Tests correctness properties for:
- Property 25: Model provider factory correctness
- Property 26: Tool call format normalization

**Validates: Requirements 13.3, 13.4, 13.5**
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest
from hypothesis import given, settings, strategies as st

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.anthropic import AnthropicProvider
from quantgambit.copilot.providers.azure_openai import AzureOpenAIProvider
from quantgambit.copilot.providers.base import ModelProvider
from quantgambit.copilot.providers.factory import SUPPORTED_PROVIDERS, create_model_provider
from quantgambit.copilot.providers.openai import OpenAIProvider


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Strategy for valid provider names
valid_provider_names = st.sampled_from(list(SUPPORTED_PROVIDERS))

# Strategy for strings that are NOT in the supported provider set.
# We generate arbitrary text and filter out any that happen to match.
invalid_provider_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip().lower() not in SUPPORTED_PROVIDERS)

# Strategy for non-empty tool names
tool_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip())

# Strategy for tool call IDs
tool_call_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)

# Strategy for JSON-serializable tool arguments (simple dicts)
@st.composite
def tool_arguments_strategy(draw):
    """Generate a JSON-serializable dict suitable for tool call arguments."""
    num_keys = draw(st.integers(min_value=0, max_value=5))
    args = {}
    for i in range(num_keys):
        key = f"arg_{i}"
        value = draw(
            st.one_of(
                st.text(min_size=0, max_size=20),
                st.integers(min_value=-1000, max_value=1000),
                st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
                st.booleans(),
            )
        )
        args[key] = value
    return args


# =============================================================================
# Property 25: Model provider factory correctness
# Feature: trading-copilot-agent, Property 25: Model provider factory correctness
#
# For any valid provider name in {"openai", "anthropic", "azure_openai", "local"},
# the factory SHALL return an instance that implements the ModelProvider interface.
# For any string not in the supported set, the factory SHALL raise a ValueError
# listing available providers.
#
# **Validates: Requirements 13.3, 13.5**
# =============================================================================


@settings(max_examples=100)
@given(provider_name=valid_provider_names)
def test_property_25_valid_provider_returns_model_provider_instance(provider_name: str):
    """
    Property 25: Model provider factory correctness — valid providers.

    For any valid provider name, the factory SHALL return an instance
    that implements the ModelProvider interface.

    **Validates: Requirements 13.3**
    """
    env = {
        "COPILOT_LLM_PROVIDER": provider_name,
        "COPILOT_LLM_API_KEY": "test-key-123",
        "COPILOT_LLM_MODEL": "test-model",
        "COPILOT_LLM_BASE_URL": "http://localhost:8000/v1",
        "COPILOT_AZURE_ENDPOINT": "https://test.openai.azure.com",
        "COPILOT_AZURE_API_VERSION": "2024-02-01",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        provider = create_model_provider()

    assert isinstance(provider, ModelProvider)
    assert hasattr(provider, "chat_completion_stream")
    assert callable(provider.chat_completion_stream)


@settings(max_examples=100)
@given(provider_name=valid_provider_names)
def test_property_25_valid_provider_returns_correct_subclass(provider_name: str):
    """
    Property 25: Model provider factory correctness — correct subclass.

    For each valid provider name, the factory SHALL return the expected
    concrete provider class.

    **Validates: Requirements 13.3**
    """
    expected_classes = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "azure_openai": AzureOpenAIProvider,
        "local": OpenAIProvider,
    }

    env = {
        "COPILOT_LLM_PROVIDER": provider_name,
        "COPILOT_LLM_API_KEY": "test-key-123",
        "COPILOT_LLM_MODEL": "test-model",
        "COPILOT_LLM_BASE_URL": "http://localhost:8000/v1",
        "COPILOT_AZURE_ENDPOINT": "https://test.openai.azure.com",
        "COPILOT_AZURE_API_VERSION": "2024-02-01",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        provider = create_model_provider()

    assert isinstance(provider, expected_classes[provider_name])


@settings(max_examples=100)
@given(provider_name=invalid_provider_names)
def test_property_25_invalid_provider_raises_value_error(provider_name: str):
    """
    Property 25: Model provider factory correctness — invalid providers.

    For any string not in the supported set, the factory SHALL raise a
    ValueError listing available providers.

    **Validates: Requirements 13.5**
    """
    env = {
        "COPILOT_LLM_PROVIDER": provider_name,
        "COPILOT_LLM_API_KEY": "test-key-123",
        "COPILOT_LLM_MODEL": "test-model",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="Supported providers"):
            create_model_provider()


@settings(max_examples=100)
@given(provider_name=invalid_provider_names)
def test_property_25_error_message_lists_all_supported_providers(provider_name: str):
    """
    Property 25: Model provider factory correctness — error message completeness.

    The ValueError message SHALL list all supported providers so the user
    knows which values are valid.

    **Validates: Requirements 13.5**
    """
    env = {
        "COPILOT_LLM_PROVIDER": provider_name,
        "COPILOT_LLM_API_KEY": "test-key-123",
        "COPILOT_LLM_MODEL": "test-model",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError) as exc_info:
            create_model_provider()

    error_msg = str(exc_info.value)
    for supported in SUPPORTED_PROVIDERS:
        assert supported in error_msg, (
            f"Error message should list '{supported}' as a supported provider"
        )


# =============================================================================
# Property 26: Tool call format normalization
# Feature: trading-copilot-agent, Property 26: Tool call format normalization
#
# For any LLM provider and any tool call response from that provider, the
# normalized LLMChunk SHALL have a non-empty tool_name and a valid JSON string
# in tool_arguments, regardless of the provider's native format.
#
# **Validates: Requirements 13.4**
# =============================================================================


@st.composite
def openai_tool_call_sse_data(draw):
    """Generate OpenAI-format SSE data for a complete tool call sequence.

    Returns a list of SSE data dicts that, when parsed in order, produce
    a tool_call_start, zero or more tool_call_delta, and a tool_call_end.
    """
    fn_name = draw(tool_names)
    tc_id = draw(tool_call_ids)
    args = draw(tool_arguments_strategy())
    args_json = json.dumps(args)

    # Split the arguments JSON into 1-3 fragments for streaming
    num_fragments = draw(st.integers(min_value=1, max_value=min(3, max(1, len(args_json)))))
    fragments = []
    if num_fragments == 1:
        fragments = [args_json]
    else:
        split_points = sorted(draw(
            st.lists(
                st.integers(min_value=1, max_value=max(1, len(args_json) - 1)),
                min_size=num_fragments - 1,
                max_size=num_fragments - 1,
                unique=True,
            )
        ))
        prev = 0
        for sp in split_points:
            fragments.append(args_json[prev:sp])
            prev = sp
        fragments.append(args_json[prev:])

    sse_events = []

    # First chunk: tool_call_start with function name and first argument fragment
    sse_events.append({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": tc_id,
                    "function": {
                        "name": fn_name,
                        "arguments": fragments[0],
                    },
                }]
            },
            "finish_reason": None,
        }]
    })

    # Subsequent fragments: tool_call_delta
    for frag in fragments[1:]:
        sse_events.append({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {
                            "arguments": frag,
                        },
                    }]
                },
                "finish_reason": None,
            }]
        })

    # Final chunk: finish_reason = "tool_calls"
    sse_events.append({
        "choices": [{
            "delta": {},
            "finish_reason": "tool_calls",
        }]
    })

    return fn_name, args_json, sse_events


@st.composite
def anthropic_tool_call_sse_events(draw):
    """Generate Anthropic-format SSE events for a complete tool call sequence.

    Returns a list of (event_type, data) tuples that, when parsed in order,
    produce a tool_call_start, zero or more tool_call_delta, and a tool_call_end.
    """
    fn_name = draw(tool_names)
    tc_id = draw(tool_call_ids)
    args = draw(tool_arguments_strategy())
    args_json = json.dumps(args)

    # Split the arguments JSON into 1-3 fragments for streaming
    num_fragments = draw(st.integers(min_value=1, max_value=min(3, max(1, len(args_json)))))
    fragments = []
    if num_fragments == 1:
        fragments = [args_json]
    else:
        split_points = sorted(draw(
            st.lists(
                st.integers(min_value=1, max_value=max(1, len(args_json) - 1)),
                min_size=num_fragments - 1,
                max_size=num_fragments - 1,
                unique=True,
            )
        ))
        prev = 0
        for sp in split_points:
            fragments.append(args_json[prev:sp])
            prev = sp
        fragments.append(args_json[prev:])

    events: list[tuple[str, dict]] = []

    # content_block_start with tool_use block
    events.append((
        "content_block_start",
        {
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": tc_id,
                "name": fn_name,
            },
        },
    ))

    # content_block_delta with input_json_delta for each fragment
    for frag in fragments:
        events.append((
            "content_block_delta",
            {
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": frag,
                },
            },
        ))

    # content_block_stop
    events.append((
        "content_block_stop",
        {"index": 0},
    ))

    return fn_name, args_json, events


@settings(max_examples=100)
@given(data=openai_tool_call_sse_data())
def test_property_26_openai_tool_call_normalization(data):
    """
    Property 26: Tool call format normalization — OpenAI provider.

    For any OpenAI tool call SSE response, the normalized tool_call_end
    LLMChunk SHALL have a non-empty tool_name and a valid JSON string
    in tool_arguments.

    **Validates: Requirements 13.4**
    """
    expected_name, expected_args_json, sse_events = data

    active_tool_calls: dict[int, dict] = {}
    all_chunks: list[LLMChunk] = []

    for event_data in sse_events:
        chunks = OpenAIProvider._parse_chunk(event_data, active_tool_calls)
        all_chunks.extend(chunks)

    # Find tool_call_end chunks
    end_chunks = [c for c in all_chunks if c.type == "tool_call_end"]
    assert len(end_chunks) >= 1, "Expected at least one tool_call_end chunk"

    for chunk in end_chunks:
        # Non-empty tool_name
        assert chunk.tool_name is not None
        assert len(chunk.tool_name.strip()) > 0, "tool_name must be non-empty"

        # Valid JSON in tool_arguments
        assert chunk.tool_arguments is not None
        parsed = json.loads(chunk.tool_arguments)  # Raises if invalid JSON
        assert isinstance(parsed, (dict, list, str, int, float, bool, type(None)))

        # Verify the accumulated arguments match the original
        assert chunk.tool_arguments == expected_args_json
        assert chunk.tool_name == expected_name


@settings(max_examples=100)
@given(data=anthropic_tool_call_sse_events())
def test_property_26_anthropic_tool_call_normalization(data):
    """
    Property 26: Tool call format normalization — Anthropic provider.

    For any Anthropic tool call SSE response, the normalized tool_call_end
    LLMChunk SHALL have a non-empty tool_name and a valid JSON string
    in tool_arguments.

    **Validates: Requirements 13.4**
    """
    expected_name, expected_args_json, sse_events = data

    active_blocks: dict[int, dict] = {}
    all_chunks: list[LLMChunk] = []

    for event_type, event_data in sse_events:
        chunks = AnthropicProvider._parse_event(event_type, event_data, active_blocks)
        all_chunks.extend(chunks)

    # Find tool_call_end chunks
    end_chunks = [c for c in all_chunks if c.type == "tool_call_end"]
    assert len(end_chunks) >= 1, "Expected at least one tool_call_end chunk"

    for chunk in end_chunks:
        # Non-empty tool_name
        assert chunk.tool_name is not None
        assert len(chunk.tool_name.strip()) > 0, "tool_name must be non-empty"

        # Valid JSON in tool_arguments
        assert chunk.tool_arguments is not None
        parsed = json.loads(chunk.tool_arguments)  # Raises if invalid JSON
        assert isinstance(parsed, (dict, list, str, int, float, bool, type(None)))

        # Verify the accumulated arguments match the original
        assert chunk.tool_arguments == expected_args_json
        assert chunk.tool_name == expected_name


@settings(max_examples=100)
@given(data=openai_tool_call_sse_data())
def test_property_26_openai_tool_call_start_has_name(data):
    """
    Property 26: Tool call format normalization — OpenAI tool_call_start.

    The tool_call_start chunk SHALL have a non-empty tool_name.

    **Validates: Requirements 13.4**
    """
    expected_name, _, sse_events = data

    active_tool_calls: dict[int, dict] = {}
    all_chunks: list[LLMChunk] = []

    for event_data in sse_events:
        chunks = OpenAIProvider._parse_chunk(event_data, active_tool_calls)
        all_chunks.extend(chunks)

    start_chunks = [c for c in all_chunks if c.type == "tool_call_start"]
    assert len(start_chunks) >= 1, "Expected at least one tool_call_start chunk"

    for chunk in start_chunks:
        assert chunk.tool_name is not None
        assert len(chunk.tool_name.strip()) > 0
        assert chunk.tool_name == expected_name


@settings(max_examples=100)
@given(data=anthropic_tool_call_sse_events())
def test_property_26_anthropic_tool_call_start_has_name(data):
    """
    Property 26: Tool call format normalization — Anthropic tool_call_start.

    The tool_call_start chunk SHALL have a non-empty tool_name.

    **Validates: Requirements 13.4**
    """
    expected_name, _, sse_events = data

    active_blocks: dict[int, dict] = {}
    all_chunks: list[LLMChunk] = []

    for event_type, event_data in sse_events:
        chunks = AnthropicProvider._parse_event(event_type, event_data, active_blocks)
        all_chunks.extend(chunks)

    start_chunks = [c for c in all_chunks if c.type == "tool_call_start"]
    assert len(start_chunks) >= 1, "Expected at least one tool_call_start chunk"

    for chunk in start_chunks:
        assert chunk.tool_name is not None
        assert len(chunk.tool_name.strip()) > 0
        assert chunk.tool_name == expected_name
