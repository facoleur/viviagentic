"""Lignage amont declaratif : TRAC_DATA dit, par table cible, de quelles sources elle a besoin.

On remonte source par source jusqu'aux sources SDA, niveau par niveau, avec une profondeur
maximale contre les boucles. Pas de colonnes ni de jointures : seulement ce que le framework
enregistre.
"""

import re
from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.explore import queries

_MAX_DEPTH = 10


def table_name(name: str) -> str:
    """Nom nu, sans schema, prefixe de vue V_ ni suffixe $ : SDEINT.V_P_FLUX$CV -> P_FLUX."""
    bare = name.strip().upper().rsplit(".", 1)[-1]
    return re.sub(r"\$.*", "", bare.removeprefix("V_"))


def get_dependencies(
    table: Annotated[
        str, Field(description="Nom de la table, sans schema (ex. 'P_FLUX', 'F_OPERATION').")
    ],
) -> str:
    """Graphe des sources de `table` (TRAC_DATA), remonte jusqu'aux sources SDA.

    Exemple : get_dependencies("F_OPERATION")
    """
    root = table_name(table)
    edges: dict[tuple[str, str], None] = {}
    zones, seen, level = {}, {root}, [root]
    for _ in range(_MAX_DEPTH):
        upper = []
        for target in level:
            _, rows = client.fetch(queries.TRAC_DATA_SOURCES, {"target": target})
            for zone, source_name in rows:
                source = table_name(source_name)
                edges[(source, target)] = None
                zones[source] = zone
                if zone != "SDA" and source not in seen:  # SDA = source initiale, on s'arrete
                    seen.add(source)
                    upper.append(source)
        level = upper
        if not level:
            break
    return fmt.dependencies_graph(root, list(edges), zones, complete=not level)
