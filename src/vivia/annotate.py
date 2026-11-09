"""Reporte les votes 👍/👎 d'Open WebUI en annotations Phoenix, sur le bon span.

Le filtre `phoenix_tracing.py` derive ses identifiants de span par hachage, sans
etat partage : le meme quadruplet (projet, utilisateur, chat, message) redonne
toujours le meme span. Ce script rejoue ce calcul depuis l'exterieur, ce qui
permet d'attacher un vote a son tour de conversation sans avoir trace quoi que
ce soit sur le moment. `identifier` rend l'envoi idempotent : Phoenix met a jour
l'annotation existante au lieu d'en empiler une copie a chaque passage.
"""

import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import httpx

from vivia.configure import ROOT, OpenWebUI

# Doit rester identique au `scope` du filtre : c'est le seul couplage entre les
# deux, et `tests/test_annotate.py` echoue si l'un des deux change seul.
NAMESPACE = "vivia.phoenix.v1"
ANNOTATION_NAME = "user_rating"


def span_id(project: str, user_id: str, chat_id: str, message_id: str) -> str:
    """Reproduit `_id(*scope, "message", message_id, size=8)` du filtre."""
    parts = (NAMESPACE, project, user_id, chat_id, "message", message_id)
    digest = hashlib.blake2b(
        json.dumps(parts, ensure_ascii=False, default=str).encode(), digest_size=8
    ).digest()
    return f"{int.from_bytes(digest, 'big') or 1:016x}"


def annotation(feedback: dict, project: str) -> dict[str, Any] | None:
    """Traduit un feedback en annotation, ou None s'il n'est pas rattachable."""
    data = feedback.get("data") or {}
    meta = feedback.get("meta") or {}
    chat_id, message_id = meta.get("chat_id"), meta.get("message_id")
    rating = str(data.get("rating", ""))
    # Open WebUI stocke aussi des feedbacks d'arene et des brouillons sans vote :
    # sans les trois identifiants et une note, il n'y a pas de span a annoter.
    if not (chat_id and message_id and feedback.get("user_id")) or rating not in ("1", "-1"):
        return None
    extra = {key: data[key] for key in ("comment", "reason", "model_id", "tags") if data.get(key)}
    return {
        "span_id": span_id(project, feedback["user_id"], chat_id, message_id),
        "name": ANNOTATION_NAME,
        "annotator_kind": "HUMAN",
        # Le score binaire rend la note moyennable dans Phoenix ; le label reste
        # lisible tel quel dans l'UI.
        "result": {
            "label": "up" if rating == "1" else "down",
            "score": 1.0 if rating == "1" else 0.0,
            "explanation": data.get("comment") or data.get("reason") or None,
        },
        "metadata": {"chat_id": chat_id, "message_id": message_id, **extra},
        "identifier": str(feedback["id"]),
    }


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "vivia.toml"
    cfg = tomllib.loads(path.read_text())
    # Le nom du projet vient des valves du filtre : une seule source de verite.
    valves = next(
        (f.get("valves") or {} for f in cfg.get("functions", []) if f["id"] == "phoenix_tracing"),
        {},
    )
    project = valves.get("project_name", "open-webui")
    # L'URL des valves (`http://phoenix:6006`) adresse le reseau Docker ; ce
    # script tourne sur l'hote, d'ou une entree de configuration distincte.
    phoenix = (cfg.get("phoenix", {}).get("url") or "http://127.0.0.1:6006").rstrip("/")

    api = OpenWebUI(cfg["openwebui"]["url"], cfg["admin"])
    feedbacks = api.call("GET", "/api/v1/evaluations/feedbacks/all/export")
    print(f"> {len(feedbacks)} feedback(s), projet {project}")

    payload = [a for f in feedbacks if (a := annotation(f, project))]
    skipped = len(feedbacks) - len(payload)
    if skipped:
        print(f"  {skipped} ignore(s) : sans vote ou sans chat/message")
    if not payload:
        print("done")
        return

    # `sync=true` : sans lui, Phoenix repond 200 et ignore en silence un span absent
    # (trace purgee, tour anterieur au filtre). Un envoi par vote isole ces cas.
    missing = 0
    with httpx.Client(base_url=phoenix, timeout=30) as client:
        for item in payload:
            res = client.post(
                "/v1/span_annotations", params={"sync": "true"}, json={"data": [item]}
            )
            label = f"{item['result']['label']:>4} -> span {item['span_id']}"
            if res.status_code == 404:
                missing += 1
                print(f"  {label} : absent de Phoenix, ignore")
            elif res.is_success:
                print(f"  {label}")
            else:
                print(f"  ! POST /v1/span_annotations -> {res.status_code} {res.text[:300]}")
                raise SystemExit(1)
    print(f"done ({len(payload) - missing} annotation(s), {missing} span(s) introuvable(s))")


if __name__ == "__main__":
    main()
