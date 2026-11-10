"""Execute un SELECT libre en lecture seule, borne en lignes et en temps."""

import oracledb

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.sql_guard import RejectedSQL, ensure_single_select

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

    capped = f"SELECT * FROM (\n{sql}\n) FETCH FIRST {int(max_rows)} ROWS ONLY"
    try:
        columns, rows = client.fetch(capped, max_rows=max_rows)
    except oracledb.DatabaseError as err:
        (error,) = err.args
        return f"{error.full_code} : {error.message.strip()}"

    rows = [tuple(_truncated(v) for v in row) for row in rows]
    return fmt.markdown_table(columns, rows, limit=max_rows)


def _truncated(value, limit: int = 200):
    text = str(value) if value is not None else None
    return text if text is None or len(text) <= limit else text[:limit] + "…"
