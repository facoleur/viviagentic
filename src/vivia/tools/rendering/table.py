from typing import Any


def table(
    rows: list[Any],
    columns: list[str] | None = None,
    title: str = "",
    subtitle: str = "",
) -> dict[str, Any]:
    """Affiche des donnees tabulaires, triables par colonne et filtrables.

    Preferable a une liste en Markdown des qu'il y a plusieurs colonnes ou plus
    d'une dizaine de lignes.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "columns": columns or None,
        "rows": rows,
    }
