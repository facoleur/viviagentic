"""Le script d'annotation rejoue le calcul d'ID du filtre : il doit le suivre."""

import unittest
from typing import ClassVar

from openwebui.functions import phoenix_tracing as tracing
from vivia import annotate


class SpanIdContractTests(unittest.TestCase):
    """Garde-fou du seul couplage entre le filtre et le script.

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
                scope = (annotate.NAMESPACE, project, user, chat)
                expected = f"{tracing._id(*scope, 'message', message, size=8):016x}"
                self.assertEqual(annotate.span_id(project, user, chat, message), expected)

    def test_namespace_matches_the_filter(self):
        # Le filtre construit son scope en dur : le relire garantit l'accord.
        source = tracing.__file__
        with open(source, encoding="utf-8") as handle:
            self.assertIn(f'"{annotate.NAMESPACE}"', handle.read())

    def test_span_id_is_sixteen_hex_characters(self):
        for project, user, chat, message in self.cases:
            value = annotate.span_id(project, user, chat, message)
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
                item = annotate.annotation(self.feedback(data={"rating": rating}), "open-webui")
                self.assertEqual(item["result"]["label"], label)
                self.assertEqual(item["result"]["score"], score)
                self.assertEqual(item["annotator_kind"], "HUMAN")

    def test_span_id_targets_the_rated_message(self):
        item = annotate.annotation(self.feedback(), "open-webui")
        self.assertEqual(item["span_id"], annotate.span_id("open-webui", "user1", "chat1", "a1"))

    def test_identifier_is_the_feedback_id_so_reruns_update(self):
        item = annotate.annotation(self.feedback(id="fb-42"), "open-webui")
        self.assertEqual(item["identifier"], "fb-42")

    def test_comment_and_tags_are_carried(self):
        item = annotate.annotation(
            self.feedback(
                data={"rating": "-1", "comment": "Dés faux.", "tags": ["outil"], "reason": "x"}
            ),
            "open-webui",
        )
        self.assertEqual(item["result"]["explanation"], "Dés faux.")
        self.assertEqual(item["metadata"]["tags"], ["outil"])
        self.assertEqual(item["metadata"]["chat_id"], "chat1")

    def test_reason_is_used_when_there_is_no_comment(self):
        item = annotate.annotation(
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
                self.assertIsNone(annotate.annotation(feedback, "open-webui"))

    def test_no_explanation_when_nothing_was_written(self):
        item = annotate.annotation(self.feedback(), "open-webui")
        self.assertIsNone(item["result"]["explanation"])

    def test_project_name_changes_the_target_span(self):
        a = annotate.annotation(self.feedback(), "open-webui")
        b = annotate.annotation(self.feedback(), "autre-projet")
        self.assertNotEqual(a["span_id"], b["span_id"])


if __name__ == "__main__":
    unittest.main()
