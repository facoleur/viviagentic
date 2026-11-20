"""Enricher : prompt Jinja -> LLM (API OpenAI-compatible : Ollama, vLLM) -> objet Pydantic.

Avec Ollama, fixer le contexte cote serveur (ex. OLLAMA_CONTEXT_LENGTH=131072) : l'API
OpenAI-compatible ne le transmet pas et le defaut est trop court pour le SQL des flux.
"""

import os
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ValidationError

URL = os.getenv("RETRODOC_LLM_URL", "http://localhost:11434/v1")
MODEL = os.getenv("RETRODOC_MODEL", "qwen3.6:35b")

_jinja = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("prompts")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template: str, **data) -> str:
    return _jinja.get_template(template).render(**data)


def enrich[T: BaseModel](schema: type[T], system: str, user: str, retries: int = 3) -> T:
    """Reponse structuree selon `schema` ; si elle est invalide, renvoie l'erreur au modele."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
    }
    for attempt in range(retries):
        res = httpx.post(
            f"{URL}/chat/completions",
            json={
                "model": MODEL,
                "messages": messages,
                "response_format": response_format,
                "temperature": 0,
            },
            timeout=3600,
        )
        res.raise_for_status()
        answer = res.json()["choices"][0]["message"]["content"]
        try:
            return schema.model_validate_json(answer)
        except ValidationError as err:
            if attempt == retries - 1:
                raise
            messages += [
                {"role": "assistant", "content": answer},
                {"role": "user", "content": f"JSON invalide, corrige-le :\n{err}"},
            ]
    raise AssertionError("unreachable")
