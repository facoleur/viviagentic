"""Fonctions (filtres, evenements) chargees depuis openwebui/functions/."""

from vivia.configure.client import ROOT, OpenWebUI


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
