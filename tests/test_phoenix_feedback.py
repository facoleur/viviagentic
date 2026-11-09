"""Fonction d'evenement Phoenix Feedback : vote Open WebUI -> annotation Phoenix, sans reseau."""

import sys
import tomllib
import types
import unittest
from unittest.mock import AsyncMock, patch

from openwebui.functions import phoenix_feedback as fn
from vivia.configure import ROOT

FEEDBACK = {
    "id": "fb-1",
    "user_id": "user1",
    "data": {"rating": 1, "comment": "Parfait"},
    "meta": {"chat_id": "chat1", "message_id": "a1"},
}


class Stored:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class EventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # La fonction importe le modele d'Open WebUI a l'execution : on le simule.
        self.feedbacks = AsyncMock(return_value=Stored(FEEDBACK))
        module = types.ModuleType("open_webui.models.feedbacks")
        module.Feedbacks = types.SimpleNamespace(get_feedback_by_id=self.feedbacks)
        patcher = patch.dict(sys.modules, {"open_webui.models.feedbacks": module})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.event = fn.Event()
        self.event.valves.project_name = "open-webui"

    async def fire(self, name="feedback.created", statuses=(200,)):
        sent = []

        def post(endpoint, item):
            sent.append((endpoint, item))
            return statuses[min(len(sent), len(statuses)) - 1]

        with patch.object(fn, "post", post), patch.object(fn.asyncio, "sleep", AsyncMock()):
            await self.event.event({"event": name, "subject": {"type": "feedback", "id": "fb-1"}})
        return sent

    async def test_vote_is_posted_on_the_turn_span(self):
        sent = await self.fire()
        self.feedbacks.assert_awaited_once_with("fb-1")
        endpoint, item = sent[0]
        self.assertEqual(endpoint, "http://phoenix:6006")
        self.assertEqual(item, fn.annotation(FEEDBACK, "open-webui"))
        self.assertEqual(item["span_id"], fn.span_id("open-webui", "user1", "chat1", "a1"))
        self.assertEqual(item["result"]["label"], "up")

    async def test_updates_are_posted_and_other_events_ignored(self):
        self.assertEqual(len(await self.fire("feedback.updated")), 1)
        for name in ("feedback.deleted", "chat.created", None):
            with self.subTest(event=name):
                self.assertEqual(await self.fire(name), [])

    async def test_missing_span_is_retried_until_exported(self):
        self.assertEqual(len(await self.fire(statuses=(404, 404, 200))), 3)
        self.event.valves.retries = 2
        self.assertEqual(len(await self.fire(statuses=(404,))), 2)

    async def test_unrattachable_or_unknown_feedback_posts_nothing(self):
        for stored in (None, Stored({**FEEDBACK, "data": {"comment": "sans vote"}})):
            with self.subTest(stored=stored):
                self.feedbacks.return_value = stored
                self.assertEqual(await self.fire(), [])

    async def test_failures_never_reach_open_webui(self):
        self.feedbacks.side_effect = RuntimeError("base indisponible")
        await self.fire()


class ConfigTests(unittest.TestCase):
    def test_feedback_targets_the_tracing_project(self):
        # Le projet entre dans le hachage du span : un ecart rendrait tous les votes orphelins.
        cfg = tomllib.loads((ROOT / "vivia.toml").read_text())
        valves = {f["id"]: f.get("valves", {}) for f in cfg["functions"]}
        self.assertEqual(
            valves["phoenix_feedback"]["project_name"], valves["phoenix_tracing"]["project_name"]
        )


if __name__ == "__main__":
    unittest.main()
