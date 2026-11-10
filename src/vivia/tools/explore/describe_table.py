"""Fiche complete d'une table ou vue, en un seul appel."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, resolve
from vivia.tools.explore import queries


def describe_table(
    name: Annotated[
        str,
        Field(
            description="Table ou vue a decrire, 'SCHEMA.TABLE' ou nom seul (erreur si ambigu "
            "entre plusieurs schemas)."
        ),
    ],
) -> str:
    """Fiche d'une table ou vue : colonnes, cle, index uniques, partitionnement, volumetrie, zone.

    Accepte "SCHEMA.TABLE" ou un nom seul (ambiguite levee si plusieurs schemas correspondent).
    Les operations qui l'alimentent (index hors ligne) et sa fiche de doc arriveront plus tard.

    Exemple : describe_table("DMDTRG.D_TIERS")
    """
    try:
        obj = resolve(name)
    except ResolutionError as err:
        return f"Erreur : {err}"

    params = {"owner": obj.schema, "name": obj.name}
    _, cols = client.fetch(queries.DESCRIBE_TABLE_COLUMNS, params)
    if not cols:
        return fmt.unknown_object(obj)

    _, pk = client.fetch(queries.DESCRIBE_TABLE_PK, params)
    _, uniques = client.fetch(queries.DESCRIBE_TABLE_UNIQUE_INDEXES, params)
    _, part = client.fetch(queries.DESCRIBE_TABLE_VOLUMETRY, params)

    partition_kind = None
    if part and part[0][0] == "YES":
        _, kind = client.fetch(queries.DESCRIBE_TABLE_PARTITION_KIND, params)
        partition_kind = kind[0][0] if kind else "oui (type inconnu)"

    view_text = None
    if not part:
        _, text = client.fetch(queries.DESCRIBE_TABLE_VIEW_TEXT, params)
        view_text = text[0][0] if text else None

    return fmt.describe_table_report(obj, cols, pk, uniques, part, partition_kind, view_text)
