"""Statistiques par colonne : distinctes, nulls, min/max (catalogue, ou calcul reel filtre)."""

import oracledb

from vivia.oracle import client
from vivia.oracle.identifiers import ResolutionError, ensure_identifier, resolve
from vivia.oracle.sql_guard import RejectedSQL, ensure_safe_fragment

_OUT_TYPE_BY_DATA_TYPE = {"DATE": oracledb.DB_TYPE_DATE, "NUMBER": oracledb.DB_TYPE_NUMBER}


def column_stats(table: str, colonnes: list[str], filtre: str | None = None) -> str:
    """Stats par colonne : ALL_TAB_COL_STATISTICS sans filtre, calcul reel si `filtre` est fourni.

    Exemple : column_stats("DMDTRG.D_TIERS", ["segment", "pays"])
    """
    try:
        obj = resolve(table)
        cols = [ensure_identifier(c) for c in colonnes]
        if filtre:
            ensure_safe_fragment(filtre)
    except (ResolutionError, ValueError, RejectedSQL) as err:
        return f"Erreur : {err}"

    return _live(obj, cols, filtre) if filtre else _catalog(obj, cols)


def _catalog(obj, cols: list[str]) -> str:
    placeholders = ", ".join(f":c{i}" for i in range(len(cols)))
    params = {f"c{i}": c for i, c in enumerate(cols)}
    _, rows = client.fetch(
        f"""
        SELECT s.column_name, t.data_type, s.num_distinct, s.num_nulls, s.low_value, s.high_value
        FROM all_tab_col_statistics s JOIN all_tab_columns t
          ON t.owner = s.owner AND t.table_name = s.table_name AND t.column_name = s.column_name
        WHERE s.owner = :owner AND s.table_name = :table AND s.column_name IN ({placeholders})
        """,
        {"owner": obj.schema, "table": obj.name, **params},
    )
    if not rows:
        return (
            f"Pas de statistiques pour {obj} (jamais analysee ?). "
            "Fournir un `filtre` pour un calcul reel."
        )
    return "\n".join(
        f"- `{col}` : {distinct} distinctes, {nulls} nulls{_decoded(data_type, low, high)}"
        for col, data_type, distinct, nulls, low, high in rows
    )


def _decoded(data_type: str, low: bytes | None, high: bytes | None) -> str:
    if low is None or high is None or not client.has_dbms_stats_convert_raw():
        return ""
    out_type = _OUT_TYPE_BY_DATA_TYPE.get(data_type, oracledb.DB_TYPE_VARCHAR)
    try:
        lo = client.convert_raw(low, out_type)
        hi = client.convert_raw(high, out_type)
        return f", min={lo}, max={hi}"
    except oracledb.DatabaseError:
        return ""


def _live(obj, cols: list[str], filtre: str) -> str:
    selects = ", ".join(
        f"COUNT(DISTINCT {c}) {c}_D, SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) {c}_N, "
        f"MIN({c}) {c}_LO, MAX({c}) {c}_HI"
        for c in cols
    )
    columns, rows = client.fetch(f"SELECT {selects} FROM {obj} WHERE {filtre}")
    row = dict(zip(columns, rows[0], strict=True)) if rows else {}
    return "\n".join(
        f"- `{c}` : {row.get(f'{c}_D')} distinctes, {row.get(f'{c}_N')} nulls, "
        f"min={row.get(f'{c}_LO')}, max={row.get(f'{c}_HI')}"
        for c in cols
    )
