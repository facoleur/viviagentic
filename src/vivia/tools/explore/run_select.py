"""Execute un SELECT libre en lecture seule, borne en lignes et en temps."""

import oracledb

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.sql_guard import RejectedSQL, ensure_single_select
from vivia.tools.explore import queries

_DEFAULT_MAX_ROWS = 50


def run_select(sql: str, max_rows: int = _DEFAULT_MAX_ROWS) -> str:
    """Execute un SELECT ou WITH deja ecrit, lecture seule. Une seule instruction (verifiee par
    sqlglot), `FETCH FIRST` ajoute automatiquement, delai maximal du compte applique.

    Exemple : run_select("SELECT * FROM DMDTRG.D_TIERS", max_rows=10)
    """
    try:
        ensure_single_select(sql)
    except RejectedSQL as err:
        return f"Rejete : {err}"

    try:
        capped = queries.RUN_SELECT_CAPPED.format(sql=sql, max_rows=int(max_rows))
        columns, rows = client.fetch(capped, max_rows=max_rows)
    except oracledb.DatabaseError as err:
        return fmt.oracle_error(err)
    return fmt.run_select_table(columns, rows, max_rows)
