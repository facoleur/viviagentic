"""Client REST d'Open WebUI, authentifie en admin."""

from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]


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
