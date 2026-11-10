"""Verifie le grain d'une table sur un jeu de colonnes : lignes, cles distinctes, doublons."""

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, ensure_identifier, resolve
from vivia.oracle.sql_guard import RejectedSQL, ensure_safe_fragment

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

    _, size = client.fetch(
        "SELECT num_rows FROM all_tables WHERE owner = :o AND table_name = :t",
        {"o": obj.schema, "t": obj.name},
    )
    num_rows = size[0][0] if size and size[0][0] is not None else None
    if num_rows and num_rows > _FILTER_REQUIRED_ABOVE and not filtre:
        return (
            f"Erreur : {obj} fait ~{num_rows:,} lignes, un filtre est obligatoire "
            f"au-dela de {_FILTER_REQUIRED_ABOVE:,}."
        )

    where = f"WHERE {filtre}" if filtre else ""
    _, counts = client.fetch(f"SELECT COUNT(*), COUNT(DISTINCT {keys}) FROM {obj} {where}")
    total, distinct = counts[0]
    lines = [f"lignes : {total} — cles distinctes ({keys}) : {distinct}"]
    if total != distinct:
        cols, dups = client.fetch(
            f"SELECT {keys}, COUNT(*) occurrences FROM {obj} {where} "
            f"GROUP BY {keys} HAVING COUNT(*) > 1 FETCH FIRST 5 ROWS ONLY"
        )
        lines += ["", "### Exemples de doublons", fmt.markdown_table(cols, dups, limit=5)]
    return "\n".join(lines)
