"""Applique `vivia.toml` a Open WebUI via son API REST. Idempotent."""

import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]


def deep_merge(base: Any, patch: dict) -> dict:
    """Etat courant + patch declare, en descendant dans les sous-objets."""
    merged = dict(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        current = merged.get(key)
        merged[key] = deep_merge(current, value) if isinstance(value, dict) else value
    return merged


class OpenWebUI:
    def __init__(self, url: str, admin: dict[str, str]):
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=30)
        self.http.post("/api/v1/auths/signup", json=admin)  # 400 si l'admin existe deja
        token = self.call("POST", "/api/v1/auths/signin", admin)["token"]
        self.http.headers["Authorization"] = f"Bearer {token}"

    def call(self, method: str, path: str, body: Any = None) -> Any:
        res = self.http.request(method, path, json=body)
        res.raise_for_status()
        return res.json()

    def get(self, path: str) -> Any | None:
        """Lecture silencieuse : None si la ressource n'existe pas."""
        res = self.http.get(path)
        return res.json() if res.is_success else None

    def try_call(self, method: str, path: str, body: Any = None) -> Any | None:
        try:
            return self.call(method, path, body)
        except httpx.HTTPStatusError as err:
            print(f"  ! {method} {path} -> {err.response.status_code} {err.response.text[:160]}")
            return None


def sync_users(api: OpenWebUI, users: list[dict], groups: list[dict]) -> None:
    known = {u["email"]: u for u in api.call("GET", "/api/v1/users/?page=1")["users"]}
    for user in users:
        if user["email"] not in known:
            payload = {k: v for k, v in user.items() if k != "groups"}
            created = api.try_call("POST", "/api/v1/auths/add", payload | {"profile_image_url": ""})
            if created:
                known[user["email"]] = created
        print(f"  user {user['email']}")

    by_name = {g["name"]: g for g in api.call("GET", "/api/v1/groups/")}
    for group in groups:
        existing = by_name.get(group["name"]) or api.call(
            "POST",
            "/api/v1/groups/create",
            {"name": group["name"], "description": group.get("description", "")},
        )
        members = [
            known[u["email"]]["id"]
            for u in users
            if group["name"] in u.get("groups", []) and u["email"] in known
        ]
        api.try_call(
            "POST",
            f"/api/v1/groups/id/{existing['id']}/update",
            {
                "name": group["name"],
                "description": group.get("description", ""),
                "permissions": group.get("permissions"),
                "user_ids": members,
            },
        )
        print(f"  group {group['name']} ({len(members)} membre(s))")


def sync_api(api: OpenWebUI, sections: dict[str, dict]) -> None:
    """Patch declaratif : l'etat courant est relu, fusionne, puis repousse entier.

    Ces endpoints exigent le formulaire complet (un champ absent => 422), d'ou
    la relecture ; le chemin de lecture est le chemin d'ecriture sans `/update`.
    """
    for path, patch in sections.items():
        current = api.get(f"/api/v1/{path.removesuffix('/update')}") or {}
        api.try_call("POST", f"/api/v1/{path}", deep_merge(current, patch))
        print(f"  {path}")


def upsert_model(api: OpenWebUI, model: dict, default: dict | None = None) -> None:
    """Cree ou met a jour l'entree de modele `model["id"]` (fusionnee dans l'existante)."""
    query = quote(model["id"], safe="")
    current = api.get(f"/api/v1/models/model?id={query}")
    path = f"/api/v1/models/model/update?id={query}" if current else "/api/v1/models/create"
    api.try_call("POST", path, deep_merge(current or default or {}, model))


def sync_models(api: OpenWebUI, models: list[dict], only_declared: bool = False) -> None:
    """Entrees de modele : porte les toolIds et les params de function calling.

    `only_declared` desactive tout autre modele (Ollama, connexions, modeles du workspace) :
    une entree `is_active=false` de meme id le retire de la liste, pour tous les comptes.
    """
    for model in models:
        upsert_model(api, model)
        tools = (model.get("meta") or {}).get("toolIds") or []
        print(f"  model {model['id']} (tools: {', '.join(tools) or 'aucun'})")
    if not only_declared:
        return
    declared = {m["id"] for m in models}
    # /api/models ne liste que les modeles actifs : un modele deja desactive n'y est plus.
    for model in (api.get("/api/models") or {}).get("data", []):
        if model["id"] in declared or model.get("owned_by") == "arena":
            continue  # l'arene se coupe par sa config (evaluations/config)
        base = {
            "id": model["id"],
            "name": model.get("name") or model["id"],
            "meta": {},
            "params": {},
        }
        upsert_model(api, {"id": model["id"], "is_active": False}, default=base)
        print(f"  model {model['id']} desactive")


def sync_functions(api: OpenWebUI, functions: list[dict]) -> None:
    for fn in functions:
        payload = {
            "id": fn["id"],
            "name": fn["name"],
            "type": fn.get("type", "filter"),
            "content": (ROOT / fn["path"]).read_text(),
            "meta": {"description": fn.get("description", ""), "manifest": {}},
        }
        current = api.get(f"/api/v1/functions/id/{fn['id']}")
        endpoint = (
            f"/api/v1/functions/id/{fn['id']}/update" if current else "/api/v1/functions/create"
        )
        api.try_call("POST", endpoint, payload)

        if fn.get("valves"):
            api.try_call("POST", f"/api/v1/functions/id/{fn['id']}/valves/update", fn["valves"])

        # /toggle et /toggle/global basculent l'etat : ne les appeler qu'en cas d'ecart.
        state = api.get(f"/api/v1/functions/id/{fn['id']}") or {}
        flags = {"active": "is_active", "global": "is_global"}
        for key, field in flags.items():
            wanted = fn.get(key, False)
            if bool(state.get(field)) != wanted:
                suffix = "/toggle" if key == "active" else "/toggle/global"
                api.try_call("POST", f"/api/v1/functions/id/{fn['id']}{suffix}")
        print(f"  function {fn['id']} ({', '.join(k for k in flags if fn.get(k)) or 'inactive'})")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "vivia.toml"
    cfg = tomllib.loads(path.read_text())
    api = OpenWebUI(cfg["openwebui"]["url"], cfg["admin"])
    print(f"> {cfg['openwebui']['url']} (admin {cfg['admin']['email']})")

    sync_users(api, cfg.get("users", []), cfg.get("groups", []))
    sync_api(api, cfg.get("api", {}))
    sync_models(api, cfg.get("models", []), cfg["openwebui"].get("only_declared_models", False))
    sync_functions(api, cfg.get("functions", []))
    print("done")


if __name__ == "__main__":
    main()
