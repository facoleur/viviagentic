"""`make configure` sans appel reseau : modeles declares, skills."""

import os
import re
import tomllib
import unittest
from unittest import mock

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


class SkillsTests(unittest.TestCase):
    def test_every_markdown_file_is_a_skill_attached_to_the_model(self):
        cfg = tomllib.loads((configure.ROOT / "vivia.toml").read_text())
        files = configure.skills.skill_files(configure.ROOT / cfg["skills"][0]["path"])
        skills = [configure.skills.read_skill(f) for f in files]
        ids = [s["id"] for s in skills]
        self.assertEqual(ids[0], "oracle-elt")
        for skill in skills:
            self.assertTrue(skill["description"] and not skill["content"].startswith("---"))
        self.assertEqual(sorted(ids), sorted(cfg["models"][0]["meta"]["skillIds"]))
        # Chaque skill cite par un autre existe.
        for skill in skills:
            for cited in re.findall(r"`(oracle-elt[\w-]*)`", skill["content"]):
                self.assertIn(cited, ids, f"{skill['id']} cite {cited}")

    def test_sync_creates_then_updates_with_public_read(self):
        class Api:
            def __init__(self, known):
                self.known, self.posts = known, []

            def get(self, path):
                return {} if path.rsplit("/", 1)[1] in self.known else None

            def try_call(self, method, path, body):
                self.posts.append((path, body))

        api = Api({"oracle-elt"})
        configure.sync_skills(api, [{"path": "openwebui/skills/oracle-elt", "public": True}])
        self.assertEqual(api.posts[0][0], "/api/v1/skills/id/oracle-elt/update")
        self.assertTrue(all(p == "/api/v1/skills/create" for p, _ in api.posts[1:]))
        self.assertEqual(api.posts[0][1]["access_grants"][0]["principal_id"], "*")


if __name__ == "__main__":
    unittest.main()


class ConnectionsTests(unittest.TestCase):
    def test_connection_is_appended_then_updated_with_the_key_from_the_environment(self):
        class Api:
            def __init__(self, current):
                self.current, self.posts = current, []

            def get(self, path):
                return self.current

            def try_call(self, method, path, body):
                self.posts.append((path, body))

        conn = {"url": "https://gw/v1/", "api_key_env": "GW_KEY", "config": {"prefix_id": "gw"}}
        api = Api({"OPENAI_API_BASE_URLS": ["https://or/v1"], "OPENAI_API_KEYS": ["k0"],
                   "OPENAI_API_CONFIGS": {"0": {"enable": True}}})  # fmt: skip
        with mock.patch.dict(os.environ, {"GW_KEY": "secret"}):
            configure.sync_connections(api, [conn])
            path, body = api.posts[0]
            self.assertEqual(path, "/openai/config/update")
            self.assertEqual(body["OPENAI_API_BASE_URLS"], ["https://or/v1", "https://gw/v1"])
            self.assertEqual(body["OPENAI_API_KEYS"], ["k0", "secret"])
            self.assertEqual(body["OPENAI_API_CONFIGS"]["1"], {"prefix_id": "gw"})

            api.current = body  # relance : meme URL, pas de doublon
            configure.sync_connections(api, [conn])
            self.assertEqual(api.posts[1][1]["OPENAI_API_BASE_URLS"], body["OPENAI_API_BASE_URLS"])

    def test_missing_key_stops_the_run(self):
        conn = {"url": "https://gw/v1", "api_key_env": "ABSENT_KEY"}
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
            configure.sync_connections(mock.Mock(get=lambda path: {}), [conn])


class DerivedModelTests(unittest.TestCase):
    def test_public_model_gets_read_grants_and_keeps_its_base(self):
        model = {"id": "vivia-dwh", "base_model_id": "gw.m", "name": "Vivia DWH", "public": True,
                 "meta": {"builtinTools": {"web_search": False}}, "params": {}}  # fmt: skip
        api = FakeOpenWebUI([], {})
        configure.sync_models(api, [model])
        path, body = api.posts[0]
        self.assertEqual(path, "/api/v1/models/create")
        self.assertEqual(body["base_model_id"], "gw.m")
        self.assertEqual(body["access_grants"], configure.skills.PUBLIC_READ)
        self.assertNotIn("public", body)
