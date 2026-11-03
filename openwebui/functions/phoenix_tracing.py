"""
title: Phoenix Tracing
author: vivia
version: 0.3.0
description: Une trace par conversation, un span par tour et par appel d'outil.
requirements: arize-phoenix-otel, openinference-semantic-conventions
"""

import hashlib
import json
import logging
import math
import time
from contextvars import ContextVar
from uuid import uuid4

from openinference.semconv.trace import OpenInferenceSpanKindValues as Kind
from openinference.semconv.trace import SpanAttributes as SA
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from phoenix.otel import register
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
_SPAN_IDS: ContextVar[tuple[int, int] | None] = ContextVar("phoenix_span_ids", default=None)
_STARTED = "vivia_phoenix_started_ns"


def _dump(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _text(value) -> str:
    if isinstance(value, list) and all(
        isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}
        for part in value
    ):
        return "\n".join(str(part.get("text", "")) for part in value)
    return _dump(value)


def _ns(seconds) -> int | None:
    if isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds > 0:
        return int(seconds * 1_000_000_000)
    return None


def _id(*parts, size: int) -> int:
    # Namespace includes project + user + chat: Phoenix span IDs are globally unique.
    digest = hashlib.blake2b(_dump(parts).encode(), digest_size=size).digest()
    return int.from_bytes(digest, "big") or 1


class ConversationIds(RandomIdGenerator):
    """Use explicit IDs only inside this filter's synchronous start_span calls."""

    def generate_trace_id(self) -> int:
        ids = _SPAN_IDS.get()
        return ids[0] if ids else super().generate_trace_id()

    def generate_span_id(self) -> int:
        ids = _SPAN_IDS.get()
        return ids[1] if ids else super().generate_span_id()

    def is_trace_id_random(self) -> bool:
        return False


class Filter:
    class Valves(BaseModel):
        endpoint: str = Field(default="http://phoenix:6006", description="Base URL Phoenix")
        project_name: str = Field(default="open-webui", description="Projet Phoenix")

    def __init__(self):
        self.valves = self.Valves()
        self._tracer = None

    @property
    def tracer(self) -> trace.Tracer:
        if self._tracer is None:
            self._tracer = register(
                endpoint=f"{self.valves.endpoint.rstrip('/')}/v1/traces",
                project_name=self.valves.project_name,
                batch=True,
                set_global_tracer_provider=False,
                id_generator=ConversationIds(),
            ).get_tracer(__name__)
        return self._tracer

    def _span(self, name: str, scope: tuple, key: tuple, **kwargs) -> trace.Span:
        ids = (_id(*scope, size=16), _id(*scope, *key, size=8))
        token = _SPAN_IDS.set(ids)
        try:
            return self.tracer.start_span(name, **kwargs)
        finally:
            _SPAN_IDS.reset(token)

    async def inlet(self, body: dict, __metadata__: dict | None = None) -> dict:
        # Open WebUI 0.13 passes this same dict to the inline outlet. No shared
        # per-request cache: abandoned requests cannot leak or collide here.
        if __metadata__ is not None:
            __metadata__.setdefault(_STARTED, time.time_ns())
        return body

    async def outlet(
        self, body: dict, __metadata__: dict | None = None, __user__: dict | None = None
    ) -> dict:
        try:
            self._trace_turn(body, __metadata__ or {}, __user__ or {})
        except Exception:
            # Telemetry must never prevent a chat response from being delivered.
            log.exception("Phoenix tracing failed")
        return body

    def _trace_turn(self, body: dict, metadata: dict, user: dict) -> None:
        messages = body.get("messages") or []
        message_id = metadata.get("message_id") or body.get("id")
        index = next(
            (
                i
                for i in range(len(messages) - 1, -1, -1)
                if messages[i].get("role") == "assistant"
                and (not message_id or messages[i].get("id") == message_id)
            ),
            None,
        )
        if index is None:
            return
        message = messages[index]
        message_id = message_id or message.get("id") or uuid4().hex
        chat_id = metadata.get("chat_id") or body.get("chat_id")
        user_id = user.get("id") or metadata.get("user_id") or user.get("email") or "anonymous"
        # Never use Open WebUI's session_id: it identifies a browser socket, not a chat.
        scope = ("vivia.phoenix.v1", self.valves.project_name, user_id, chat_id or uuid4().hex)
        common = {SA.USER_ID: str(user_id)}
        if chat_id:
            common[SA.SESSION_ID] = str(chat_id)

        ended = time.time_ns()
        started = metadata.get(_STARTED) or _ns(message.get("timestamp")) or ended
        started = min(started, ended)
        history = messages[: index + 1]
        anchor_time = next(
            (ts for m in history if (ts := _ns(m.get("timestamp"))) is not None), started
        )
        # Conversation lifetimes are open-ended. Export a zero-duration anchor,
        # not an unfinished root or an invented conversation duration. Re-emitting
        # its stable ID is safe: Phoenix ignores spans it has already ingested.
        anchor_time = min(anchor_time, started)
        root = self._span(
            "open-webui.conversation",
            scope,
            ("conversation",),
            context=Context(),
            start_time=anchor_time,
            attributes={
                **common,
                SA.OPENINFERENCE_SPAN_KIND: Kind.CHAIN.value,
                "openwebui.conversation.anchor": True,
            },
        )
        root.end(end_time=anchor_time)
        span = self._span(
            "open-webui.chat",
            scope,
            ("message", message_id),
            context=trace.set_span_in_context(root, Context()),
            start_time=started,
            attributes={
                **common,
                SA.OPENINFERENCE_SPAN_KIND: Kind.CHAIN.value,
                SA.LLM_MODEL_NAME: str(body.get("model", "unknown")),
                SA.INPUT_VALUE: next(
                    (
                        _text(m.get("content", ""))
                        for m in reversed(history)
                        if m.get("role") == "user"
                    ),
                    "",
                ),
                SA.OUTPUT_VALUE: _text(message.get("content", "")),
                "openwebui.message.id": str(message_id),
            },
        )
        try:
            failed = self._trace_tools(span, message, scope, common, ended)
            span.set_status(trace.Status(trace.StatusCode.ERROR if failed else trace.StatusCode.OK))
        finally:
            span.end(end_time=ended)

    def _trace_tools(self, parent, message: dict, scope: tuple, common: dict, ended: int) -> bool:
        # outlet receives saved Responses-style output, even for Ollama models.
        output = message.get("output") or []
        results = {
            item["call_id"]: item
            for item in output
            if item.get("type") == "function_call_output" and item.get("call_id")
        }
        seen = set()
        failed = False
        for index, call in enumerate(output):
            if call.get("type") != "function_call":
                continue
            call_id = call.get("call_id") or call.get("id") or f"index:{index}"
            if call_id in seen:
                continue
            seen.add(call_id)
            result = results.get(call_id, {})
            name = call.get("name") or "unknown"
            status = result.get("status") or call.get("status") or "unknown"
            error = status in {"failed", "error", "cancelled", "denied"}
            failed |= error
            start = _ns(call.get("started_at"))
            end = _ns(call.get("ended_at"))
            timed = start is not None and end is not None and end >= start
            if not timed:
                # Missing execution times do not justify inventing a duration.
                start = end = start or end or ended
            attributes = {
                **common,
                SA.OPENINFERENCE_SPAN_KIND: Kind.TOOL.value,
                SA.TOOL_NAME: name,
                SA.INPUT_VALUE: _dump(call.get("arguments", "")),
                "openwebui.tool.call_id": str(call_id),
                "openwebui.tool.status": status,
                "openwebui.tool.timing_available": timed,
            }
            if result:
                attributes[SA.OUTPUT_VALUE] = _text(result.get("output", ""))
            span = self._span(
                f"tool.{name}",
                scope,
                ("tool", parent.get_span_context().span_id, call_id),
                context=trace.set_span_in_context(parent, Context()),
                start_time=start,
                attributes=attributes,
            )
            if error:
                span.set_status(trace.Status(trace.StatusCode.ERROR, f"Tool {status}"))
            elif result and status == "completed":
                span.set_status(trace.Status(trace.StatusCode.OK))
            span.end(end_time=end)
        return failed
