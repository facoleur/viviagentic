"""Recherche de tables/vues par nom ou par commentaire, dans le dictionnaire Oracle standard."""

from vivia.oracle import client

_LIMIT = 20


def search_objects(texte: str, zone: str | None = None) -> str:
    """Cherche une table ou une vue par nom ou par commentaire. 20 resultats au maximum.

    `zone` filtre sur le prefixe de schema (ex. "DMD" -> DMDSTG/DMDTRG/DMDINT). Les fiches de
    documentation (phase 4) seront cherchees ici aussi une fois qu'elles existeront.

    Exemple : search_objects("tiers"), ou search_objects("flux", zone="SDE")
    """
    needle = f"%{texte.upper()}%"
    params: dict[str, str] = {"needle": needle}
    filter_t, filter_v = "", ""
    if zone:
        params["zone"] = f"{zone.upper()}%"
        filter_t, filter_v = "AND t.owner LIKE :zone", "AND v.owner LIKE :zone"

    _, rows = client.fetch(
        f"""
        SELECT owner, object_name, object_type, comments FROM (
          SELECT t.owner, t.table_name object_name, 'TABLE' object_type, c.comments
          FROM all_tables t LEFT JOIN all_tab_comments c
            ON c.owner = t.owner AND c.table_name = t.table_name
          WHERE t.table_name LIKE :needle {filter_t}
          UNION
          SELECT v.owner, v.view_name, 'VIEW', c.comments
          FROM all_views v LEFT JOIN all_tab_comments c
            ON c.owner = v.owner AND c.table_name = v.view_name
          WHERE v.view_name LIKE :needle {filter_v}
          UNION
          SELECT DISTINCT t.owner, t.table_name, 'TABLE (commentaire)', c.comments
          FROM all_col_comments c JOIN all_tables t
            ON t.owner = c.owner AND t.table_name = c.table_name
          WHERE c.comments LIKE :needle {filter_t}
        )
        ORDER BY owner, object_name
        """,
        params,
        max_rows=_LIMIT,
    )
    if not rows:
        return f"Aucun resultat pour « {texte} »" + (f" en zone {zone}" if zone else "")
    lines = [f"- `{o}.{n}` ({t}){f' — {c}' if c else ''}" for o, n, t, c in rows]
    if len(rows) >= _LIMIT:
        lines.append(f"\n… limite a {_LIMIT} resultats, preciser `zone` ou le texte.")
    return "\n".join(lines)
