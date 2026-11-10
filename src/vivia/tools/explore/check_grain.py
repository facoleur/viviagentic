"""Verifie le grain d'une table sur un jeu de colonnes : lignes, cles distinctes, doublons."""

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, ensure_identifier, resolve
from vivia.oracle.sql_guard import RejectedSQL, ensure_safe_fragment
from vivia.tools.explore import queries

_FILTER_REQUIRED_ABOVE = 1_000_000  # num_rows au-dela duquel un filtre devient obligatoire


def check_grain(table: str, colonnes_cle: list[str], filtre: str | None = None) -> str:
    """Compte les lignes et les cles distinctes sur `colonnes_cle`, et montre 5 doublons.

    `filtre` est une clause WHERE sans le mot-cle ; obligatoire au-dela d'une table volumineuse.

    Exemple : check_grain("DMDTRG.D_TIERS", ["id_tiers"])
    """
    try:
        obj = resolve(table)
        keys = ", ".join(ensure_identifier(c) for c in colonnes_cle)
        if filtre:
            ensure_safe_fragment(filtre)
    except (ResolutionError, ValueError, RejectedSQL) as err:
        return f"Erreur : {err}"

    _, size = client.fetch(queries.CHECK_GRAIN_NUM_ROWS, {"o": obj.schema, "t": obj.name})
    num_rows = size[0][0] if size and size[0][0] is not None else None
    if num_rows and num_rows > _FILTER_REQUIRED_ABOVE and not filtre:
        return fmt.too_many_rows(obj, num_rows, _FILTER_REQUIRED_ABOVE)

    where = f"WHERE {filtre}" if filtre else ""
    _, counts = client.fetch(queries.CHECK_GRAIN_COUNTS.format(keys=keys, obj=obj, where=where))
    total, distinct = counts[0]
    if total == distinct:
        return fmt.check_grain_report(keys, total, distinct)

    dup_sql = queries.CHECK_GRAIN_DUPLICATES.format(keys=keys, obj=obj, where=where)
    cols, dups = client.fetch(dup_sql)
    return fmt.check_grain_report(keys, total, distinct, cols, dups)
