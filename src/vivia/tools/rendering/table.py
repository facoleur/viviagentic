from typing import Annotated, Any

from pydantic import Field


def table(
    rows: Annotated[
        list[dict[str, Any]] | list[list[Any]],
        Field(
            description="Donnees a afficher : liste d'objets (une cle par colonne), ou liste de "
            "listes alignees sur `columns`. Les deux formes sont acceptees."
        ),
    ],
    columns: Annotated[
        list[str] | None,
        Field(
            description="Noms de colonnes, dans l'ordre d'affichage. Obligatoire si `rows` est "
            "une liste de listes ; deduit des cles si `rows` est une liste d'objets et que "
            "`columns` est omis."
        ),
    ] = None,
    title: Annotated[str, Field(description="Titre affiche au-dessus du tableau.")] = "",
    subtitle: Annotated[
        str, Field(description="Sous-titre, typiquement la source des donnees.")
    ] = "",
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
