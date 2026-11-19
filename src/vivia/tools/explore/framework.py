"""Vues du framework ETL : leurs schemas sont decouverts dans le dictionnaire, pas codes en dur."""

from functools import cache

from vivia.oracle import client
from vivia.tools.explore import queries

OPERATIONS = "V_M_OPERATION"
TRAC_DATA = "V_M_TRAC_DATA"
FLOWDATA = "V_M_FLOWDATA"


@cache
def schemas(view: str) -> tuple[str, ...]:
    """Schemas qui exposent `view` (ex. SDEINT, DMDINT), lus une fois dans ALL_VIEWS."""
    _, rows = client.fetch(queries.VIEW_OWNERS, {"view": view})
    if not rows:
        raise LookupError(f"vue {view} introuvable dans ALL_VIEWS (nom ou droits a verifier)")
    return tuple(owner for (owner,) in rows)


def union(view: str, columns: str) -> str:
    """`view` de tous les schemas qui l'exposent, comme une seule source SQL."""
    return " UNION ALL ".join(f"SELECT {columns} FROM {s}.{view}" for s in schemas(view))
