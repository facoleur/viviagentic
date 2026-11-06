"""
title: Phoenix Tracing
author: vivia
version: 0.6.0
description: Une trace par conversation (tours, appels LLM, TTFT, outils). Open WebUI 0.10+.
requirements: arize-phoenix-otel, openinference-semantic-conventions
"""

import copy
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
from opentelemetry.sdk.trace import SpanLimits
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from phoenix.otel import register
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
_SPAN_IDS: ContextVar[tuple[int, int] | None] = ContextVar("phoenix_span_ids", default=None)
_STARTED = "vivia_phoenix_started_ns"
_CALLS = "vivia_phoenix_llm_calls"
# Open WebUI < 0.12 n'a pas de hook `request` : le corps vu par `inlet` est alors la seule
# entree disponible, et les appels LLM sont ouverts par `stream` au premier evenement.
_INLET = "vivia_phoenix_inlet_call"
_HAS_REQUEST = "vivia_phoenix_request_hook"
_PARAMETERS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "seed",
    "reasoning_effort",
)


def _parts_text(parts) -> str:
    if isinstance(parts, str):
        return parts
    return "\n".join(p.get("text", "") for p in parts or [] if isinstance(p, dict))


def _responses_messages(items: list[dict]) -> list[dict]:
    """Normalize provider output items, preserving reasoning/text/tool order."""
    messages = []
    for item in items:
        kind = item.get("type")
        if kind == "message":
            messages.append(
                {"role": item.get("role", "assistant"), "content": item.get("content", [])}
            )
        elif kind == "reasoning":
            messages.append(
                {
                    "role": "assistant",
                    "reasoning_content": _parts_text(item.get("content") or item.get("summary")),
                }
            )
        elif kind == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": item.get("call_id") or item.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": item.get("name", ""),
                                "arguments": item.get("arguments", ""),
                            },
                        }
                    ],
                }
            )
    return messages


def _message_attributes(messages: list[dict], prefix: str) -> dict:
    """OpenInference's indexed attributes drive Phoenix's structured chat view."""
    attrs = {}
    for i, message in enumerate(messages):
        key = f"{prefix}.{i}.message"
        attrs[f"{key}.role"] = message.get("role", "assistant")
        for field in ("name", "tool_call_id"):
            if message.get(field):
                attrs[f"{key}.{field}"] = str(message[field])
        content = message.get("content")
        if content is not None:
            attrs[f"{key}.content"] = _text(content)
        parts = []
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if reasoning:
            parts.append({"type": "reasoning", "text": _text(reasoning)})
        if isinstance(content, list):
            parts.extend(content)
        elif content:
            parts.append({"type": "text", "text": content})
        for j, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            part_key = f"{key}.contents.{j}.message_content"
            kind = part.get("type", "text")
            if kind in {
                "input_text",
                "output_text",
                "summary_text",
                "reasoning_text",
                "text",
                "reasoning",
            }:
                attrs[f"{part_key}.type"] = (
                    "reasoning"
                    if kind in {"reasoning", "reasoning_text", "summary_text"}
                    else "text"
                )
                attrs[f"{part_key}.text"] = part.get("text", "")
            elif kind in {"image_url", "input_image"}:
                url = part.get("image_url", "")
                attrs[f"{part_key}.type"] = "image"
                attrs[f"{part_key}.image.image.url"] = (
                    url.get("url", "") if isinstance(url, dict) else url
                )
        for j, call in enumerate(message.get("tool_calls") or []):
            call_key = f"{key}.tool_calls.{j}.tool_call"
            attrs[f"{call_key}.id"] = str(call.get("id", ""))
            fn = call.get("function") or {}
            attrs[f"{call_key}.function.name"] = fn.get("name", "")
            attrs[f"{call_key}.function.arguments"] = _dump(fn.get("arguments", ""))
    return attrs


def _first_token(call: dict, now: int, fragment) -> None:
    # Le TTFT se mesure sur le premier fragment reellement emis par le modele :
    # les evenements de role, d'usage ou d'ouverture d'item n'en sont pas un.
    if fragment:
        call.setdefault("first_token", now)


def _observe_chat_chunk(call: dict, event: dict, now: int) -> None:
    for choice in event.get("choices") or []:
        index = choice.get("index", 0)
        message = call["choices"].setdefault(index, {"role": "assistant", "tool_calls": {}})
        delta = choice.get("delta") or choice.get("message") or {}
        for key in ("content", "reasoning_content", "reasoning", "refusal"):
            if isinstance(delta.get(key), str):
                message[key] = message.get(key, "") + delta[key]
                _first_token(call, now, delta[key])
        for item in delta.get("tool_calls") or []:
            tool = message["tool_calls"].setdefault(item.get("index", 0), {"function": {}})
            if item.get("id"):
                tool["id"] = item["id"]
            tool["type"] = item.get("type", "function")
            for key in ("name", "arguments"):
                value = (item.get("function") or {}).get(key)
                if value:
                    tool["function"][key] = tool["function"].get(key, "") + value
                    _first_token(call, now, value)
        if choice.get("finish_reason"):
            call["finish_reasons"][index] = choice["finish_reason"]
    if call["choices"] and len(call["finish_reasons"]) == len(call["choices"]):
        call.setdefault("ended", now)
        call["completed"] = True


def _observe_responses_event(call: dict, event: dict, now: int) -> None:
    kind = event.get("type", "")
    response = event.get("response") or {}
    if response.get("model"):
        call["response_model"] = response["model"]
    if response.get("usage"):
        call["usage"].update(response["usage"])
    index = event.get("output_index", 0)
    if kind in {"response.output_item.added", "response.output_item.done"}:
        call["items"][index] = copy.deepcopy(event["item"])
    elif kind == "response.function_call_arguments.delta":
        item = call["items"].setdefault(index, {"type": "function_call"})
        item["arguments"] = item.get("arguments", "") + event.get("delta", "")
        _first_token(call, now, event.get("delta", ""))
    elif kind in {
        "response.output_text.delta",
        "response.reasoning_text.delta",
        "response.reasoning_summary_text.delta",
    }:
        reasoning = "reasoning" in kind
        item = call["items"].setdefault(index, {"type": "reasoning" if reasoning else "message"})
        # Terminal item/response snapshots replace these partial deltas, never append twice.
        field = "summary" if "summary" in kind else "content"
        parts = item.setdefault(field, [])
        part_index = event.get("summary_index" if field == "summary" else "content_index", 0)
        while len(parts) <= part_index:
            parts.append({"type": "output_text", "text": ""})
        parts[part_index]["text"] += event.get("delta", "")
        _first_token(call, now, event.get("delta", ""))
    elif kind in {"response.completed", "response.incomplete", "response.failed"}:
        if "output" in response:
            call["items"] = dict(enumerate(copy.deepcopy(response["output"])))
        call["ended"] = now
        call["completed"] = kind == "response.completed"
        call["finish_reasons"][0] = (response.get("incomplete_details") or {}).get(
            "reason"
        ) or kind.removeprefix("response.")
        if kind == "response.failed":
            call["error"] = response.get("error") or "Provider response failed"


def _new_call(body: dict, now: int, source: str) -> dict:
    # Snapshot only model inputs, never metadata (which contains our state,
    # tool callables and potentially credentials). Later hooks mutate messages.
    return {
        "id": uuid4().hex,
        "started": now,
        "model": body.get("model", "unknown"),
        "stream": body.get("stream", False),
        "input": copy.deepcopy({k: body[k] for k in ("messages", "tools") if k in body}),
        "input_source": source,
        "parameters": copy.deepcopy({k: body[k] for k in _PARAMETERS if k in body}),
        "choices": {},
        "items": {},
        "usage": {},
        "finish_reasons": {},
        "completed": False,
    }


def _starts_response(event: dict) -> bool:
    """Evenement qui ouvre une reponse fournisseur : contenu ou erreur, pas un usage seul."""
    kind = event.get("type", "")
    return (
        kind in {"response.created", "response.in_progress", "error"}
        or "error" in event
        or (not kind and bool(event.get("choices")))
    )


def _completion_messages(call: dict) -> list[dict]:
    if call.get("items"):
        return _responses_messages([item for _, item in sorted(call["items"].items())])
    messages = []
    for _, message in sorted(call["choices"].items()):
        normalized = dict(message)
        normalized["tool_calls"] = [t for _, t in sorted(message["tool_calls"].items())]
        messages.append(normalized)
    return messages


def _usage_attributes(usage: dict) -> dict:
    attrs = {}
    for attr, aliases in (
        (SA.LLM_TOKEN_COUNT_PROMPT, ("prompt_tokens", "input_tokens", "prompt_eval_count")),
        (SA.LLM_TOKEN_COUNT_COMPLETION, ("completion_tokens", "output_tokens", "eval_count")),
        (SA.LLM_TOKEN_COUNT_TOTAL, ("total_tokens",)),
    ):
        value = next((usage[k] for k in aliases if isinstance(usage.get(k), int)), None)
        if value is not None:
            attrs[attr] = value
    details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    if isinstance(details.get("reasoning_tokens"), int):
        attrs[SA.LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING] = details["reasoning_tokens"]
    return attrs


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
                span_limits=SpanLimits(max_attributes=4096),
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
        # Open WebUI 0.10+ passes this same dict to the inline outlet. No shared
        # per-request cache: abandoned requests cannot leak or collide here.
        if __metadata__ is not None:
            now = time.time_ns()
            __metadata__.setdefault(_STARTED, now)
            if isinstance(body, dict) and "messages" in body:
                try:
                    __metadata__.setdefault(_INLET, _new_call(body, now, "inlet_filter"))
                except Exception:
                    log.exception("Phoenix inlet capture failed")
        return body

    async def request(self, body: dict, __metadata__: dict | None = None) -> dict:
        if __metadata__ is None:
            return body
        __metadata__[_HAS_REQUEST] = True
        try:
            call = _new_call(body, time.time_ns(), "request_filter")
            __metadata__.setdefault(_CALLS, []).append(call)
        except Exception:
            log.exception("Phoenix request capture failed")
        return body

    async def stream(self, event: dict, __metadata__: dict | None = None) -> dict:
        kind = event.get("type", "") if isinstance(event, dict) else ""
        if not isinstance(event, dict) or not (
            any(k in event for k in ("choices", "usage", "error"))
            or kind.startswith("response.")
            or kind == "error"
        ):
            return event
        metadata = __metadata__ or {}
        calls = metadata.get(_CALLS) or []
        # < 0.12 : chaque nouvelle reponse du fournisseur ouvre un appel. Le premier
        # reprend l'entree vue par inlet ; les suivants (apres outils) n'en ont pas.
        if (
            _INLET in metadata
            and not metadata.get(_HAS_REQUEST)
            and (not calls or (calls[-1].get("ended") and _starts_response(event)))
        ):
            call = copy.deepcopy(metadata[_INLET])
            call.update(id=uuid4().hex, started=time.time_ns(), stream=True, legacy=True)
            if calls:
                call.update(input={}, input_source="unavailable")
            calls = metadata.setdefault(_CALLS, [])
            calls.append(call)
        if not calls:
            return event
        call = calls[-1]
        try:
            now = time.time_ns()
            call["last_event"] = now
            if event.get("model"):
                call["response_model"] = event["model"]
            if event.get("usage"):
                call["usage"].update(event["usage"])
            if kind.startswith("response."):
                _observe_responses_event(call, event, now)
            else:
                _observe_chat_chunk(call, event, now)
            if event.get("error") or kind == "error":
                call["error"] = copy.deepcopy(event.get("error") or event)
                call["ended"] = now
        except Exception:
            log.exception("Phoenix stream capture failed")
        return event

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
        if _INLET in metadata and not metadata.get(_HAS_REQUEST) and not metadata.get(_CALLS):
            # < 0.12 sans streaming : l'appel n'est connu que par inlet et outlet.
            metadata[_CALLS] = [{**metadata[_INLET], "legacy": True}]
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
            failed |= self._trace_llms(span, message, metadata, scope, common, ended)
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

    def _trace_llms(
        self, parent, message: dict, metadata: dict, scope: tuple, common: dict, ended: int
    ) -> bool:
        calls = metadata.get(_CALLS) or []
        failed = False
        count = 0
        for index, call in enumerate(calls):
            observed = "last_event" in call
            # Open WebUI also invokes request() before approval resumes, without
            # calling the provider. Do not manufacture an LLM span for that hook.
            non_streaming = not call["stream"] and index == len(calls) - 1
            if not observed and not non_streaming:
                continue
            count += 1
            if observed:
                output = _completion_messages(call)
                end = call.get("ended") or call["last_event"]
                usage = call["usage"]
                completed = call["completed"]
                reasons = list(call["finish_reasons"].values())
            else:
                # Non-streamed replies have no stream hook. The completed outlet
                # provides the response, but its time includes post-processing.
                output = _responses_messages(message.get("output") or []) or [
                    {
                        "role": "assistant",
                        "content": message.get("content", ""),
                    }
                ]
                end, completed = ended, True
                usage = (message.get("usage") or {}) if len(calls) == 1 else {}
                reasons = [message["finish_reason"]] if message.get("finish_reason") else []
            error = call.get("error")
            failed |= bool(error)
            attributes = {
                **_message_attributes(call["input"].get("messages", []), SA.LLM_INPUT_MESSAGES),
                **_message_attributes(output, SA.LLM_OUTPUT_MESSAGES),
                **_usage_attributes(usage),
            }
            for i, tool in enumerate(call["input"].get("tools") or []):
                attributes[f"llm.tools.{i}.tool.json_schema"] = _dump(tool)
            # Keep the full JSON and identity even if a long chat exceeds the
            # SDK's limit for indexed attributes. They are inserted last.
            attributes.update(
                {
                    **common,
                    SA.OPENINFERENCE_SPAN_KIND: Kind.LLM.value,
                    SA.LLM_MODEL_NAME: str(call.get("response_model") or call["model"]),
                    SA.LLM_REQUEST_MODEL_NAME: str(call["model"]),
                    SA.LLM_INVOCATION_PARAMETERS: _dump(call["parameters"]),
                    SA.INPUT_VALUE: _dump(call["input"]),
                    SA.INPUT_MIME_TYPE: "application/json",
                    SA.OUTPUT_VALUE: _dump(
                        {"messages": output, **({"error": error} if error else {})}
                    ),
                    SA.OUTPUT_MIME_TYPE: "application/json",
                    "openwebui.llm.sequence": count,
                    "openwebui.llm.completed": completed,
                    "openwebui.llm.input_source": call.get("input_source", "request_filter"),
                    "openwebui.llm.output_source": "stream_filter" if observed else "outlet",
                    "openwebui.llm.structured_attributes_truncated": len(attributes) + 20 > 4096,
                    "openwebui.message.id": str(
                        message.get("id") or metadata.get("message_id") or ""
                    ),
                }
            )
            if reasons:
                attributes[SA.LLM_FINISH_REASON] = ",".join(reasons)
            # OpenInference n'a pas de convention de TTFT : attribut maison.
            # Seul le streaming en fournit un ; sans lui, ne rien inventer.
            # Sans hook `request` (< 0.12), le debut de l'appel n'est pas observable.
            if call.get("first_token") and not call.get("legacy"):
                attributes["openwebui.llm.time_to_first_token_ms"] = (
                    call["first_token"] - call["started"]
                ) / 1_000_000
            span = self._span(
                f"llm.call.{count}",
                scope,
                ("llm", parent.get_span_context().span_id, call["id"]),
                context=trace.set_span_in_context(parent, Context()),
                start_time=call["started"],
                attributes=attributes,
            )
            if error:
                span.set_status(trace.Status(trace.StatusCode.ERROR, _dump(error)))
            elif completed:
                span.set_status(trace.Status(trace.StatusCode.OK))
            span.end(end_time=max(call["started"], end))
        parent.set_attribute("openwebui.llm.call_count", count)
        return failed
