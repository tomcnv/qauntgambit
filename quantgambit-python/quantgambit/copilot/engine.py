"""AgentEngine — core ReAct loop for the Trading Copilot.

Orchestrates: system prompt building → LLM streaming → tool execution →
event yielding → conversation persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from quantgambit.copilot.conversation import ConversationManager
from quantgambit.copilot.models import (
    ChartDataEvent,
    DoneEvent,
    ErrorEvent,
    Message,
    SettingsMutationProposal,
    TextDelta,
    ToolCallRecord,
    ToolCallResult,
    ToolCallStart,
    TradeContext,
)
from quantgambit.copilot.prompt import SystemPromptBuilder
from quantgambit.copilot.providers.base import ModelProvider
from quantgambit.copilot.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_TURN = 5
MAX_REACT_ITERATIONS = 15

# Patterns that indicate the LLM hallucinated tool calls as text instead
# of using the proper tool_calls API.  DeepSeek sometimes outputs XML-like
# markup (e.g. <｜DSML｜function_calls>) or Markdown-style fenced blocks
# that mimic tool invocations.
_HALLUCINATED_TOOL_CALL_PATTERNS = [
    re.compile(r"<[^>]*function_calls?[^>]*>", re.IGNORECASE),
    re.compile(r"<[^>]*invoke\s+name=", re.IGNORECASE),
    re.compile(r"<[^>]*tool_call[^>]*>", re.IGNORECASE),
    re.compile(r"```(?:xml|tool_call)", re.IGNORECASE),
]


def _contains_hallucinated_tool_calls(text: str) -> bool:
    """Return True if *text* contains patterns that look like hallucinated tool calls."""
    return any(pat.search(text) for pat in _HALLUCINATED_TOOL_CALL_PATTERNS)


def _strip_hallucinated_tool_calls(text: str) -> str:
    """Remove hallucinated tool-call markup from *text*.

    Strips XML-like blocks (``<…function_calls…>…</…>``) and any trailing
    whitespace so the user sees only the real prose the LLM produced before
    it started hallucinating.
    """
    # Remove XML-style blocks like <｜DSML｜function_calls>…</｜DSML｜function_calls>
    cleaned = re.sub(
        r"<[^>]*function_calls?[^>]*>.*?</[^>]*function_calls?[^>]*>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove any remaining opening/closing tags for invoke, tool_call, etc.
    cleaned = re.sub(
        r"<[^>]*(?:invoke|tool_call|function_calls?)[^>]*/?>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.rstrip()


def _sanitize_tool_call_history(messages: list[dict]) -> list[dict]:
    """Remove assistant messages with tool_calls that lack matching tool results.

    DeepSeek (and OpenAI) require that every assistant message containing
    ``tool_calls`` is immediately followed by ``tool`` role messages for
    each ``tool_call_id``.  Old/corrupted conversations may violate this.
    This function strips those orphaned assistant+tool messages so the
    provider doesn't reject the request with a 400.
    """
    sanitized: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Collect expected tool_call_ids
            expected_ids = {
                tc.get("id") or tc.get("function", {}).get("name", "")
                for tc in msg["tool_calls"]
            }
            # Look ahead for matching tool messages
            j = i + 1
            found_ids: set[str] = set()
            tool_msgs: list[dict] = []
            while j < len(messages) and messages[j].get("role") == "tool":
                tcid = messages[j].get("tool_call_id", "")
                found_ids.add(tcid)
                tool_msgs.append(messages[j])
                j += 1
            if expected_ids and not expected_ids.issubset(found_ids):
                # Missing tool results — skip this assistant msg and its tool msgs
                logger.warning(
                    "Dropping assistant message with orphaned tool_calls "
                    "(expected %s, found %s)",
                    expected_ids,
                    found_ids,
                )
                i = j
                continue
            # Valid sequence — keep them all
            sanitized.append(msg)
            sanitized.extend(tool_msgs)
            i = j
        else:
            sanitized.append(msg)
            i += 1
    return sanitized


class AgentEngine:
    """Core orchestration class that manages the ReAct loop.

    Accepts a user message, streams LLM responses, executes tool calls,
    and yields ``AgentEvent`` objects for the caller to forward via SSE.
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        tool_registry: ToolRegistry,
        conversation_manager: ConversationManager,
        system_prompt_builder: SystemPromptBuilder,
    ) -> None:
        self._model = model_provider
        self._tools = tool_registry
        self._conversation = conversation_manager
        self._prompt_builder = system_prompt_builder

    async def run(
        self,
        user_message: str,
        conversation_id: str,
        user_claims: dict[str, Any] | None = None,
        trade_context: TradeContext | None = None,
        page_path: str | None = None,
    ) -> AsyncIterator:
        """Execute the agent loop. Yields AgentEvent objects.

        When *trade_context* is provided the engine injects trade data into
        the system prompt and pre-fetches the decision trace if a
        ``decision_trace_id`` is present.

        When *page_path* is provided the engine passes it to the system
        prompt builder so the current page documentation is included.
        """
        user_claims = user_claims or {}
        user_id = user_claims.get("user_id", "unknown")

        # 1. Build system prompt (with optional trade context and page context)
        system_prompt = self._prompt_builder.build(trade_context=trade_context, page_path=page_path)

        # 2. Persist the user message
        user_msg = Message(role="user", content=user_message)
        await self._conversation.append_message(conversation_id, user_msg)

        # 3. Get conversation history (truncated to fit context window)
        history = await self._conversation.truncate_to_fit(
            conversation_id, max_tokens=12_000
        )

        # 4. Build messages list for the LLM
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.parameters),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(entry)

        # 4b. Sanitize message history — remove assistant messages with
        # tool_calls that lack corresponding tool result messages.  This
        # prevents 400 errors from providers that enforce strict ordering.
        messages = _sanitize_tool_call_history(messages)

        # 5. Pre-fetch decision trace if trade context has a trace id
        if trade_context and trade_context.decision_trace_id:
            async for event in self._prefetch_decision_trace(
                trade_context.decision_trace_id, messages
            ):
                yield event

        # 6. Tool definitions for the LLM
        tool_defs = self._tools.list_definitions()
        tools_for_llm = (
            [
                {
                    "type": "function",
                    "function": {
                        "name": td["name"],
                        "description": td["description"],
                        "parameters": td["parameters"],
                    },
                }
                for td in tool_defs
            ]
            if tool_defs
            else None
        )

        # 7. ReAct loop
        tool_call_count = 0
        try:
            async for event in self._react_loop(
                messages, tools_for_llm, tool_call_count, conversation_id, user_id
            ):
                yield event
        except Exception as exc:
            logger.exception("AgentEngine error for user=%s", user_id)
            yield ErrorEvent(message=str(exc))
        finally:
            # Always emit DoneEvent so the frontend never gets stuck
            yield DoneEvent()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _react_loop(
        self,
        messages: list[dict],
        tools_for_llm: list[dict] | None,
        tool_call_count: int,
        conversation_id: str,
        user_id: str,
    ) -> AsyncIterator:
        """Run the ReAct loop: call LLM → handle tool calls or text → repeat."""
        iteration = 0
        force_no_tools = False  # Set True to force a text-only retry
        empty_retries = 0  # Track consecutive empty responses
        hallucination_retries = 0  # Track consecutive hallucinated-tool-call retries
        max_hallucination_retries = 2  # Give up after this many hallucination retries
        last_tool_results: list[dict] = []  # Keep track of last tool results for fallback
        while iteration < MAX_REACT_ITERATIONS:
            iteration += 1
            # If we've hit the tool call limit or need a forced text retry,
            # strip tools so the LLM must produce text.
            force_text = force_no_tools or tool_call_count >= MAX_TOOL_CALLS_PER_TURN
            current_tools = None if force_text else tools_for_llm
            force_no_tools = False  # Reset after use

            logger.info(
                "ReAct loop iteration=%d tool_call_count=%d force_text=%s "
                "empty_retries=%d msg_count=%d user=%s",
                iteration, tool_call_count, force_text, empty_retries,
                len(messages), user_id,
            )

            accumulated_text = ""
            pending_tool_calls: dict[str, _PendingToolCall] = {}
            chunk_count = 0
            # Buffer text only after we've already seen a hallucination
            # in this turn — avoids streaming garbled XML on retries while
            # keeping normal post-tool responses fully streamed.
            buffer_text = hallucination_retries > 0

            stream = self._model.chat_completion_stream(
                messages=messages,
                tools=current_tools,
            )

            # Two-tier timeout:
            # - Total timeout: hard cap on the entire stream
            # - Idle timeout: if no chunk arrives within this window, bail
            # Post-tool iterations use shorter timeouts since the user is
            # already staring at a spinner.  But after many tool calls
            # (e.g. 5), DeepSeek needs more time to synthesize all results.
            many_tools = tool_call_count >= 3
            total_timeout = 90.0 if many_tools else (45.0 if tool_call_count > 0 else 120.0)
            idle_timeout = 45.0 if many_tools else (30.0 if tool_call_count > 0 else 45.0)
            timed_out = False

            try:
                async with asyncio.timeout(total_timeout):
                    stream_iter = stream.__aiter__()
                    while True:
                        try:
                            chunk = await asyncio.wait_for(
                                stream_iter.__anext__(), timeout=idle_timeout,
                            )
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            logger.warning(
                                "ReAct iteration=%d: idle timeout (%.0fs) "
                                "waiting for next chunk (chunks=%d text_len=%d) "
                                "user=%s",
                                iteration, idle_timeout, chunk_count,
                                len(accumulated_text), user_id,
                            )
                            timed_out = True
                            break

                        chunk_count += 1
                        if chunk.type == "text_delta":
                            accumulated_text += chunk.content
                            if not buffer_text:
                                yield TextDelta(content=chunk.content)

                        elif chunk.type == "tool_call_start":
                            tc_id = chunk.tool_call_id or ""
                            pending_tool_calls[tc_id] = _PendingToolCall(
                                id=tc_id,
                                name=chunk.tool_name or "",
                                arguments="",
                            )

                        elif chunk.type == "tool_call_delta":
                            tc_id = chunk.tool_call_id or ""
                            if tc_id in pending_tool_calls:
                                pending_tool_calls[tc_id].arguments += (
                                    chunk.tool_arguments or ""
                                )

                        elif chunk.type == "tool_call_end":
                            pass

                        elif chunk.type == "done":
                            break
            except (TimeoutError, asyncio.TimeoutError):
                logger.warning(
                    "ReAct iteration=%d: total stream timeout after %.0fs "
                    "(chunks=%d text_len=%d) user=%s",
                    iteration, total_timeout, chunk_count,
                    len(accumulated_text), user_id,
                )
                timed_out = True
            except Exception as exc:
                logger.exception(
                    "LLM provider error iteration=%d user=%s: %s",
                    iteration, user_id, exc,
                )
                # If we have tool results, yield a fallback instead of a
                # generic error so the user at least knows what data we got.
                if tool_call_count > 0 and last_tool_results:
                    fallback = self._build_tool_result_fallback(last_tool_results)
                    yield TextDelta(content=fallback)
                    assistant_msg = Message(role="assistant", content=fallback)
                    await self._conversation.append_message(
                        conversation_id, assistant_msg
                    )
                else:
                    yield ErrorEvent(
                        message="The AI service is temporarily unavailable. Please try again."
                    )
                return

            # If the stream timed out, treat any partial text as the
            # response, or yield the fallback if we got nothing.
            if timed_out:
                if accumulated_text.strip():
                    # Got some text before timeout — use it as-is
                    logger.info(
                        "ReAct iteration=%d: timed out but got partial text "
                        "(%d chars) — using as response. user=%s",
                        iteration, len(accumulated_text), user_id,
                    )
                    # Strip any hallucinated markup from partial text
                    clean = _strip_hallucinated_tool_calls(accumulated_text)
                    final_text = clean.strip() or accumulated_text
                    if buffer_text:
                        yield TextDelta(content=final_text)
                    assistant_msg = Message(role="assistant", content=final_text)
                    await self._conversation.append_message(
                        conversation_id, assistant_msg
                    )
                    return

                # No text at all — yield fallback
                logger.warning(
                    "ReAct iteration=%d: timed out with no text — "
                    "yielding fallback. user=%s",
                    iteration, user_id,
                )
                if tool_call_count > 0 and last_tool_results:
                    fallback = self._build_tool_result_fallback(last_tool_results)
                else:
                    fallback = (
                        "\n\nThe AI service took too long to respond. "
                        "Could you try again?"
                    )
                yield TextDelta(content=fallback)
                assistant_msg = Message(role="assistant", content=fallback)
                await self._conversation.append_message(
                    conversation_id, assistant_msg
                )
                return

            logger.info(
                "ReAct iteration=%d finished: chunks=%d text_len=%d "
                "text_preview=%.100r tool_calls=%d user=%s",
                iteration, chunk_count, len(accumulated_text),
                accumulated_text[:100], len(pending_tool_calls), user_id,
            )

            # If no tool calls were accumulated, we have a text response — done
            if not pending_tool_calls:
                if accumulated_text.strip():
                    # Reset empty retry counter on successful text
                    empty_retries = 0

                    # Check if the LLM hallucinated tool calls as text
                    # (e.g. DeepSeek outputting XML markup instead of using
                    # the tool_calls API).  Strip the markup and retry.
                    if _contains_hallucinated_tool_calls(accumulated_text):
                        hallucination_retries += 1
                        cleaned = _strip_hallucinated_tool_calls(accumulated_text)
                        logger.warning(
                            "ReAct iteration=%d: LLM hallucinated tool calls as "
                            "text instead of using tool_calls API "
                            "(hallucination_retry=%d/%d, cleaned_len=%d). "
                            "user=%s",
                            iteration, hallucination_retries,
                            max_hallucination_retries, len(cleaned), user_id,
                        )

                        # If we've exhausted hallucination retries, stop
                        # looping and use whatever we can salvage.
                        if hallucination_retries > max_hallucination_retries:
                            logger.warning(
                                "ReAct iteration=%d: giving up after %d "
                                "hallucination retries. user=%s",
                                iteration, hallucination_retries, user_id,
                            )
                            if cleaned.strip():
                                # Use the cleaned text as the final response.
                                # Flush buffered text to the client.
                                yield TextDelta(content=cleaned)
                                assistant_msg = Message(
                                    role="assistant", content=cleaned,
                                )
                                await self._conversation.append_message(
                                    conversation_id, assistant_msg
                                )
                                return
                            # No usable text — fall back to tool result summary
                            if tool_call_count > 0 and last_tool_results:
                                fallback = self._build_tool_result_fallback(
                                    last_tool_results
                                )
                            else:
                                fallback = (
                                    "\n\nSorry, I wasn't able to compose a "
                                    "response. Could you try rephrasing?"
                                )
                            yield TextDelta(content=fallback)
                            assistant_msg = Message(
                                role="assistant", content=fallback,
                            )
                            await self._conversation.append_message(
                                conversation_id, assistant_msg
                            )
                            return

                        # Still have retries — strip markup and nudge the LLM.
                        # Force tools OFF so it must produce plain text.
                        if cleaned:
                            messages.append({
                                "role": "assistant",
                                "content": cleaned,
                            })
                        messages.append({
                            "role": "system",
                            "content": (
                                "You tried to call a tool by writing XML markup "
                                "in your response. That does not work. You MUST "
                                "use the tool_calls API to invoke tools. Never "
                                "write XML or markup to call tools. If you have "
                                "enough information already, just respond to the "
                                "user in plain text. Summarize the tool results "
                                "you already have."
                            ),
                        })
                        force_no_tools = True  # Force text-only on retry
                        accumulated_text = ""
                        continue

                    # Clean text — flush buffer if we were buffering
                    if buffer_text:
                        yield TextDelta(content=accumulated_text)
                    assistant_msg = Message(role="assistant", content=accumulated_text)
                    await self._conversation.append_message(
                        conversation_id, assistant_msg
                    )
                    return

                # Empty response — track retries
                empty_retries += 1
                logger.warning(
                    "ReAct iteration=%d empty response (empty_retries=%d, "
                    "force_text=%s, tool_call_count=%d) user=%s",
                    iteration, empty_retries, force_text, tool_call_count, user_id,
                )

                # First empty: retry with nudge (tools stripped)
                if empty_retries == 1 and tool_call_count > 0:
                    logger.info(
                        "ReAct iteration=%d: first empty after tools — "
                        "adding nudge and retrying without tools. user=%s",
                        iteration, user_id,
                    )
                    messages.append({
                        "role": "system",
                        "content": (
                            "You have received the tool results above. "
                            "Now provide your analysis and response to the user. "
                            "Do not call any more tools."
                        ),
                    })
                    force_no_tools = True
                    continue

                # Second empty (or first empty with no tools): yield fallback
                logger.warning(
                    "ReAct iteration=%d: giving up after %d empty retries — "
                    "yielding fallback. user=%s",
                    iteration, empty_retries, user_id,
                )
                if tool_call_count > 0 and last_tool_results:
                    fallback = self._build_tool_result_fallback(last_tool_results)
                else:
                    fallback = (
                        "\n\nSorry, I wasn't able to generate a response. "
                        "Could you try rephrasing your question?"
                    )
                yield TextDelta(content=fallback)
                assistant_msg = Message(role="assistant", content=fallback)
                await self._conversation.append_message(
                    conversation_id, assistant_msg
                )
                return

            # Process each pending tool call
            tool_call_records: list[ToolCallRecord] = []
            tool_result_messages: list[dict] = []
            last_tool_results = []  # Reset for this batch
            for tc in pending_tool_calls.values():
                if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
                    break
                tool_call_count += 1

                # Parse arguments
                try:
                    params = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    params = {}

                yield ToolCallStart(tool_name=tc.name, parameters=params)

                # Execute the tool
                result = await self._tools.execute(tc.name, params)

                yield ToolCallResult(
                    tool_name=tc.name,
                    result=result.data,
                    duration_ms=result.duration_ms,
                    success=result.success,
                )

                # Check for settings mutation proposals
                if tc.name == "propose_settings_mutation" and result.success:
                    yield SettingsMutationProposal(mutation=result.data)

                # Emit chart data event for candle tool results
                if tc.name == "query_candles" and result.success:
                    candles = result.data
                    if isinstance(candles, list) and len(candles) > 0:
                        yield ChartDataEvent(
                            symbol=params.get("symbol", ""),
                            timeframe_sec=params.get("timeframe_sec", 60),
                            candles=candles,
                        )

                tool_call_records.append(
                    ToolCallRecord(
                        id=tc.id,
                        tool_name=tc.name,
                        parameters=params,
                        result=result.data if result.success else result.error,
                        duration_ms=result.duration_ms,
                        success=result.success,
                    )
                )

                logger.info(
                    "Tool call: name=%s success=%s duration_ms=%.1f user=%s",
                    tc.name,
                    result.success,
                    result.duration_ms,
                    user_id,
                )

                # Collect tool result message for the LLM context
                tool_content = (
                    json.dumps(result.data)
                    if result.success
                    else f"Error: {result.error}"
                )
                tool_result_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_content,
                    }
                )
                last_tool_results.append({
                    "tool": tc.name,
                    "success": result.success,
                    "data": result.data if result.success else result.error,
                })

            # Append a single assistant message with ALL tool calls,
            # followed by individual tool result messages.
            # NOTE: DeepSeek requires content to be null (not empty string)
            # when tool_calls are present, otherwise it may return 400.
            if tool_call_records:
                assistant_entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": accumulated_text or None,
                    "tool_calls": [
                        {
                            "id": tcr.id,
                            "type": "function",
                            "function": {
                                "name": tcr.tool_name,
                                "arguments": json.dumps(tcr.parameters),
                            },
                        }
                        for tcr in tool_call_records
                    ],
                }
                messages.append(assistant_entry)
                messages.extend(tool_result_messages)

            # Persist the assistant message with tool calls
            if accumulated_text or tool_call_records:
                assistant_msg = Message(
                    role="assistant",
                    content=accumulated_text,
                    tool_calls=tool_call_records if tool_call_records else None,
                )
                await self._conversation.append_message(
                    conversation_id, assistant_msg
                )

            # Persist each tool result message so the history is valid
            # when loaded from DB on subsequent requests.
            for tool_msg in tool_result_messages:
                await self._conversation.append_message(
                    conversation_id,
                    Message(
                        role="tool",
                        content=tool_msg["content"],
                        tool_call_id=tool_msg["tool_call_id"],
                    ),
                )

            # Loop back to get the LLM's response incorporating tool results
            accumulated_text = ""

            # If we've hit the tool call limit, add a nudge so the LLM
            # knows it must produce a text summary instead of trying more
            # tool calls (which will be stripped anyway).
            if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
                messages.append({
                    "role": "system",
                    "content": (
                        "You have completed all your tool calls. Now analyze "
                        "the results above and provide a clear, helpful "
                        "response to the user. Do not attempt to call any "
                        "more tools."
                    ),
                })

        # Safety: if we exhausted iterations, yield a warning so the user
        # isn't left staring at a blank response.
        logger.warning(
            "ReAct loop hit max iterations (%d) for user=%s",
            MAX_REACT_ITERATIONS, user_id,
        )
        yield TextDelta(
            content="\n\n*I gathered the data above but ran into a limit "
            "while composing my response. Please ask a follow-up and I'll continue.*"
        )

    @staticmethod
    def _build_tool_result_fallback(tool_results: list[dict]) -> str:
        """Build a user-visible fallback from tool results.

        When the LLM fails to synthesise a response after tool execution,
        we show the raw results so the user isn't left with nothing.
        """
        parts = ["\n\nI ran into trouble composing a response, but here's what I found:\n"]
        for tr in tool_results:
            name = tr.get("tool", "unknown")
            success = tr.get("success", False)
            data = tr.get("data")
            if success and data:
                # Truncate large results
                data_str = json.dumps(data, default=str) if not isinstance(data, str) else data
                if len(data_str) > 500:
                    data_str = data_str[:500] + "…"
                parts.append(f"**{name}**: {data_str}\n")
            elif not success:
                parts.append(f"**{name}**: Error — {data}\n")
        parts.append("\nCould you ask a follow-up question so I can provide a better analysis?")
        return "".join(parts)

    async def _prefetch_decision_trace(
        self,
        decision_trace_id: str,
        messages: list[dict],
    ) -> AsyncIterator:
        """Pre-fetch a decision trace and inject the result into messages."""
        tool = self._tools.get("query_decision_traces")
        if tool is None:
            return

        yield ToolCallStart(
            tool_name="query_decision_traces",
            parameters={"trace_id": decision_trace_id},
        )

        result = await self._tools.execute(
            "query_decision_traces",
            {"trace_id": decision_trace_id},
        )

        yield ToolCallResult(
            tool_name="query_decision_traces",
            result=result.data,
            duration_ms=result.duration_ms,
            success=result.success,
        )

        if result.success and result.data:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"[Pre-fetched Decision Trace for {decision_trace_id}]\n"
                        f"{json.dumps(result.data)}"
                    ),
                }
            )


class _PendingToolCall:
    """Accumulator for a tool call being streamed from the LLM."""

    __slots__ = ("id", "name", "arguments")

    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.name = name
        self.arguments = arguments
