"""Faits deterministes : tout ce que le code sait d'une table sans LLM."""

import re
from collections import Counter

from vivia.oracle.client import fetch
from vivia.retrodoc import sql

ALL = 10_000_000  # pas de plafond de lignes pour ces requetes
LOBS = ("CLOB", "NCLOB", "BLOB", "LONG", "XMLTYPE")
DOC_ZONES = ("SDA", "SDE")


def framework() -> dict:
    """TRAC_DATA (sources ramenees de la vue a la table) et frequence par flux, charges une fois."""
    _, views = fetch(sql.VIEWS, max_rows=ALL)
    table_of = dict(views)
    _, trac = fetch(sql.TRAC, max_rows=ALL)
    _, flows = fetch(sql.FLOWS, max_rows=ALL)
    return {
        "trac": [(ch, fl, cible, table_of.get(src, src)) for ch, fl, cible, src in trac],
        "frequence": {(ch, fl): freq for ch, fl, freq in flows},
    }


def strategic(fw: dict, n: int) -> dict[str, int]:
    """Les `n` tables SDA/SDE lues par le plus de flux : {table: nb de flux}."""
    reads = {(src, ch, fl) for ch, fl, _, src in fw["trac"] if src[:3] in DOC_ZONES}
    return dict(Counter(src for src, _, _ in reads).most_common(n))


def facts(table: str, fw: dict, glossary: dict[str, str]) -> dict:
    """Dictionnaire, profil, exemples, flux, SQL producteur et glossaire utile d'une table."""
    owner, name = table.split(".")
    cols = columns(table)
    _, pk = fetch(sql.PK, {"owner": owner, "name": name})
    _, comment = fetch(sql.TABLE_COMMENT, {"owner": owner, "name": name})
    _, ops = fetch(sql.OPERATIONS, {"t": table}, max_rows=ALL)
    sample, profiled = profile(table, cols)
    producers = sorted({(ch, fl) for ch, fl, _, cible, _ in ops if cible == table})
    sources = sorted({src for _, _, cible, src in fw["trac"] if cible == table})
    words = set(re.findall(r"[A-Z0-9]+", " ".join([table, *cols, *(op[4] or "" for op in ops)])))
    return {
        "table": table,
        "commentaire": comment[0][0] if comment else None,
        "pk": [r[0] for r in pk],
        "echantillon": sample,
        "colonnes": profiled,
        "exemples": examples(table),
        "producteurs": [
            {"flux": f"{ch}.{fl}", "frequence": fw["frequence"].get((ch, fl))}
            for ch, fl in producers
        ],
        "consommateurs": sorted({f"{ch}.{fl}" for ch, fl, _, src in fw["trac"] if src == table}),
        "sources": {s: [describe(c, t, m) for c, (t, m) in columns(s).items()] for s in sources},
        "operations": [
            {"flux": f"{ch}.{fl}", "ordre": ordre, "table_cible": cible, "sql": text}
            for ch, fl, ordre, cible, text in ops
        ],
        "glossaire": {k: v for k, v in glossary.items() if k.upper() in words},
    }


def columns(table: str) -> dict[str, tuple[str, str | None]]:
    """{colonne: (type, commentaire)} dans l'ordre de la table."""
    owner, name = table.split(".")
    _, rows = fetch(sql.COLUMNS, {"owner": owner, "name": name}, max_rows=ALL)
    return {c: (t, m) for c, t, m in rows}


def describe(col: str, typ: str, comment: str | None) -> str:
    return f"{col} {typ}" + (f" -- {comment}" if comment else "")


def profile(table: str, cols: dict) -> tuple[int, list[dict]]:
    """Taux de nulls et cardinalite sur 1 % des lignes ; toute la table si elle est petite."""
    measured = [c for c, (t, _) in cols.items() if t not in LOBS]
    stats = ", ".join(
        ["COUNT(*)", *(f'COUNT("{c}"), APPROX_COUNT_DISTINCT("{c}")' for c in measured)]
    )
    for source in (f"{table} SAMPLE (1)", table):
        _, [row] = fetch(sql.PROFILE.format(stats=stats, source=source))
        if row[0] >= 1000:
            break
    pairs = zip(row[1::2], row[2::2], strict=True)
    n, found = row[0], dict(zip(measured, pairs, strict=True))
    return n, [
        {
            "nom": c,
            "type": t,
            "commentaire": m,
            "taux_null": round(1 - found[c][0] / n, 3) if c in found and n else None,
            "cardinalite": found[c][1] if c in found else None,
        }
        for c, (t, m) in cols.items()
    ]


def examples(table: str) -> list[dict]:
    """5 lignes, valeurs tronquees : montre au LLM a quoi ressemblent les donnees."""
    names, rows = fetch(sql.EXAMPLES.format(table=table))
    return [
        {c: None if v is None else str(v)[:40] for c, v in zip(names, r, strict=True)} for r in rows
    ]
