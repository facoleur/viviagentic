"""Bibliotheque de requetes validees a la main (few-shot) : voir verified_queries.toml, a cote."""

import tomllib
from pathlib import Path
from typing import Annotated

from pydantic import Field

_QUERIES = tomllib.loads(Path(__file__).with_name("verified_queries.toml").read_text())["queries"]


def find_verified_query(
    texte: Annotated[
        str,
        Field(
            description="Mots-cles de la question (ex. 'tiers crees avant une date'). Renvoie "
            "les requetes dont la question contient tous les mots, sans egard a la casse."
        ),
    ],
) -> str:
    """Cherche une requete deja validee dont la question contient tous les mots de `texte`.

    Exemple : find_verified_query("tiers crees avant une date")
    """
    mots = texte.upper().split()
    matches = [q for q in _QUERIES if all(mot in q["question"].upper() for mot in mots)]
    if not matches:
        return f"Aucune requete validee ne correspond a « {texte} »."
    return "\n\n".join(f"**{q['question']}**\n```sql\n{q['sql']}\n```" for q in matches)
