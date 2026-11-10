from typing import Any, Literal


def chart(
    labels: list[str],
    series: list[dict[str, Any]],
    title: str = "",
    kind: Literal["bar", "line", "area"] = "bar",
    subtitle: str = "",
    height: int = 300,
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
        "series": series,
        "height": height,
    }
