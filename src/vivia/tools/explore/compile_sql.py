"""Verifie qu'une requete SELECT/WITH se compilerait, sans jamais l'executer pour de vrai."""

import re

import oracledb

from vivia.oracle import client
from vivia.oracle.sql_guard import RejectedSQL, ensure_single_select

_TEMPLATE = re.compile(r"#(\w+)#")
_QUOTED_TEMPLATE = re.compile(r"'#(\w+)#'")

# Devine un defaut typé par le nom du template ; premiere regle qui correspond (configurable :
# ajouter une regle avant le fallback pour un prefixe maison, ex. r"^PN" pour #PNDATE#).
_DEFAULT_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"DATE|^PN", re.I), "20000101", "DATE '2000-01-01'"),
    (re.compile(r"NB|NUM|MONTANT|SEUIL|ID$", re.I), "0", "0"),
]
_DEFAULT_FALLBACK = ("X", "'X'")


def _default_for(name: str) -> tuple[str, str]:
    """(valeur entre guillemets, valeur nue) : le gabarit peut apparaitre dans l'un ou l'autre."""
    for pattern, quoted, bare in _DEFAULT_PATTERNS:
        if pattern.search(name):
            return quoted, bare
    return _DEFAULT_FALLBACK


def _substitute(sql: str, templates: dict[str, str] | None) -> str:
    templates = templates or {}

    def quoted(match: re.Match[str]) -> str:
        name = match[1]
        return f"'{templates[name]}'" if name in templates else f"'{_default_for(name)[0]}'"

    def bare(match: re.Match[str]) -> str:
        name = match[1]
        return str(templates[name]) if name in templates else _default_for(name)[1]

    return _TEMPLATE.sub(bare, _QUOTED_TEMPLATE.sub(quoted, sql))


def _locate(sql: str, offset: int) -> tuple[int, int, str]:
    """Ligne et colonne 1-based d'un offset Oracle, avec un extrait de 3 lignes autour."""
    head = sql[:offset]
    line = head.count("\n") + 1
    column = offset - (head.rfind("\n") + 1) + 1
    lines = sql.splitlines()
    extract = "\n".join(lines[max(0, line - 2) : line + 1])
    return line, column, extract


def compile_sql(sql: str, templates: dict[str, str] | None = None) -> str:
    """Valide un SELECT/WITH (templates #NOM# remplaces) sans l'executer ni lire une ligne.

    Renvoie les colonnes produites (nom, type), ou le code ORA-, la ligne/colonne dans le SQL
    d'origine et un extrait de 3 lignes. `templates` : {"NOM": "valeur"} ; les templates omis
    prennent un defaut typé par leur nom (date, nombre ou texte).

    Exemple : compile_sql("SELECT id FROM #SCH#.orders", {"SCH": "SDATRG"})
    """
    try:
        ensure_single_select(sql)
    except RejectedSQL as err:
        return f"Rejete : {err}"

    resolved = _substitute(sql, templates)
    probe = f"SELECT * FROM (\n{resolved}\n) WHERE 1 = 0 FETCH FIRST 0 ROWS ONLY"
    try:
        columns = client.describe(probe)
    except oracledb.DatabaseError as err:
        (error,) = err.args
        line, column, extract = _locate(resolved, getattr(error, "offset", 0) or 0)
        return (
            f"{error.full_code} a la ligne {line}, colonne {column} :\n{error.message.strip()}\n\n"
            f"```\n{extract}\n```"
        )
    return "OK — colonnes : " + ", ".join(f"{name} ({kind})" for name, kind in columns)
