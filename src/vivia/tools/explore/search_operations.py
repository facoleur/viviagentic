"""Recherche d'operations ELT par nom de flux, description ou contenu SQL."""

from typing import Annotated, Literal

from pydantic import Field

from vivia.oracle import format as fmt
from vivia.tools.explore.operations import fetch_operations, in_list

_FIELDS = {"nom": "flux", "description": "operation_description", "sql": "sql_text"}


def search_operations(
    texte: Annotated[
        str,
        Field(description="Sous-chaine cherchee, insensible a la casse (ex. 'P_TIERS', 'NVL(')."),
    ],
    dans: Annotated[
        Literal["tout", "nom", "description", "sql"],
        Field(description="Ou chercher : nom du flux, description, SQL, ou les trois."),
    ] = "tout",
    chaines: Annotated[
        list[str] | None, Field(description="Restreint a ces chaines. Omis = toutes.")
    ] = None,
    limite: Annotated[int, Field(description="Nombre maximal d'operations.", ge=1, le=200)] = 25,
) -> str:
    """Operations dont le nom de flux, la description ou le SQL contient `texte`.

    Pour le SQL, renvoie les lignes qui correspondent (numerotees), pas le SQL entier :
    enchainer avec get_operation pour le lire.

    Exemple : search_operations("SDETRG.P_TIERS", dans="sql")
    """
    params: dict = {"needle": f"%{texte.strip().upper()}%"}
    cols = _FIELDS.values() if dans == "tout" else [_FIELDS[dans]]
    where = ["(" + " OR ".join(f"UPPER({c}) LIKE :needle" for c in cols) + ")"]
    if chaines:
        where.append(in_list("chaine", chaines, params))
    rows = fetch_operations(where, params, max_rows=limite)
    return fmt.search_operations_report(texte, rows, limite)
