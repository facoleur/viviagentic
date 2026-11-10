from typing import Annotated, Any

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """Un noeud du graphe.

    Un noeud cite par une arete (`source`/`target`) sans etre declare ici est cree
    automatiquement, avec son id comme libelle.
    """

    id: Annotated[
        str | int, Field(description="Identifiant unique du noeud, reference par les aretes.")
    ]
    label: Annotated[
        str | None,
        Field(description="Libelle affiche sous le noeud. Par defaut, l'id est utilise."),
    ] = None
    group: Annotated[
        str | None,
        Field(
            description="Groupe/categorie du noeud : determine sa couleur et son entree de legende."
        ),
    ] = None
    value: Annotated[
        float | None,
        Field(
            description="Valeur numerique optionnelle, utilisee pour dimensionner le noeud "
            "(sinon base sur son degre dans le graphe)."
        ),
    ] = None
    fixed: Annotated[
        bool,
        Field(
            description="Si vrai, le noeud garde sa position de depart au lieu d'etre deplace "
            "par la simulation."
        ),
    ] = False


class GraphEdge(BaseModel):
    """Une arete entre deux noeuds, identifies par leur `id`."""

    source: Annotated[str | int, Field(description="Id du noeud de depart.")]
    target: Annotated[str | int, Field(description="Id du noeud d'arrivee.")]
    weight: Annotated[
        float,
        Field(
            description="Poids de l'arete : une arete plus lourde tire davantage les deux "
            "noeuds l'un vers l'autre.",
            gt=0,
        ),
    ] = 1.0


def graph(
    edges: Annotated[
        list[GraphEdge],
        Field(
            description="Aretes du graphe. Chaque arete reference ses noeuds par `source`/`target`."
        ),
    ],
    nodes: Annotated[
        list[GraphNode] | None,
        Field(
            description="Noeuds a declarer explicitement, pour leur donner un `label`/`group`/"
            "`value`. Optionnel : tout noeud cite par une arete mais absent d'ici est cree "
            "automatiquement."
        ),
    ] = None,
    title: Annotated[str, Field(description="Titre affiche au-dessus du graphe.")] = "",
    subtitle: Annotated[
        str, Field(description="Sous-titre, typiquement la source des donnees.")
    ] = "",
    directed: Annotated[
        bool, Field(description="Si vrai, les aretes sont dirigees et affichees avec une fleche.")
    ] = False,
    height: Annotated[int, Field(description="Hauteur du graphe en pixels.", ge=120, le=760)] = 420,
) -> dict[str, Any]:
    """Dessine un graphe de noeuds et d'aretes, dispose par forces et manipulable.

    Pour tout ce qui est relationnel : dependances, arborescence, reseau,
    enchainement d'etapes.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "nodes": [n.model_dump(exclude_defaults=True) for n in nodes] if nodes else [],
        "edges": [e.model_dump(exclude_defaults=True) for e in edges],
        "directed": directed,
        "height": height,
    }
