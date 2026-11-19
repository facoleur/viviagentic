"""Lignage amont declaratif : TRAC_DATA dit, par table cible, quelles tables source sont requises.

Recursif : chaque source est remontee a son tour (vue *INT ramenee a sa table *TRG) jusqu'aux
tables sans source declaree, en general les ingestions SDA. Limite aux dependances que le
framework enregistre (pas les colonnes ni les jointures).
"""

from typing import Annotated

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.explore import queries


def get_dependencies(
    table_cible: Annotated[
        str,
        Field(
            description="Table cible dont on veut les dependances, 'SCHEMA.NOM' "
            "(ex. 'SDETRG.P_TIERS')."
        ),
    ],
    recursif: Annotated[
        bool,
        Field(description="True : remonte jusqu'aux sources initiales. False : un seul niveau."),
    ] = True,
) -> str:
    """Tables source de `table_cible` declarees dans TRAC_DATA, en arbre jusqu'aux sources SDA.

    Exemple : get_dependencies("DMDTRG.F_OPERATION"), ou get_dependencies("...", recursif=False)
    """
    _, views = client.fetch(queries.VIEW_TABLES, max_rows=100_000)
    tables_of: dict[str, list[str]] = {}
    for view, table in views:
        tables_of.setdefault(view, []).append(table)

    lines: list[str] = []
    seen = {table_cible.strip().upper()}

    def walk(table: str, depth: int) -> None:
        _, rows = client.fetch(queries.TRAC_DATA_SOURCES, {"cible": table})
        for chaine, flux, source in rows:
            bases = tables_of.get(source, [source])
            todo = [b for b in bases if b not in seen]
            lines.append(fmt.dependency_line(depth, source, bases, chaine, flux, bool(todo)))
            seen.update(todo)
            for base in todo if recursif else []:
                walk(base, depth + 1)

    walk(table_cible.strip().upper(), 0)
    return fmt.dependencies_report(table_cible, lines)
