"""
title: Phoenix Feedback
author: vivia
version: 0.1.0
description: Reporte chaque vote 👍/👎 sur le span du tour dans Phoenix, des qu'il est donne.
"""

import asyncio
import hashlib
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Doit rester identique au `scope` du filtre `phoenix_tracing` : c'est le seul couplage
# entre les deux, et `tests/test_annotate.py` echoue si l'un des deux change seul.
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
    """Traduit un feedback Open WebUI en annotation Phoenix, ou None s'il n'est pas rattachable."""
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
        # Le score binaire rend la note moyennable dans Phoenix ; le label reste lisible.
        "result": {
            "label": "up" if rating == "1" else "down",
            "score": 1.0 if rating == "1" else 0.0,
            "explanation": data.get("comment") or data.get("reason") or None,
        },
        "metadata": {"chat_id": chat_id, "message_id": message_id, **extra},
        # Le meme feedback (vote change, commentaire ajoute) met a jour l'annotation.
        "identifier": str(feedback["id"]),
    }


def post(endpoint: str, item: dict) -> int:
    """Envoie une annotation et renvoie le statut HTTP (404 : span absent de Phoenix).

    `sync=true` : sans lui, Phoenix repond 200 et ignore en silence un span inconnu.
    """
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/v1/span_annotations?sync=true",
        data=json.dumps({"data": [item]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


class Event:
    """Fonction d'evenement Open WebUI (0.10+) : appelee a chaque `feedback.created/updated`."""

    class Valves(BaseModel):
        endpoint: str = Field(default="http://phoenix:6006", description="Base URL Phoenix")
        project_name: str = Field(
            default="open-webui", description="Projet Phoenix, le meme que Phoenix Tracing"
        )
        retries: int = Field(
            default=6, description="Essais espaces de 5 s si le tour n'est pas encore exporte"
        )

    def __init__(self):
        self.valves = self.Valves()

    async def event(self, event: dict) -> None:
        if event.get("event") not in ("feedback.created", "feedback.updated"):
            return
        try:
            from open_webui.models.feedbacks import Feedbacks

            feedback = await Feedbacks.get_feedback_by_id((event.get("subject") or {}).get("id"))
            item = feedback and annotation(feedback.model_dump(), self.valves.project_name)
            if not item:
                return
            status = 0
            for attempt in range(max(1, self.valves.retries)):
                # Le filtre exporte les spans par lot apres la reponse : un vote tres
                # rapide peut preceder leur arrivee dans Phoenix.
                status = await asyncio.to_thread(post, self.valves.endpoint, item)
                if status != 404:
                    break
                if attempt + 1 < self.valves.retries:
                    await asyncio.sleep(5)
            if not 200 <= status < 300:
                log.warning("Phoenix feedback %s -> HTTP %s", item["identifier"], status)
        except Exception:
            # Un vote ne doit jamais echouer a cause de la telemetrie.
            log.exception("Phoenix feedback failed")
