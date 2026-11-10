"""Qui utilise un objet : dependances PL/SQL et source citant son nom."""

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, resolve
from vivia.tools.explore import queries

_LIMIT = 20


def find_usages(name: str) -> str:
    """Dependances PL/SQL (ALL_DEPENDENCIES) et code source citant `name` (ALL_SOURCE).

    Les operations ELT qui le citent arriveront avec l'index hors ligne (phase 2).

    Exemple : find_usages("D_TIERS")
    """
    try:
        obj = resolve(name)
    except ResolutionError as err:
        return f"Erreur : {err}"

    _, deps = client.fetch(
        queries.FIND_USAGES_DEPENDENCIES, {"owner": obj.schema, "name": obj.name, "lim": _LIMIT}
    )
    _, source = client.fetch(queries.FIND_USAGES_SOURCE, {"needle": f"%{obj.name}%", "lim": _LIMIT})
    return fmt.find_usages_report(obj, deps, source)
