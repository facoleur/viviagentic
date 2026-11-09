"""Entrees de modele : tools, skills, params, modeles desactives."""

from urllib.parse import quote

from vivia.configure.client import OpenWebUI, deep_merge


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
        meta = model.get("meta") or {}
        tools = ", ".join(meta.get("toolIds") or []) or "aucun"
        skills = ", ".join(meta.get("skillIds") or []) or "aucun"
        print(f"  model {model['id']} (tools: {tools} ; skills: {skills})")
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
