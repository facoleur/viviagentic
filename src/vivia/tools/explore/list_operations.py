"""Liste des operations ELT d'une ou plusieurs chaines, dans l'ordre d'execution."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import format as fmt
from vivia.tools.explore.operations import fetch_operations, in_list


def list_operations(
    chaines: Annotated[list[str], Field(description="Chaines a lister (ex. ['SDE_LOAD']).")],
    limite: Annotated[int, Field(description="Nombre maximal d'operations.", ge=1, le=1000)] = 100,
) -> str:
    """Operations des chaines : flux, numero, description, table cible, taille du SQL.

    Exemple : list_operations(["SDE_LOAD", "DMD_LOAD"])
    """
    params: dict = {}
    where = [in_list("chaine", chaines, params)]
    nb_lines = "REGEXP_COUNT(sql_text, CHR(10)) + 1"
    rows = fetch_operations(where, params, last_col=nb_lines, max_rows=limite)
    return fmt.list_operations_report(chaines, rows, limite)
