"""Recherche d'operations ELT : toujours dans le nom du flux, la description et le SQL."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import format as fmt
from vivia.tools.explore.operations import fetch_operations

_FIELDS = ("flux", "operation_description", "sql_text")
LIMIT = 25


def search_operations(
    texte: Annotated[
        str,
        Field(description="Sous-chaine cherchee, insensible a la casse (ex. 'P_TIERS', 'NVL(')."),
    ],
) -> str:
    """Operations dont le nom de flux, la description ou le SQL contient `texte` (25 au plus).

    Pour le SQL, renvoie les lignes qui correspondent (numerotees), pas le SQL entier :
    enchainer avec get_operation pour le lire.

    Exemple : search_operations("SDETRG.P_TIERS")
    """
    params = {"needle": f"%{texte.strip().upper()}%"}
    where = ["(" + " OR ".join(f"UPPER({c}) LIKE :needle" for c in _FIELDS) + ")"]
    rows = fetch_operations(where, params, max_rows=LIMIT + 1)
    return fmt.search_operations_report(texte, rows, LIMIT)
