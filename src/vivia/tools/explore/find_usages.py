"""Qui utilise un objet : dependances PL/SQL et source citant son nom."""

from vivia.oracle import client
from vivia.oracle.identifiers import ResolutionError, resolve

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
        "SELECT owner, name, type FROM all_dependencies "
        "WHERE referenced_owner = :owner AND referenced_name = :name FETCH FIRST :lim ROWS ONLY",
        {"owner": obj.schema, "name": obj.name, "lim": _LIMIT},
    )
    lines = [f"## Dependances de {obj}"]
    if deps:
        lines += [f"- `{o}.{n}` ({t})" for o, n, t in deps]
    else:
        lines.append(
            "Aucune trouvee dans ALL_DEPENDENCIES — soit aucun code PL/SQL visible ne le cite, "
            "soit l'acces a cette vue est restreint pour ce compte."
        )

    _, source = client.fetch(
        "SELECT owner, name, type, line FROM all_source WHERE UPPER(text) LIKE :needle "
        "FETCH FIRST :lim ROWS ONLY",
        {"needle": f"%{obj.name}%", "lim": _LIMIT},
    )
    lines += ["", f"## Code source citant {obj.name}"]
    if source:
        lines += [f"- `{o}.{n}` ({t}), ligne {line}" for o, n, t, line in source]
    else:
        lines.append(
            "Aucune occurrence dans ALL_SOURCE — soit aucun objet PL/SQL ne le cite, soit "
            "l'acces a cette vue est restreint pour ce compte."
        )

    lines += ["", "Operations ELT qui le citent : pas encore disponible (index phase 2)."]
    return "\n".join(lines)
