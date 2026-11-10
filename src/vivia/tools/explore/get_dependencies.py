"""Lineage declaratif : TRAC_DATA dit, par table cible, quelles tables source sont requises.

Contrairement a `find_usages` (qui cherche dans le code), c'est une donnee du framework
ETL lui-meme : fiable, mais limitee aux dependances qu'il enregistre (pas les jointures).
"""

from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.glossary import ZONES
from vivia.tools.explore import queries


def get_dependencies(
    table_cible: Annotated[
        str,
        Field(
            description="Table cible dont on veut les dependances, 'SCHEMA.NOM' "
            "(ex. 'SDETRG.P_TIERS')."
        ),
    ],
) -> str:
    """Tables source necessaires a `table_cible`, declarees dans TRAC_DATA (une ligne par source).

    Exemple : get_dependencies("SDETRG.P_TIERS")
    """
    per_zone = " UNION ALL ".join(
        queries.TRAC_DATA_BY_ZONE.format(schema=f"{zone}TRG") for zone in ZONES
    )
    sql = queries.TRAC_DATA_DEPENDENCIES.format(unioned=per_zone)
    _, rows = client.fetch(sql, {"cible": table_cible.strip().upper()})
    return fmt.dependencies_report(table_cible, rows)
