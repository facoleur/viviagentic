"""Lecture des operations ELT (V_M_OPERATION des schemas *INT), partagee par les tools."""

from vivia.oracle import client
from vivia.tools.explore import queries


def fetch_operations(
    where: list[str], params: dict, last_col: str = "sql_text", max_rows: int = 1000
) -> list[tuple]:
    """(chaine, flux, operation_nr, description, table_cible, `last_col`), filtres en AND."""
    sql = queries.OPERATIONS.format(
        cols=f"{queries.OPERATION_COLUMNS}, {last_col}", where=" AND ".join(where) or "1 = 1"
    )
    return client.fetch(sql, params, max_rows=max_rows)[1]


def by_flux(flux: str, operation_nr: int | None, chaine: str | None) -> tuple[list[str], dict]:
    """Filtre (where, binds) sur un flux, et si donnes sur un numero d'operation et une chaine."""
    where, params = ["flux = :flux"], {"flux": flux.strip().upper()}
    if operation_nr is not None:
        where.append("operation_nr = :nr")
        params["nr"] = operation_nr
    if chaine:
        where.append("chaine = :chaine")
        params["chaine"] = chaine.strip().upper()
    return where, params


def in_list(column: str, values: list[str], params: dict) -> str:
    """`column IN (:column_0, ...)`, en ajoutant les binds (en majuscules) a `params`."""
    names = [f"{column}_{i}" for i in range(len(values))]
    params.update({n: v.strip().upper() for n, v in zip(names, values, strict=True)})
    return f"{column} IN ({', '.join(':' + n for n in names)})"
