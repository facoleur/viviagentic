"""Lignage amont declare dans V_M_TRAC_DATA : les sources d'une table, sur 1 a 3 niveaux."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.explore import framework, queries


def get_dependencies(
    table: Annotated[str, Field(description="Nom de la table, sans schema (ex. 'P_FLUX').")],
    niveaux: Annotated[
        int, Field(description="1 : sources directes ; 2 et 3 : leurs sources.", ge=1, le=3)
    ] = 1,
) -> str:
    """Graphe des sources de `table` : 1 niveau = ses sources, chaque niveau suivant refait la
    meme recherche pour chaque source trouvee.

    Exemple : get_dependencies("F_OPERATION"), ou get_dependencies("P_FLUX", niveaux=2)
    """
    sql = queries.TRAC_DATA_SOURCES.format(
        source=framework.union(framework.TRAC_DATA, "source_name, target_name")
    )
    root = table.strip().upper()
    edges, level, seen = [], [root], set()
    for _ in range(niveaux):
        seen.update(level)
        found = []
        for target in level:
            _, rows = client.fetch(sql, {"target": target})
            found += [(source, target) for (source,) in rows]
        edges += found
        level = [s for s in dict.fromkeys(s for s, _ in found) if s not in seen]
    return fmt.dependencies_graph(root, edges)
