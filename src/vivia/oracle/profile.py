"""Profil d'une table ou vue calcule a la main sur un echantillon : les statistiques Oracle
(NUM_ROWS, ALL_TAB_COL_STATISTICS) sont vides sur ces tables.

Une requete d'agregats par lot de colonnes (nulls, valeurs distinctes, min, max), puis une seule
requete GROUPING SETS pour les valeurs frequentes des colonnes de codes.
"""

from datetime import date
from functools import lru_cache

import oracledb

from vivia.oracle import client

SAMPLE = "SELECT * FROM {obj} SAMPLE BLOCK (1) SEED (42) FETCH FIRST 100000 ROWS ONLY"
FIRST = "SELECT * FROM {obj} FETCH FIRST 100000 ROWS ONLY"
MIN_SAMPLE = 1000  # en dessous, l'echantillon par blocs est maigre : on lit le debut de la table
BATCH = 120  # colonnes par requete (6 expressions chacune ; Oracle limite a 1000 par requete)
MAX_VALUES = 30  # au plus 30 valeurs distinctes : une colonne de codes, dont on liste les valeurs
MAX_CODES = 40  # colonnes de codes dont on liste les valeurs
TIMEOUT = 20  # secondes par requete

# Valeurs « bouchon » mises a la place d'un NULL (a completer avec celles de la banque).
SENTINELS = {"N/A", "NA", "ND", "N.D.", "NULL", "INCONNU", "UNKNOWN", "-", "?", "-1"}

_NUMBER = {"NUMBER", "FLOAT", "INTEGER", "BINARY_FLOAT", "BINARY_DOUBLE"}
_TEXT = {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"}
_EXTRA = {  # 2 mesures par type : negatifs et zeros / dates sentinelles haute et basse
    "num": ("SUM(CASE WHEN {q} < 0 THEN 1 ELSE 0 END)", "SUM(CASE WHEN {q} = 0 THEN 1 ELSE 0 END)"),
    "date": (
        "SUM(CASE WHEN {q} >= DATE '9999-01-01' THEN 1 ELSE 0 END)",
        "SUM(CASE WHEN {q} <= DATE '1900-01-01' THEN 1 ELSE 0 END)",
    ),
    "text": ("NULL", "NULL"),
}


def kind(data_type: str) -> str | None:
    """num, date ou text ; None pour les types non profilables (LOB, XMLTYPE, objets...)."""
    if data_type in _NUMBER:
        return "num"
    if data_type == "DATE" or data_type.startswith("TIMESTAMP"):
        return "date"
    return "text" if data_type in _TEXT else None


def _stats(source: str, columns: list[tuple[str, str]]) -> tuple[int, dict]:
    """(lignes de l'echantillon, {colonne: mesures}) pour un lot de colonnes."""
    exprs = []
    for name, k in columns:
        q = f'"{name}"'
        exprs += [f"COUNT({q})", f"APPROX_COUNT_DISTINCT({q})", f"MIN({q})", f"MAX({q})"]
        exprs += [e.format(q=q) for e in _EXTRA[k]]
    sql = f"SELECT COUNT(*), {', '.join(exprs)} FROM ({source})"
    row = client.fetch(sql, max_seconds=TIMEOUT)[1][0]
    stats = {}
    for i, (name, k) in enumerate(columns):
        n, distinct, lo, hi, x, y = row[1 + 6 * i : 7 + 6 * i]
        stats[name] = {
            "kind": k, "non_null": n or 0, "distinct": distinct or 0, "min": lo, "max": hi,
            "x": x or 0, "y": y or 0, "values": [],
        }  # fmt: skip
    return row[0], stats


def _frequent(source: str, codes: list[str]) -> dict[str, list[tuple]]:
    """Les 5 valeurs les plus frequentes de chaque colonne de `codes`, en une seule passe."""
    cols = ", ".join(f'"{c}"' for c in codes)
    sets = ", ".join(f'("{c}")' for c in codes)
    flags = ", ".join(f'GROUPING("{c}")' for c in codes)
    sql = f"SELECT {cols}, COUNT(*), {flags} FROM ({source}) GROUP BY GROUPING SETS ({sets})"
    rows = client.fetch(sql, max_rows=5000, max_seconds=TIMEOUT)[1]
    found: dict[str, list[tuple]] = {c: [] for c in codes}
    for row in rows:
        for i, c in enumerate(codes):
            if row[len(codes) + 1 + i] == 0 and row[i] is not None:  # ligne du groupe de `c`
                found[c].append((row[i], row[len(codes)]))
    return {c: sorted(v, key=lambda x: -x[1])[:5] for c, v in found.items()}


def profile(owner: str, name: str, columns: tuple[tuple[str, str], ...]) -> dict | None:
    """{rows, sampled, columns: {colonne: mesures}} ; None si aucune colonne n'est profilable.

    L'echantillon (1 % des blocs, 100 000 lignes au plus) devient les 100 000 premieres lignes
    quand il est trop petit ou quand SAMPLE est refuse (vue complexe) : `sampled` le dit.
    """
    cols = [(c, k) for c, t in columns if (k := kind(t))]
    if not cols:
        return None
    batches = [cols[i : i + BATCH] for i in range(0, len(cols), BATCH)]
    for sampled, template in ((True, SAMPLE), (False, FIRST)):
        source = template.format(obj=f"{owner}.{name}")
        try:
            rows, stats = _stats(source, batches[0])
        except oracledb.DatabaseError:
            if not sampled:
                raise
            continue  # ex. ORA-01446 : pas de SAMPLE sur cette vue
        if rows >= MIN_SAMPLE or not sampled:
            break
    for batch in batches[1:]:
        stats |= _stats(source, batch)[1]
    codes = [c for c, s in stats.items() if 0 < s["distinct"] <= MAX_VALUES and s["kind"] != "date"]
    if rows and codes:
        for c, values in _frequent(source, codes[:MAX_CODES]).items():
            stats[c]["values"] = values
    return {"rows": rows, "sampled": sampled, "columns": stats}


@lru_cache(maxsize=64)
def _cached(owner: str, name: str, columns: tuple, day: str) -> dict | None:
    return profile(owner, name, columns)


def profile_of_the_day(owner: str, name: str, columns: tuple) -> dict | None:
    """Comme `profile`, garde en memoire pour la journee (donnees rechargees une fois par jour)."""
    return _cached(owner, name, columns, date.today().isoformat())
