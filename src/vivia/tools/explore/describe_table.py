"""Fiche complete d'une table ou vue, en un seul appel."""

from typing import Annotated

import oracledb
from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import resolve
from vivia.oracle.profile import profile_of_the_day
from vivia.tools.errors import guarded
from vivia.tools.explore import queries


@guarded
def describe_table(
    table: Annotated[
        str,
        Field(
            description="Table ou vue a decrire, 'SCHEMA.TABLE' ou nom seul (erreur si ambigu "
            "entre plusieurs schemas)."
        ),
    ],
) -> str:
    """Fiche d'une table ou vue : nombre de lignes, colonnes profilees, cle, index uniques.

    Le nombre de lignes est compte (COUNT(*)) ; chaque colonne porte un profil calcule sur un
    echantillon des donnees, sans les statistiques Oracle : part de nulls, valeurs distinctes,
    valeurs frequentes des colonnes de codes, bornes, valeurs sentinelles (9999-12-31, -1...).

    Accepte "SCHEMA.TABLE" ou un nom seul (ambiguite levee si plusieurs schemas correspondent).
    Les operations qui l'alimentent (index hors ligne) et sa fiche de doc arriveront plus tard.

    Exemple : describe_table("DMDTRG.D_TIERS")
    """
    obj = resolve(table)

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

    try:  # le profil enrichit la fiche : sa panne ne doit jamais la faire echouer
        profile = profile_of_the_day(obj.schema, obj.name, tuple((c, t) for c, t, _, _ in cols))
    except oracledb.DatabaseError as err:
        profile = f"Profil non calcule ({fmt.oracle_error(err)})."
    return fmt.describe_table_report(
        obj, cols, pk, uniques, part, partition_kind, view_text, profile
    )
