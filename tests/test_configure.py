"""`make configure` : seuls les modeles declares restent actifs, sans appel reseau."""

import unittest

from vivia import configure


class FakeOpenWebUI:
    def __init__(self, available, entries):
        self.available, self.entries, self.posts = available, entries, []

    def get(self, path):
        if path == "/api/models":
            return {"data": self.available}
        return self.entries.get(path.split("id=")[1].replace("%3A", ":"))

    def try_call(self, method, path, body):
        self.posts.append((path.split("?")[0], body))


class OnlyDeclaredModelsTests(unittest.TestCase):
    declared = [{"id": "qwen3:8b", "name": "qwen3:8b", "is_active": True}]  # noqa: RUF012

    def run_sync(self, only_declared, entries=None):
        api = FakeOpenWebUI(
            [
                {"id": "qwen3:8b", "owned_by": "ollama"},
                {"id": "nomic-embed-text:latest", "name": "nomic", "owned_by": "ollama"},
                {"id": "mon-assistant", "owned_by": "ollama"},
                {"id": "arena-model", "owned_by": "arena"},
            ],
            entries or {},
        )
        configure.sync_models(api, self.declared, only_declared)
        return {body["id"]: (path, body) for path, body in api.posts}

    def test_every_other_model_gets_an_inactive_entry(self):
        posts = self.run_sync(
            True, {"mon-assistant": {"id": "mon-assistant", "base_model_id": "x"}}
        )
        self.assertTrue(posts["qwen3:8b"][1]["is_active"])
        # Modele Ollama sans entree : creee, desactivee, avec les champs exiges par l'API.
        path, body = posts["nomic-embed-text:latest"]
        self.assertEqual(path, "/api/v1/models/create")
        self.assertEqual(body, {"id": "nomic-embed-text:latest", "name": "nomic", "meta": {},
                                "params": {}, "is_active": False})  # fmt: skip
        # Modele du workspace : son entree est conservee, seul is_active change.
        path, body = posts["mon-assistant"]
        self.assertEqual(path, "/api/v1/models/model/update")
        self.assertEqual(body, {"id": "mon-assistant", "base_model_id": "x", "is_active": False})
        self.assertNotIn("arena-model", posts)

    def test_nothing_is_disabled_without_the_option(self):
        self.assertEqual(list(self.run_sync(False)), ["qwen3:8b"])


if __name__ == "__main__":
    unittest.main()
