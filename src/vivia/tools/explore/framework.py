"""Vues du framework ETL : schemas decouverts dans le dictionnaire, colonnes verifiees."""

from functools import cache

from vivia.oracle import client
from vivia.tools.explore import queries

OPERATIONS = "V_M_OPERATION"
TRAC_DATA = "V_M_TRAC_DATA"
FLOWDATA = "V_M_FLOWDATA"

# Schemas lus pour les vues du framework (SDA n'en a pas). Les autres schemas qui exposent la
# meme vue sont ignores.
SCHEMAS = ("SDEINT", "DMDINT")

# Nom interne (celui des requetes des tools) -> colonne reelle de la vue, quand elle differe.
# Seul endroit a adapter : `union` selectionne `reelle AS interne`.
# target_table est sans schema ; target_schema peut etre un template (#schema#), non utilise.
COLUMNS: dict[str, dict[str, str]] = {
    OPERATIONS: {
        "chaine": "chain_name",
        "flux": "flow_name",
        "table_cible": "target_table",
        "sql_text": "operation",
    },
}


@cache
def schemas(view: str) -> tuple[str, ...]:
    """Schemas de `SCHEMAS` qui exposent `view`, verifies une fois dans ALL_VIEWS."""
    _, rows = client.fetch(queries.VIEW_OWNERS, {"name": view})
    owners = tuple(owner for (owner,) in rows if owner in SCHEMAS)
    if not owners:
        raise LookupError(f"vue {view} introuvable dans {', '.join(SCHEMAS)} (nom ou droits ?)")
    return owners


@cache
def columns_of(view: str) -> dict[str, tuple[str, ...]]:
    """{schema: colonnes reelles} de `view`, lues une fois dans ALL_TAB_COLUMNS."""
    _, rows = client.fetch(queries.VIEW_COLUMNS, {"name": view})
    return {s: tuple(c for o, c in rows if o == s) for s in schemas(view)}


def union(view: str, columns: str) -> str:
    """`view` de tous les schemas qui l'exposent, comme une seule source SQL.

    `columns` : noms internes separes par des virgules. Une colonne absente d'un schema donne une
    erreur qui liste les colonnes reelles, au lieu d'un ORA-00904 sans contexte.
    """
    wanted = [c.strip() for c in columns.split(",")]
    real = {c: COLUMNS.get(view, {}).get(c, c) for c in wanted}
    for schema, available in columns_of(view).items():
        missing = [r for r in real.values() if r.upper() not in available]
        if missing:
            raise LookupError(
                f"{schema}.{view} : colonne(s) {', '.join(missing)} absente(s). "
                f"Colonnes reelles : {', '.join(available)}. "
                "Adapter COLUMNS dans vivia/tools/explore/framework.py."
            )
    select = ", ".join(c if r == c else f"{r} AS {c}" for c, r in real.items())
    return " UNION ALL ".join(f"SELECT {select} FROM {s}.{view}" for s in schemas(view))
