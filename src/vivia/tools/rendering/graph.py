from typing import Any


def graph(
    edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]] | None = None,
    title: str = "",
    subtitle: str = "",
    directed: bool = False,
    height: int = 420,
) -> dict[str, Any]:
    """Dessine un graphe de noeuds et d'aretes, dispose par forces et manipulable.

    Pour tout ce qui est relationnel : dependances, arborescence, reseau,
    enchainement d'etapes.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "nodes": nodes or [],
        "edges": edges,
        "directed": directed,
        "height": height,
    }
