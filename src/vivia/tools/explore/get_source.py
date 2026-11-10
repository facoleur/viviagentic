"""Code source PL/SQL stocke (ALL_SOURCE), par pages de 200 lignes."""

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError, resolve
from vivia.tools.explore import queries

_PAGE = 200


def get_source(objet: str, de_ligne: int = 1, a_ligne: int | None = None) -> str:
    """Code source d'un objet PL/SQL stocke (package, procedure, fonction, trigger).

    200 lignes au maximum par appel ; rappeler avec `de_ligne` pour la suite.

    Exemple : get_source("PKG_CHARGEMENT", de_ligne=201)
    """
    try:
        obj = resolve(objet)
    except ResolutionError as err:
        return f"Erreur : {err}"

    haut = min(a_ligne if a_ligne is not None else de_ligne + _PAGE - 1, de_ligne + _PAGE - 1)
    _, rows = client.fetch(
        queries.GET_SOURCE,
        {"owner": obj.schema, "name": obj.name, "lo": de_ligne, "hi": haut},
        max_rows=_PAGE,
    )
    if not rows:
        return fmt.no_source_lines(obj, de_ligne, haut)
    return fmt.source_page(obj, de_ligne, haut, rows)
