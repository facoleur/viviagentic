from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class ChartSeries(BaseModel):
    """Une serie de valeurs numeriques, alignee position a position sur `labels`."""

    name: Annotated[
        str, Field(description="Nom de la serie, affiche dans la legende et l'infobulle au survol.")
    ] = ""
    values: Annotated[
        list[float | None],
        Field(
            description="Valeurs numeriques, une par entree de `labels`, dans le meme ordre et "
            "la meme longueur. Utiliser `null` pour un point manquant (pas 0)."
        ),
    ]


def chart(
    labels: Annotated[
        list[str],
        Field(
            description="Etiquettes de l'axe des categories (ex. mois, type d'operation), dans "
            "l'ordre d'affichage souhaite."
        ),
    ],
    series: Annotated[
        list[ChartSeries],
        Field(
            description="Une ou plusieurs series a tracer. Chaque serie a un `name` et des "
            "`values` (meme longueur que `labels`) — pas `data`."
        ),
    ],
    title: Annotated[str, Field(description="Titre affiche au-dessus du graphique.")] = "",
    kind: Annotated[
        Literal["bar", "line", "area"],
        Field(
            description="Type de rendu : 'bar' (barres groupees), 'line' (lignes) ou "
            "'area' (aires sous la ligne)."
        ),
    ] = "bar",
    subtitle: Annotated[
        str,
        Field(description="Sous-titre, typiquement la source des donnees ou la methode de calcul."),
    ] = "",
    height: Annotated[
        int, Field(description="Hauteur du graphique en pixels.", ge=120, le=700)
    ] = 300,
) -> dict[str, Any]:
    """Trace un graphique (barres, lignes ou aires) a partir de series chiffrees.

    A utiliser des qu'une reponse comporte des valeurs comparables : evolution,
    repartition, comparaison entre categories.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "kind": kind,
        "labels": labels,
        "series": [s.model_dump(exclude_defaults=True) for s in series],
        "height": height,
    }
