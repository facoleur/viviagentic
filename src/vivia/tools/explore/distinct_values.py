"""Valeurs distinctes d'une colonne : evite qu'un filtre devine une casse/orthographe fausse."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, ensure_identifier, resolve
from vivia.tools.explore import queries

_DEFAULT_LIMIT = 25


def distinct_values(
    table: Annotated[
        str, Field(description="Table ou vue source, 'SCHEMA.NOM' ou nom seul si non ambigu.")
    ],
    colonne: Annotated[
        str,
        Field(description="Colonne dont on liste les valeurs distinctes (ex. 'type_mouvement')."),
    ],
    limite: Annotated[
        int, Field(description="Nombre maximal de valeurs distinctes renvoyees.", ge=1, le=500)
    ] = _DEFAULT_LIMIT,
) -> str:
    """Liste les valeurs distinctes d'une colonne (ex. un statut, un type), triees.

    Exemple : distinct_values("SDATRG.MOUVEMENT", "type_mouvement")
    """
    try:
        obj = resolve(table)
        col = ensure_identifier(colonne)
    except (ResolutionError, ValueError) as err:
        return f"Erreur : {err}"

    sql = queries.DISTINCT_VALUES.format(col=col, obj=obj, limit=limite)
    _, rows = client.fetch(sql, max_rows=limite)
    return fmt.distinct_values_report(col, rows, limite)
