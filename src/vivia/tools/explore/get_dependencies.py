"""Sources d'une table, declarees dans V_M_TRAC_DATA."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.errors import guarded
from vivia.tools.explore import framework, queries


@guarded
def get_dependencies(
    table: Annotated[str, Field(description="Nom de la table, sans schema (ex. 'P_FLUX').")],
) -> str:
    """Tables sources de `table` (une ligne par source, avec sa zone).

    Pour remonter plus haut, rappeler l'outil sur une source.

    Exemple : get_dependencies("F_OPERATION")
    """
    sql = queries.TRAC_DATA_SOURCES.format(
        source=framework.union(
            framework.TRAC_DATA,
            "source_application_code, source_name, target_name, validity_end_date",
        )
    )
    _, rows = client.fetch(sql, {"target": table.strip().upper()})
    return fmt.dependencies_report(table.strip().upper(), rows)
