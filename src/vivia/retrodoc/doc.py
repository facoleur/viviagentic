"""Ce que redige le LLM (schema Pydantic) et l'assemblage du JSON final d'une table."""

from typing import Literal

from pydantic import BaseModel, Field

from vivia.configure.client import deep_merge


class Colonne(BaseModel):
    nom: str
    description: str = Field(description="Ce que contient la colonne, en une ou deux phrases.")
    regle_calcul: str | None = Field(
        description="Regle metier qui paraphrase le SQL producteur ; null si copie directe."
    )
    origine: list[str] = Field(description="Colonnes sources, au format SCHEMA.TABLE.COLONNE.")
    preuve: str | None = Field(description="Flux et CTE ou se lit la regle, en quelques mots.")
    confiance: Literal["haute", "moyenne", "basse"]


class Redaction(BaseModel):
    description: str = Field(description="Ce que contient la table et a quoi elle sert.")
    grain: str = Field(description="Ce que represente une ligne : 'une ligne = ...'.")
    colonnes: list[Colonne]
    acronymes_non_resolus: list[str] = Field(
        description="Acronymes rencontres, absents du glossaire et des commentaires."
    )


def build(facts: dict, draft: dict, override: dict) -> dict:
    """Faits du code + texte du LLM, puis corrections humaines (`override`, prioritaires)."""
    written = {c["nom"]: c for c in draft["redaction"]["colonnes"]}
    colonnes = {
        col["nom"]: _without_nom(col) | _without_nom(written.get(col["nom"], {}))
        for col in facts["colonnes"]
    }
    doc = {
        "table": facts["table"],
        "description": draft["redaction"]["description"],
        "grain": draft["redaction"]["grain"],
        "pk": facts["pk"],
        "flux_producteurs": facts["producteurs"],
        "flux_consommateurs": facts["consommateurs"],
        "sources": list(facts["sources"]),
        "colonnes": colonnes,
        "acronymes_non_resolus": draft["redaction"]["acronymes_non_resolus"],
        "meta": draft["meta"] | {"echantillon": facts["echantillon"]},
    }
    return deep_merge(doc, override)


def _without_nom(col: dict) -> dict:
    return {k: v for k, v in col.items() if k != "nom"}
