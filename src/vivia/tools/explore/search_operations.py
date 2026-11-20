"""Recherche d'operations ELT : toujours dans le nom du flux, la description et le SQL."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import format as fmt
from vivia.tools.explore.operations import fetch_operations, in_list

_FIELDS = ("flux", "operation_description", "sql_text")


def search_operations(
    texte: Annotated[
        str,
        Field(description="Sous-chaine cherchee, insensible a la casse (ex. 'P_TIERS', 'NVL(')."),
    ],
    chaines: Annotated[
        list[str] | None, Field(description="Restreint a ces chaines. Omis = toutes.")
    ] = None,
    limite: Annotated[int, Field(description="Nombre maximal d'operations.", ge=1, le=200)] = 25,
) -> str:
    """Operations dont le nom de flux, la description ou le SQL contient `texte`.

    Pour le SQL, renvoie les lignes qui correspondent (numerotees), pas le SQL entier :
    enchainer avec get_operation pour le lire.

    Exemple : search_operations("SDETRG.P_TIERS")
    """
    params: dict = {"needle": f"%{texte.strip().upper()}%"}
    where = ["(" + " OR ".join(f"UPPER({c}) LIKE :needle" for c in _FIELDS) + ")"]
    if chaines:
        where.append(in_list("chaine", chaines, params))
    rows = fetch_operations(where, params, max_rows=limite)
    return fmt.search_operations_report(texte, rows, limite)
