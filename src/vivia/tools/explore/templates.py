"""Substitution des gabarits `#NOM#` de `compile_sql` par une valeur par defaut typee."""

import re
from datetime import date, timedelta

_TEMPLATE = re.compile(r"#(\w+)#")
_QUOTED_TEMPLATE = re.compile(r"'#(\w+)#'")

_IS_DATE = re.compile(r"DATE|^PN", re.I)
_IS_NUMBER = re.compile(r"NB|NUM|MONTANT|SEUIL|ID$", re.I)


def _default_for(name: str) -> tuple[str, str]:
    """(valeur entre guillemets, valeur nue) : le gabarit peut apparaitre dans l'un ou l'autre."""
    if _IS_DATE.search(name):
        # La plupart des traitements batch tournent sur J-1 : un defaut fixe
        # (ex. 2000-01-01) ne compile jamais rien de representatif.
        d = date.today() - timedelta(days=1)
        return d.strftime("%Y%m%d"), f"DATE '{d.isoformat()}'"
    if _IS_NUMBER.search(name):
        return "0", "0"
    return "X", "'X'"


def substitute(sql: str, values: dict[str, str] | None) -> str:
    values = values or {}

    def quoted(match: re.Match[str]) -> str:
        name = match[1]
        return f"'{values[name]}'" if name in values else f"'{_default_for(name)[0]}'"

    def bare(match: re.Match[str]) -> str:
        name = match[1]
        return str(values[name]) if name in values else _default_for(name)[1]

    return _TEMPLATE.sub(bare, _QUOTED_TEMPLATE.sub(quoted, sql))
