"""Lignage amont declaratif : TRAC_DATA dit, par table cible, de quelles sources elle a besoin.

Un niveau par defaut : ce lignage est au niveau table, et le remonter en entier finit par
rattacher une table a presque tout le DWH. L'agent remonte lui-meme la branche utile. Meme
avec plusieurs niveaux, on s'arrete aux sources SDA et aux tables P (reutilisees partout :
leur contenu compte, pas leurs propres sources).
"""

import re
from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.explore import queries


def table_name(name: str) -> str:
    """Nom nu, sans schema, prefixe de vue V_ ni suffixe $ : SDEINT.V_P_FLUX$CV -> P_FLUX."""
    bare = name.strip().upper().rsplit(".", 1)[-1]
    return re.sub(r"\$.*", "", bare.removeprefix("V_"))


def sources(target: str) -> list[tuple[str, str]]:
    """(zone, table) des sources directes de `target`, noms de vue ramenes a la table."""
    _, rows = client.fetch(queries.TRAC_DATA_SOURCES, {"target": target})
    return list(dict.fromkeys((zone, table_name(name)) for zone, name in rows))


def get_dependencies(
    table: Annotated[
        str, Field(description="Nom de la table, sans schema (ex. 'P_FLUX', 'F_OPERATION').")
    ],
    niveaux: Annotated[
        int,
        Field(
            description="Niveaux a remonter. 1 (defaut) : sources directes. Plus : pour une "
            "analyse d'impact ; s'arrete quand meme aux sources SDA et aux tables P.",
            ge=1,
            le=10,
        ),
    ] = 1,
) -> str:
    """Graphe des sources de `table` (TRAC_DATA), avec le nombre de sources de chaque branche.

    Pour suivre une branche, rappeler l'outil sur la source voulue plutot que d'augmenter
    `niveaux`.

    Exemple : get_dependencies("F_OPERATION"), puis get_dependencies("P_FLUX")
    """
    root = table_name(table)
    edges: dict[tuple[str, str], None] = {}
    zones: dict[str, str] = {}
    climbed, level = set(), [root]
    for _ in range(niveaux):
        climbed.update(level)
        upper = []
        for target in level:
            for zone, source in sources(target):
                edges[(source, target)] = None
                zones[source] = zone
                if zone != "SDA" and not source.startswith("P_") and source not in climbed:
                    upper.append(source)
        level = list(dict.fromkeys(upper))
    pending = {n: len(sources(n)) for n, z in zones.items() if z != "SDA" and n not in climbed}
    return fmt.dependencies_graph(root, list(edges), zones, pending)
