"""Fiche complete d'une table ou vue, en un seul appel."""

from vivia.oracle import client
from vivia.oracle.identifiers import ResolutionError, resolve

_ZONES = {"SDA": "sources", "SDE": "donnees transformees", "DMD": "data marts"}
_TYPES = {"STG": "staging", "TRG": "cibles", "INT": "vues d'interface"}


def _zone_type(schema: str) -> str:
    for zone, zone_label in _ZONES.items():
        for kind, kind_label in _TYPES.items():
            if schema == f"{zone}{kind}":
                return f"{zone} ({zone_label}) / {kind} ({kind_label})"
    return "zone/type non reconnus (hors convention SDA/SDE/DMD x STG/TRG/INT)"


def describe_table(name: str) -> str:
    """Fiche d'une table ou vue : colonnes, cle, index uniques, partitionnement, volumetrie, zone.

    Accepte "SCHEMA.TABLE" ou un nom seul (ambiguite levee si plusieurs schemas correspondent).
    Les operations qui l'alimentent (index hors ligne) et sa fiche de doc arriveront plus tard.

    Exemple : describe_table("DMDTRG.D_TIERS")
    """
    try:
        obj = resolve(name)
    except ResolutionError as err:
        return f"Erreur : {err}"

    _, cols = client.fetch(
        """
        SELECT c.column_name, c.data_type, c.nullable, m.comments
        FROM all_tab_columns c
        LEFT JOIN all_col_comments m
          ON m.owner = c.owner AND m.table_name = c.table_name AND m.column_name = c.column_name
        WHERE c.owner = :owner AND c.table_name = :name
        ORDER BY c.column_id
        """,
        {"owner": obj.schema, "name": obj.name},
    )
    if not cols:
        return f"Erreur : {obj} introuvable. Utiliser search_objects pour verifier le nom."

    lines = [f"## {obj}", "", f"Zone/type : {_zone_type(obj.schema)}", "", "### Colonnes"]
    lines += [
        f"- `{c}` {t}{' NULL' if n == 'Y' else ' NOT NULL'}{f' — {m}' if m else ''}"
        for c, t, n, m in cols
    ]

    _, pk = client.fetch(
        """
        SELECT acc.column_name
        FROM all_constraints ac JOIN all_cons_columns acc
          ON acc.owner = ac.owner AND acc.constraint_name = ac.constraint_name
        WHERE ac.owner = :owner AND ac.table_name = :name AND ac.constraint_type = 'P'
        ORDER BY acc.position
        """,
        {"owner": obj.schema, "name": obj.name},
    )
    if pk:
        lines += ["", "### Cle primaire", ", ".join(c for (c,) in pk)]

    _, uniques = client.fetch(
        """
        SELECT ai.index_name, aic.column_name
        FROM all_indexes ai JOIN all_ind_columns aic
          ON aic.index_owner = ai.owner AND aic.index_name = ai.index_name
        WHERE ai.owner = :owner AND ai.table_name = :name AND ai.uniqueness = 'UNIQUE'
        ORDER BY ai.index_name, aic.column_position
        """,
        {"owner": obj.schema, "name": obj.name},
    )
    if uniques:
        groups: dict[str, list[str]] = {}
        for idx, col in uniques:
            groups.setdefault(idx, []).append(col)
        lines += ["", "### Index uniques"]
        lines += [f"- `{idx}` ({', '.join(cs)})" for idx, cs in groups.items()]

    _, part = client.fetch(
        "SELECT partitioned, num_rows, last_analyzed FROM all_tables "
        "WHERE owner = :owner AND table_name = :name",
        {"owner": obj.schema, "name": obj.name},
    )
    if part:
        partitioned, num_rows, last_analyzed = part[0]
        partitioning = "aucun"
        if partitioned == "YES":
            _, kind = client.fetch(
                "SELECT partitioning_type FROM all_part_tables "
                "WHERE owner = :owner AND table_name = :name",
                {"owner": obj.schema, "name": obj.name},
            )
            partitioning = kind[0][0] if kind else "oui (type inconnu)"
        lines += [
            "",
            "### Volumetrie",
            f"partitionnement : {partitioning} ; "
            f"num_rows : {num_rows if num_rows is not None else 'non analyse'} ; "
            f"last_analyzed : {last_analyzed or 'jamais'}",
        ]
    else:
        _, view_text = client.fetch(
            "SELECT text FROM all_views WHERE owner = :owner AND view_name = :name",
            {"owner": obj.schema, "name": obj.name},
        )
        if view_text:
            lines += ["", "### Vue (ce qu'elle lit)", f"```sql\n{view_text[0][0]}\n```"]

    return "\n".join(lines)
