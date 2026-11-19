"""Connexions OpenAI-compatibles `[[connections]]` : URL + cle lue dans l'environnement."""

import os

from vivia.configure.client import OpenWebUI


def sync_connections(api: OpenWebUI, connections: list[dict]) -> None:
    """Ajoute ou met a jour chaque connexion, reperee par son URL ; les autres restent intactes.

    La cle n'est jamais dans le .toml : `api_key_env` nomme la variable qui la contient (.env).
    """
    if not connections:
        return
    current = api.get("/openai/config") or {}
    urls = list(current.get("OPENAI_API_BASE_URLS") or [])
    keys = list(current.get("OPENAI_API_KEYS") or [])
    keys += [""] * (len(urls) - len(keys))
    configs = dict(current.get("OPENAI_API_CONFIGS") or {})
    for conn in connections:
        key = os.environ.get(conn["api_key_env"])
        if not key:
            raise SystemExit(f"{conn['api_key_env']} absente de l'environnement (voir .env)")
        url = conn["url"].rstrip("/")
        if url not in urls:
            urls.append(url)
            keys.append("")
        i = urls.index(url)
        keys[i] = key
        configs[str(i)] = configs.get(str(i), {}) | conn.get("config", {})
        print(f"  connexion {url} ({conn['api_key_env']})")
    api.try_call(
        "POST",
        "/openai/config/update",
        {
            "ENABLE_OPENAI_API": True,
            "OPENAI_API_BASE_URLS": urls,
            "OPENAI_API_KEYS": keys,
            "OPENAI_API_CONFIGS": configs,
        },
    )
