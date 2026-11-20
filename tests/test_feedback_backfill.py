"""Rattrapage des votes : traduction et decompte, sans reseau."""

import unittest
from unittest.mock import patch

from vivia import feedback_backfill as bf

VOTE = {
    "id": "fb-1",
    "user_id": "u1",
    "data": {"rating": 1},
    "meta": {"chat_id": "c1", "message_id": "m1"},
}
ARENA = {"id": "fb-2", "user_id": "u1", "data": {}, "meta": {}}


class BackfillTests(unittest.TestCase):
    def run_with(self, status, dry_run=False):
        fn = bf.load_function()
        sent = []

        def post(endpoint, item):
            sent.append((endpoint, item))
            return status

        with patch.object(fn, "post", post), patch.object(bf, "load_function", lambda: fn):
            stats = bf.backfill([VOTE, ARENA], "open-webui", "http://x", dry_run)
        return stats, sent

    def test_vote_is_posted_ignoring_non_votes(self):
        stats, sent = self.run_with(200)
        self.assertEqual(dict(stats), {"annote": 1, "ignore": 1})
        self.assertEqual(sent[0][1]["identifier"], "fb-1")

    def test_missing_span_is_counted(self):
        self.assertEqual(self.run_with(404)[0]["sans_span"], 1)

    def test_dry_run_sends_nothing(self):
        stats, sent = self.run_with(200, dry_run=True)
        self.assertEqual(stats["a_envoyer"], 1)
        self.assertEqual(sent, [])
