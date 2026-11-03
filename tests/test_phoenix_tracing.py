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


if __name__ == "__main__":
    unittest.main()
