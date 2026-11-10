"""Fonction d'evenement Phoenix Feedback : vote Open WebUI -> annotation Phoenix, sans reseau."""

import sys
import tomllib
import types
import unittest
from typing import ClassVar
from unittest.mock import AsyncMock, patch

from openwebui.functions import phoenix_feedback as fn
from openwebui.functions import phoenix_tracing as tracing
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


class SpanIdContractTests(unittest.TestCase):
    """Garde-fou du seul couplage entre le filtre et la fonction d'evenement.

    Si le namespace, la composition du scope ou la fonction de hachage changent
    d'un cote seulement, ces tests echouent — et non les annotations en silence.
    """

    cases: ClassVar[list[tuple[str, str, str, str]]] = [
        ("open-webui", "user1", "chat1", "a1"),
        ("open-webui", "3a893c18-d9b0-4cf4-a23e-8875c636db90", "189b57bf", "db57f397"),
        # Accents et non-ASCII : `ensure_ascii` doit concorder des deux cotes.
        ("projet-é", "utilisateur-ü", "chat-ß", "message-漢"),
        # Separateurs dans les composants : le hachage porte sur une liste JSON,
        # donc aucune concatenation ambigue n'est possible.
        ("a", "b/c", "d:e", 'f"g'),
    ]

    def test_span_id_matches_the_filter(self):
        for project, user, chat, message in self.cases:
            with self.subTest(project=project, user=user):
                scope = (fn.NAMESPACE, project, user, chat)
                expected = f"{tracing._id(*scope, 'message', message, size=8):016x}"
                self.assertEqual(fn.span_id(project, user, chat, message), expected)

    def test_namespace_matches_the_filter(self):
        # Le filtre construit son scope en dur : le relire garantit l'accord.
        with open(tracing.__file__, encoding="utf-8") as handle:
            self.assertIn(f'"{fn.NAMESPACE}"', handle.read())

    def test_span_id_is_sixteen_hex_characters(self):
        for project, user, chat, message in self.cases:
            value = fn.span_id(project, user, chat, message)
            self.assertRegex(value, r"^[0-9a-f]{16}$")


class AnnotationTests(unittest.TestCase):
    def feedback(self, **overrides):
        base = {
            "id": "fb-1",
            "user_id": "user1",
            "type": "rating",
            "data": {"rating": "1", "model_id": "qwen3:8b"},
            "meta": {"chat_id": "chat1", "message_id": "a1"},
        }
        return base | overrides

    def test_thumbs_up_and_down_become_label_and_score(self):
        for rating, label, score in (("1", "up", 1.0), ("-1", "down", 0.0), (1, "up", 1.0)):
            with self.subTest(rating=rating):
                item = fn.annotation(self.feedback(data={"rating": rating}), "open-webui")
                self.assertEqual(item["result"]["label"], label)
                self.assertEqual(item["result"]["score"], score)
                self.assertEqual(item["annotator_kind"], "HUMAN")

    def test_span_id_targets_the_rated_message(self):
        item = fn.annotation(self.feedback(), "open-webui")
        self.assertEqual(item["span_id"], fn.span_id("open-webui", "user1", "chat1", "a1"))

    def test_identifier_is_the_feedback_id_so_reruns_update(self):
        item = fn.annotation(self.feedback(id="fb-42"), "open-webui")
        self.assertEqual(item["identifier"], "fb-42")

    def test_comment_and_tags_are_carried(self):
        item = fn.annotation(
            self.feedback(
                data={"rating": "-1", "comment": "Dés faux.", "tags": ["outil"], "reason": "x"}
            ),
            "open-webui",
        )
        self.assertEqual(item["result"]["explanation"], "Dés faux.")
        self.assertEqual(item["metadata"]["tags"], ["outil"])
        self.assertEqual(item["metadata"]["chat_id"], "chat1")

    def test_reason_is_used_when_there_is_no_comment(self):
        item = fn.annotation(
            self.feedback(data={"rating": "-1", "reason": "Réponse hors sujet"}), "open-webui"
        )
        self.assertEqual(item["result"]["explanation"], "Réponse hors sujet")

    def test_unrattachable_feedbacks_are_skipped(self):
        for label, feedback in (
            ("sans vote", self.feedback(data={"comment": "juste un mot"})),
            ("vote vide", self.feedback(data={"rating": ""})),
            ("sans chat_id", self.feedback(meta={"message_id": "a1"})),
            ("sans message_id", self.feedback(meta={"chat_id": "chat1"})),
            ("sans meta", self.feedback(meta={})),
            ("meta nulle", self.feedback(meta=None)),
            ("data nulle", self.feedback(data=None)),
            ("sans user_id", self.feedback(user_id="")),
            # Les feedbacks d'arene comparent deux modeles, hors d'un tour trace.
            ("arene", self.feedback(meta={"arena": True, "chat_id": "chat1"})),
        ):
            with self.subTest(label=label):
                self.assertIsNone(fn.annotation(feedback, "open-webui"))

    def test_no_explanation_when_nothing_was_written(self):
        item = fn.annotation(self.feedback(), "open-webui")
        self.assertIsNone(item["result"]["explanation"])

    def test_project_name_changes_the_target_span(self):
        a = fn.annotation(self.feedback(), "open-webui")
        b = fn.annotation(self.feedback(), "autre-projet")
        self.assertNotEqual(a["span_id"], b["span_id"])


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
