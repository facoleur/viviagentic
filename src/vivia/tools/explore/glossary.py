"""Glossaire des zones/types/termes metier : voir `vivia.oracle.glossary` pour les donnees."""

from typing import Annotated

from pydantic import Field

from vivia.oracle.glossary import define


def glossary(
    terme: Annotated[
        str,
        Field(
            description="Zone (SDA, SDE, DMD), type (STG, TRG, INT) ou terme metier "
            "(ex. 'TIERS', 'FLUX', 'CHAINE') a definir."
        ),
    ],
) -> str:
    """Definition d'une zone (SDA/SDE/DMD), d'un type (STG/TRG/INT) ou d'un terme metier.

    Exemple : glossary("SDA"), glossary("TIERS")
    """
    return define(terme) or f"Terme inconnu : {terme}."
