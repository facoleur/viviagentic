"""Regression tests against the OpenTelemetry SDK; no network exporter or LLM calls."""

import copy
import unittest
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from openwebui.functions import phoenix_tracing as tracing


def tool(call_id="call-dice", name="vivia_roll_dice", status="completed"):
    return [
        {
            "type": "function_call",
            "id": call_id,
            "call_id": call_id,
            "name": name,
            "arguments": '{"count":4,"sides":20}',
            "status": status,
            "started_at": 110.25,
            "ended_at": 110.75,
        },
        {
            "type": "function_call_output",
            "id": f"output-{call_id}",
            "call_id": call_id,
            "output": [{"type": "input_text", "text": '{"rolls":[6,5,17,1],"total":29}'}],
            "status": status,
        },
    ]


def body(message_id="a1", chat_id="chat1", output=None):
    return {
        "id": message_id,
        "chat_id": chat_id,
        "model": "qwen3:8b",
        "messages": [
            {"id": "u1", "role": "user", "content": "Lance quatre dés.", "timestamp": 100},
            {
                "id": message_id,
                "role": "assistant",
                "content": "Total : 29.",
                "timestamp": 101,
                "output": output or [],
            },
        ],
    }


class TracingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.providers = []
        self.filter = self.new_filter()
        self.user = {"id": "user1", "email": "test@example.invalid"}

    def tearDown(self):
        for provider in self.providers:
            provider.shutdown()

    def new_filter(self):
        provider = TracerProvider(id_generator=tracing.ConversationIds())
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.providers.append(provider)
        filter_ = tracing.Filter()
        filter_._tracer = provider.get_tracer("test")
        return filter_

    def spans(self, name=None):
        return [s for s in self.exporter.get_finished_spans() if name is None or s.name == name]

    async def emit(self, payload, metadata=None, filter_=None, user=None):
        with patch.object(tracing.time, "time_ns", return_value=120_000_000_000):
            return await (filter_ or self.filter).outlet(
                payload, metadata, self.user if user is None else user
            )

    async def test_two_turns_and_reload_share_one_root_and_trace(self):
        await self.emit(body())
        await self.emit(body("a2", output=tool()), filter_=self.new_filter())
        roots = self.spans("open-webui.conversation")
        turns = self.spans("open-webui.chat")
        tools = self.spans("tool.vivia_roll_dice")
        self.assertEqual(len({s.context.trace_id for s in self.spans()}), 1)
        self.assertEqual(roots[0].context.span_id, roots[1].context.span_id)
        self.assertNotEqual(turns[0].context.span_id, turns[1].context.span_id)
        self.assertTrue(all(s.parent.span_id == roots[0].context.span_id for s in turns))
        self.assertEqual(tools[0].parent.span_id, turns[1].context.span_id)
        self.assertTrue(all(s.parent is None for s in roots))
        self.assertEqual(roots[0].start_time, roots[0].end_time)
        self.assertTrue(all(s.attributes["session.id"] == "chat1" for s in self.spans()))

    async def test_only_current_message_tools_are_paired_by_call_id(self):
        payload = body(output=tool("old"))
        current = body("a2", output=tool("one") + tool("two"))["messages"]
        current[0]["content"] = "Encore."
        # Output ordering need not place each result directly after its call.
        current[1]["output"].reverse()
        current[1]["output"].append(copy.deepcopy(current[1]["output"][1]))
        payload["id"] = "a2"
        payload["messages"].extend(current)
        before = copy.deepcopy(payload)
        returned = await self.emit(payload)
        self.assertIs(returned, payload)
        self.assertEqual(payload, before)
        spans = self.spans("tool.vivia_roll_dice")
        self.assertEqual(len(spans), 2)
        self.assertEqual({s.attributes["openwebui.tool.call_id"] for s in spans}, {"one", "two"})
        for span in spans:
            self.assertEqual(span.attributes["input.value"], '{"count":4,"sides":20}')
            self.assertEqual(span.attributes["output.value"], '{"rolls":[6,5,17,1],"total":29}')
            self.assertEqual(span.start_time, 110_250_000_000)
            self.assertEqual(span.end_time, 110_750_000_000)
            self.assertEqual(span.status.status_code, trace.StatusCode.OK)
        self.assertEqual(self.spans("open-webui.chat")[0].attributes["input.value"], "Encore.")

    async def test_repeated_outlet_uses_identical_span_ids(self):
        payload = body(output=tool())
        await self.emit(payload)
        first = [(s.context.trace_id, s.context.span_id) for s in self.spans()]
        await self.emit(payload, filter_=self.new_filter())
        second = [(s.context.trace_id, s.context.span_id) for s in self.spans()][len(first) :]
        self.assertEqual(first, second)

    async def test_conversations_users_projects_and_anonymous_requests_are_isolated(self):
        await self.emit(body(chat_id="chat1"))
        await self.emit(body(chat_id="chat2"))
        await self.emit(body(chat_id="chat1"), user={"id": "user2"})
        other = self.new_filter()
        other.valves.project_name = "another-project"
        await self.emit(body(), filter_=other)
        for _ in range(2):
            await self.emit(body(chat_id=""), {"session_id": "same-browser-socket"})
        roots = self.spans("open-webui.conversation")
        self.assertEqual(len({s.context.trace_id for s in roots}), 6)
        self.assertTrue(all("session.id" not in s.attributes for s in roots[-2:]))

    async def test_inlet_timing_is_request_local_and_survives_filter_reload(self):
        first = {"chat_id": "chat1", "message_id": "a1"}
        second = {"chat_id": "chat2", "message_id": "a2"}
        with patch.object(tracing.time, "time_ns", return_value=100_100_000_000):
            await self.filter.inlet({}, first)
        with patch.object(tracing.time, "time_ns", return_value=100_200_000_000):
            await self.filter.inlet({}, second)
        await self.emit(body("a2", "chat2"), second, filter_=self.new_filter())
        await self.emit(body(), first, filter_=self.new_filter())
        turns = self.spans("open-webui.chat")
        self.assertEqual([s.start_time for s in turns], [100_200_000_000, 100_100_000_000])

    async def test_failed_tool_marks_tool_and_turn_as_errors(self):
        items = tool()
        items[1]["status"] = "failed"
        items[1]["output"] = [{"type": "input_text", "text": "Error: invalid arguments"}]
        await self.emit(body(output=items))
        for name in ["tool.vivia_roll_dice", "open-webui.chat"]:
            self.assertEqual(self.spans(name)[0].status.status_code, trace.StatusCode.ERROR)
        self.assertEqual(
            self.spans("tool.vivia_roll_dice")[0].attributes["output.value"],
            "Error: invalid arguments",
        )

    async def test_missing_timing_does_not_invent_tool_duration(self):
        items = tool()
        items[0]["started_at"] = float("nan")
        items[0]["ended_at"] = None
        await self.emit(body(output=items))
        span = self.spans("tool.vivia_roll_dice")[0]
        self.assertEqual(span.start_time, span.end_time)
        self.assertFalse(span.attributes["openwebui.tool.timing_available"])

    async def test_unresolved_call_does_not_get_a_success_status(self):
        items = tool()
        items[0]["status"] = "in_progress"
        await self.emit(body(output=items[:1]))
        span = self.spans("tool.vivia_roll_dice")[0]
        self.assertEqual(span.status.status_code, trace.StatusCode.UNSET)
        self.assertNotIn("output.value", span.attributes)

    async def test_explicit_message_selection_and_unknown_message(self):
        payload = body()
        payload["messages"].extend(body("a2", output=tool())["messages"])
        await self.emit(payload, {"message_id": "a1", "chat_id": "chat1"})
        self.assertEqual(len(self.spans("tool.vivia_roll_dice")), 0)
        before = len(self.spans())
        await self.emit(payload, {"message_id": "missing", "chat_id": "chat1"})
        self.assertEqual(len(self.spans()), before)
        payload.pop("id")
        await self.emit(payload)
        self.assertEqual(len(self.spans("tool.vivia_roll_dice")), 1)

    async def test_conversation_is_not_attached_to_an_ambient_http_trace(self):
        tracer = self.providers[0].get_tracer("ambient")
        with tracer.start_as_current_span("http-request") as ambient:
            await self.emit(body())
            self.assertEqual(trace.get_current_span(), ambient)
            self.assertNotEqual(
                ambient.get_span_context().trace_id,
                self.spans("open-webui.conversation")[0].context.trace_id,
            )
        self.assertIsNone(tracing._SPAN_IDS.get())

    async def test_telemetry_error_does_not_change_the_response(self):
        payload = body()
        with (
            patch.object(self.filter, "_trace_turn", side_effect=RuntimeError("unavailable")),
            self.assertLogs(tracing.log, level="ERROR"),
        ):
            self.assertIs(await self.emit(payload), payload)

    async def request_at(self, payload, metadata, at, filter_=None):
        with patch.object(tracing.time, "time_ns", return_value=int(at * 1e9)):
            returned = await (filter_ or self.filter).request(payload, metadata)
        self.assertIs(returned, payload)

    async def stream_at(self, event, metadata, at, filter_=None):
        before = copy.deepcopy(event)
        with patch.object(tracing.time, "time_ns", return_value=int(at * 1e9)):
            returned = await (filter_ or self.filter).stream(event, metadata)
        self.assertIs(returned, event)
        self.assertEqual(event, before)

    async def test_llm_tool_llm_sequence_with_reasoning_and_separate_contexts(self):
        metadata = {"chat_id": "chat1", "message_id": "a1"}
        request = {
            "model": "qwen3:8b",
            "stream": True,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": "Lance quatre dés."}],
            "tools": [{"type": "function", "function": {"name": "vivia_roll_dice"}}],
            "metadata": {"private": "must not be captured"},
        }
        await self.request_at(request, metadata, 102)
        await self.stream_at(
            {"choices": [{"index": 0, "delta": {"reasoning_content": "Je vais lancer "}}]},
            metadata,
            103,
        )
        await self.stream_at(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "reasoning_content": "les dés.",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-dice",
                                    "function": {
                                        "name": "vivia_roll_dice",
                                        "arguments": '{"count":',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
            metadata,
            104,
        )
        await self.stream_at(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '4,"sides":20}'}}
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            metadata,
            107,
        )
        # Usage often follows the terminal choice; it must not extend the LLM duration.
        await self.stream_at(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 6,
                    "total_tokens": 16,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                },
            },
            metadata,
            108,
        )
        request["messages"].extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-dice",
                            "function": {
                                "name": "vivia_roll_dice",
                                "arguments": '{"count":4,"sides":20}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-dice", "content": '{"total":29}'},
            ]
        )
        await self.request_at(request, metadata, 111, filter_=self.new_filter())
        await self.stream_at(
            {
                "model": "qwen3:8b-actual",
                "choices": [{"index": 0, "delta": {"reasoning_content": "Le total est 29."}}],
            },
            metadata,
            112,
        )
        await self.stream_at(
            {"choices": [{"index": 0, "delta": {"content": "Total : "}}]}, metadata, 114
        )
        await self.stream_at(
            {
                "choices": [{"index": 0, "delta": {"content": "29."}, "finish_reason": "stop"}],
                "usage": {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28},
            },
            metadata,
            116,
        )
        await self.emit(body(output=tool()), metadata, filter_=self.new_filter())
        first, second = self.spans("llm.call.1")[0], self.spans("llm.call.2")[0]
        turn = self.spans("open-webui.chat")[0]
        tool_span = self.spans("tool.vivia_roll_dice")[0]
        self.assertEqual(len(self.spans()), 5)
        self.assertEqual({s.context.trace_id for s in self.spans()}, {turn.context.trace_id})
        self.assertTrue(
            all(s.parent.span_id == turn.context.span_id for s in [first, tool_span, second])
        )
        self.assertEqual((first.start_time, first.end_time), (102_000_000_000, 107_000_000_000))
        self.assertLess(first.end_time, tool_span.start_time)
        self.assertLess(tool_span.end_time, second.start_time)
        self.assertEqual((second.start_time, second.end_time), (111_000_000_000, 116_000_000_000))
        self.assertEqual(
            first.attributes["llm.input_messages.0.message.content"], "Lance quatre dés."
        )
        self.assertNotIn("llm.input_messages.1.message.role", first.attributes)
        self.assertNotIn("private", first.attributes["input.value"])
        self.assertEqual(second.attributes["llm.input_messages.2.message.role"], "tool")
        self.assertEqual(
            second.attributes["llm.input_messages.2.message.tool_call_id"], "call-dice"
        )
        self.assertEqual(
            first.attributes["llm.output_messages.0.message.contents.0.message_content.type"],
            "reasoning",
        )
        self.assertEqual(
            first.attributes["llm.output_messages.0.message.contents.0.message_content.text"],
            "Je vais lancer les dés.",
        )
        self.assertEqual(
            first.attributes[
                "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments"
            ],
            '{"count":4,"sides":20}',
        )
        self.assertEqual(second.attributes["llm.output_messages.0.message.content"], "Total : 29.")
        self.assertEqual(first.attributes["llm.token_count.total"], 16)
        self.assertEqual(second.attributes["llm.token_count.total"], 28)
        self.assertEqual(first.attributes["llm.token_count.completion_details.reasoning"], 4)
        self.assertNotIn("llm.token_count.total", turn.attributes)
        self.assertEqual(second.attributes["llm.model_name"], "qwen3:8b-actual")
        self.assertEqual(turn.attributes["openwebui.llm.call_count"], 2)

    async def test_responses_snapshots_replace_deltas_without_duplicate_reasoning(self):
        metadata = {}
        await self.request_at(
            {"model": "responses-model", "stream": True, "messages": []}, metadata, 101
        )
        await self.stream_at(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "reasoning", "summary": []},
            },
            metadata,
            102,
        )
        await self.stream_at(
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "summary_index": 0,
                "delta": "Réflexion.",
            },
            metadata,
            103,
        )
        await self.stream_at(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Réflexion."}],
                },
            },
            metadata,
            104,
        )
        await self.stream_at(
            {
                "type": "response.completed",
                "response": {
                    "model": "responses-model",
                    "output": [
                        {
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "Réflexion."}],
                        },
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "42."}],
                        },
                    ],
                    "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                },
            },
            metadata,
            105,
        )
        await self.emit(body(), metadata)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(
            span.attributes["llm.output_messages.0.message.contents.0.message_content.text"],
            "Réflexion.",
        )
        self.assertEqual(span.attributes["llm.output_messages.1.message.content"], "42.")
        self.assertEqual(span.end_time, 105_000_000_000)
        self.assertEqual(span.status.status_code, trace.StatusCode.OK)

    async def test_non_streaming_response_uses_outlet_and_labels_timing_source(self):
        metadata = {}
        await self.request_at({"model": "qwen3:8b", "stream": False, "messages": []}, metadata, 102)
        payload = body()
        payload["messages"][-1]["output"] = [
            {"type": "reasoning", "content": [{"type": "output_text", "text": "Réflexion."}]},
            {"type": "message", "content": [{"type": "output_text", "text": "Réponse."}]},
        ]
        payload["messages"][-1]["usage"] = {
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 5,
        }
        await self.emit(payload, metadata)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(span.attributes["openwebui.llm.output_source"], "outlet")
        self.assertEqual(
            span.attributes["llm.output_messages.0.message.contents.0.message_content.type"],
            "reasoning",
        )
        self.assertEqual(span.attributes["llm.token_count.total"], 5)

    async def test_preflight_without_provider_response_is_not_an_llm_call(self):
        metadata = {}
        request = {"model": "qwen3:8b", "stream": True, "messages": []}
        await self.request_at(request, metadata, 100)
        await self.request_at(request, metadata, 105)
        await self.stream_at(
            {"choices": [{"delta": {"content": "Réponse"}, "finish_reason": "stop"}]}, metadata, 110
        )
        await self.emit(body(), metadata)
        self.assertEqual(len(self.spans("llm.call.1")), 1)
        self.assertEqual(len(self.spans("llm.call.2")), 0)
        self.assertEqual(self.spans("llm.call.1")[0].start_time, 105_000_000_000)

    async def test_partial_stream_is_not_completed_with_final_outlet_text(self):
        metadata = {}
        await self.request_at({"stream": True, "messages": []}, metadata, 102)
        await self.stream_at({"choices": [{"delta": {"content": "Partiel"}}]}, metadata, 105)
        await self.emit(body(), metadata)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(span.status.status_code, trace.StatusCode.UNSET)
        self.assertFalse(span.attributes["openwebui.llm.completed"])
        self.assertEqual(span.end_time, 105_000_000_000)
        self.assertEqual(span.attributes["llm.output_messages.0.message.content"], "Partiel")

    async def test_provider_error_marks_llm_and_turn_as_failed(self):
        metadata = {}
        await self.request_at({"stream": True, "messages": []}, metadata, 102)
        await self.stream_at({"error": {"message": "Provider unavailable"}}, metadata, 104)
        await self.emit(body(), metadata)
        self.assertEqual(self.spans("llm.call.1")[0].status.status_code, trace.StatusCode.ERROR)
        self.assertEqual(
            self.spans("open-webui.chat")[0].status.status_code, trace.StatusCode.ERROR
        )

    async def test_interleaved_streams_are_isolated_and_outlet_retries_keep_ids(self):
        first, second = {}, {}
        await self.request_at({"stream": True, "messages": []}, first, 101)
        await self.request_at({"stream": True, "messages": []}, second, 102)
        await self.stream_at(
            {"choices": [{"delta": {"content": "B"}, "finish_reason": "stop"}]}, second, 104
        )
        await self.stream_at(
            {"choices": [{"delta": {"content": "A"}, "finish_reason": "stop"}]}, first, 105
        )
        await self.emit(body("a1", "chat1"), first)
        await self.emit(body("a2", "chat2"), second)
        spans = self.spans("llm.call.1")
        self.assertEqual(
            [s.attributes["llm.output_messages.0.message.content"] for s in spans], ["A", "B"]
        )
        self.assertNotEqual(spans[0].context.trace_id, spans[1].context.trace_id)
        await self.emit(body("a1", "chat1"), first, filter_=self.new_filter())
        self.assertEqual(self.spans("llm.call.1")[-1].context.span_id, spans[0].context.span_id)

    async def test_multimodal_input_and_missing_metadata_are_safe(self):
        request = {
            "stream": True,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Regarde."},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.invalid/image.png"},
                        },
                    ],
                }
            ],
        }
        before = copy.deepcopy(request)
        metadata = {}
        await self.request_at(request, metadata, 101)
        await self.request_at(request, None, 102)
        await self.stream_at(
            {"choices": [{"delta": {"content": "Image"}, "finish_reason": "stop"}]}, None, 103
        )
        await self.stream_at(
            {"choices": [{"delta": {"content": "Image"}, "finish_reason": "stop"}]}, metadata, 104
        )
        await self.emit(body(), metadata)
        self.assertEqual(request, before)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(
            span.attributes[
                "llm.input_messages.0.message.contents.1.message_content.image.image.url"
            ],
            "https://example.invalid/image.png",
        )

    async def test_time_to_first_token_ignores_non_token_events(self):
        metadata = {"chat_id": "chat1", "message_id": "a1"}
        await self.request_at({"model": "qwen3:8b", "stream": True, "messages": []}, metadata, 100)
        # Ni un chunk de role, ni un chunk d'usage ne constituent un premier token.
        await self.stream_at({"choices": [{"delta": {"role": "assistant"}}]}, metadata, 101)
        await self.stream_at({"usage": {"prompt_tokens": 7}}, metadata, 102)
        await self.stream_at({"choices": [{"delta": {"content": "Total"}}]}, metadata, 103)
        await self.stream_at(
            {"choices": [{"delta": {"content": " : 29."}, "finish_reason": "stop"}]}, metadata, 104
        )
        await self.emit(body(), metadata)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(span.attributes["openwebui.llm.time_to_first_token_ms"], 3000)

    async def test_time_to_first_token_counts_reasoning_and_tool_arguments(self):
        for fragment, at in (({"reasoning_content": "Hmm"}, 101.5), ({"content": "x"}, 103)):
            with self.subTest(fragment=fragment):
                self.exporter.clear()
                self.filter = self.new_filter()
                metadata = {"chat_id": f"chat-{at}", "message_id": "a1"}
                await self.request_at(
                    {"model": "qwen3:8b", "stream": True, "messages": []}, metadata, 100
                )
                await self.stream_at({"choices": [{"delta": fragment}]}, metadata, at)
                await self.stream_at(
                    {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]},
                    metadata,
                    104,
                )
                await self.emit(body(), metadata)
                span = self.spans("llm.call.1")[0]
                self.assertAlmostEqual(
                    span.attributes["openwebui.llm.time_to_first_token_ms"],
                    (at - 100) * 1000,
                    places=3,
                )

    async def test_tool_call_fragment_is_a_first_token(self):
        metadata = {"chat_id": "chat1", "message_id": "a1"}
        await self.request_at({"model": "qwen3:8b", "stream": True, "messages": []}, metadata, 100)
        await self.stream_at(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": "c1", "function": {"name": "vivia_calc"}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            metadata,
            102,
        )
        await self.emit(body(), metadata)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(span.attributes["openwebui.llm.time_to_first_token_ms"], 2000)

    async def test_non_streamed_call_has_no_time_to_first_token(self):
        metadata = {"chat_id": "chat1", "message_id": "a1"}
        await self.request_at({"model": "qwen3:8b", "stream": False, "messages": []}, metadata, 100)
        await self.emit(body(), metadata)
        span = self.spans("llm.call.1")[0]
        self.assertNotIn("openwebui.llm.time_to_first_token_ms", span.attributes)

    async def test_responses_text_delta_sets_time_to_first_token(self):
        metadata = {"chat_id": "chat1", "message_id": "a1"}
        await self.request_at({"model": "qwen3:8b", "stream": True, "messages": []}, metadata, 100)
        await self.stream_at({"type": "response.created", "response": {}}, metadata, 101)
        await self.stream_at(
            {"type": "response.output_text.delta", "output_index": 0, "delta": "Total"},
            metadata,
            102,
        )
        await self.stream_at(
            {"type": "response.completed", "response": {"output": []}}, metadata, 103
        )
        await self.emit(body(), metadata)
        span = self.spans("llm.call.1")[0]
        self.assertEqual(span.attributes["openwebui.llm.time_to_first_token_ms"], 2000)


if __name__ == "__main__":
    unittest.main()
