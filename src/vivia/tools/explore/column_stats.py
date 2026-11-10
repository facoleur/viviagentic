"""Statistiques par colonne : COUNT DISTINCT, nulls, min/max, calcules en reel sur la table.

ALL_TAB_COL_STATISTICS n'est pas utilise : ces tables ETL ne sont jamais `ANALYZE`, le
catalogue y est systematiquement vide. Un appel identique (table, colonnes, filtre) ne
retape pas la base : mis en cache en memoire, borne pour ne pas grossir indefiniment.
"""

from functools import lru_cache

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, ensure_identifier, resolve
from vivia.oracle.sql_guard import RejectedSQL, ensure_safe_fragment
from vivia.tools.explore import queries


@lru_cache(maxsize=256)
def _fetch_stats(obj: str, cols: tuple[str, ...], filtre: str) -> tuple[list[str], list[tuple]]:
    selects = ", ".join(
        f"COUNT(DISTINCT {c}) {c}_D, SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) {c}_N, "
        f"MIN({c}) {c}_LO, MAX({c}) {c}_HI"
        for c in cols
    )
    return client.fetch(queries.COLUMN_STATS_LIVE.format(selects=selects, obj=obj, filtre=filtre))


def column_stats(table: str, colonnes: list[str], filtre: str | None = None) -> str:
    """Stats reelles par colonne (distinctes, nulls, min, max) ; `filtre` restreint le calcul.

    Exemple : column_stats("DMDTRG.D_TIERS", ["segment", "pays"])
    """
    try:
        obj = resolve(table)
        cols = tuple(ensure_identifier(c) for c in colonnes)
        if filtre:
            ensure_safe_fragment(filtre)
    except (ResolutionError, ValueError, RejectedSQL) as err:
        return f"Erreur : {err}"

    columns, rows = _fetch_stats(str(obj), cols, filtre or "1=1")
    return fmt.column_stats_live(cols, columns, rows)
