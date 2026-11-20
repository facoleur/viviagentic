"""Operations ELT d'un flux (ou de toute une chaine), dans l'ordre d'execution."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import format as fmt
from vivia.tools.errors import guarded
from vivia.tools.explore.operations import fetch_operations

LIMIT = 500


@guarded
def list_operations(
    chaine: Annotated[str, Field(description="Chaine (ex. 'SDE_LOAD').")],
    flux: Annotated[
        str | None, Field(description="Flux de la chaine (ex. 'P_TIERS'). Omis = toute la chaine.")
    ] = None,
) -> str:
    """Operations d'un flux : numero, description, table cible, nombre de lignes de SQL.

    Exemple : list_operations("SDE_LOAD", "P_TIERS")
    """
    where, params = ["chain_name = :chaine"], {"chaine": chaine.strip().upper()}
    if flux:
        where.append("flow_name = :flux")
        params["flux"] = flux.strip().upper()
    rows = fetch_operations(
        where, params, last_col="REGEXP_COUNT(operation, CHR(10)) + 1", max_rows=LIMIT + 1
    )
    return fmt.list_operations_report(chaine, flux, rows, LIMIT)
