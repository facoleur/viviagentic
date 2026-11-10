"""Code source PL/SQL stocke (ALL_SOURCE), par pages de 200 lignes."""

from vivia.oracle import client
from vivia.oracle.identifiers import ResolutionError, resolve

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

    haut = a_ligne if a_ligne is not None else de_ligne + _PAGE - 1
    haut = min(haut, de_ligne + _PAGE - 1)

    _, rows = client.fetch(
        "SELECT line, text FROM all_source WHERE owner = :owner AND name = :name "
        "AND line BETWEEN :lo AND :hi ORDER BY line",
        {"owner": obj.schema, "name": obj.name, "lo": de_ligne, "hi": haut},
        max_rows=_PAGE,
    )
    if not rows:
        return (
            f"Aucune ligne pour {obj} entre {de_ligne} et {haut} — objet inconnu d'ALL_SOURCE, "
            "deja termine, ou acces restreint pour ce compte."
        )
    body = "".join(text for _, text in rows)
    return f"```sql\n-- {obj}, lignes {de_ligne}-{haut}\n{body}```"
