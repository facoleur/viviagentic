from typing import Any

import lineage as lineage_parser
from vivia.tools.rendering.graph import graph


def sql_lineage(
    sql: str,
    columns: bool = False,
    target: str = "",
) -> dict[str, Any]:
    """Lineage d'un script SQL Oracle (INSERT, MERGE, UPDATE, CREATE AS, ou SELECT + `target`),
    affiche en graphe dirige source -> cible. Les aretes sont aussi dans le resultat.
    """
    edges = lineage_parser.lineage(sql, columns=columns, target=target or None)
    ids = dict.fromkeys(n for e in edges for n in (e["source"], e["target"]))
    nodes = [{"id": n, "group": n.rsplit(".", 1)[0]} for n in ids] if columns else []
    title = "Lineage par colonne" if columns else "Lineage par table"
    return graph(edges, nodes, title=title, subtitle=f"{len(edges)} aretes", directed=True)
