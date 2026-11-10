"""Verifie qu'une requete SELECT/WITH se compilerait, sans jamais l'executer pour de vrai."""

import oracledb

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.sql_guard import RejectedSQL, ensure_single_select
from vivia.tools.explore import queries
from vivia.tools.explore import templates as sql_templates


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

    resolved = sql_templates.substitute(sql, templates)
    try:
        columns = client.describe(queries.COMPILE_SQL_PROBE.format(sql=resolved))
    except oracledb.DatabaseError as err:
        return fmt.compile_error(err, resolved)
    return fmt.compile_ok(columns)
