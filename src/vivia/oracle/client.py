"""Connexion Oracle en lecture seule, une connexion par appel.

Toute la configuration vient de l'environnement, comme `PORT` dans
`vivia.mcp.server` : `ORACLE_DSN`, `ORACLE_USER`, `ORACLE_PASSWORD` (obligatoires),
`ORACLE_CALL_TIMEOUT_MS` et `ORACLE_MAX_ROWS` (optionnels). Le compte est
suppose lecture seule (SELECT) ; ce module n'execute jamais de DDL/DML.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import oracledb

CALL_TIMEOUT_MS = int(os.getenv("ORACLE_CALL_TIMEOUT_MS", "30000"))
MAX_ROWS = int(os.getenv("ORACLE_MAX_ROWS", "500"))


@contextmanager
def connection() -> Generator[oracledb.Connection]:
    """Une connexion par appel : ces outils servent un agent a la fois, pas un pool partage."""
    conn = oracledb.connect(
        dsn=os.environ["ORACLE_DSN"],
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
    )
    conn.call_timeout = CALL_TIMEOUT_MS
    try:
        yield conn
    finally:
        conn.close()


def fetch(
    sql: str, params: dict[str, Any] | None = None, max_rows: int = MAX_ROWS
) -> tuple[list[str], list[tuple]]:
    """Execute un SELECT deja valide ; renvoie (colonnes, lignes), plafonne a `max_rows`."""
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params or {})
        columns = [d[0] for d in cursor.description]
        return columns, cursor.fetchmany(max_rows)


def describe(sql: str, params: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Execute `sql` sans tirer de ligne ; renvoie (nom, type) de chaque colonne produite.

    Sert a valider une requete (tables/colonnes/types) sans jamais lire de donnees :
    l'appelant est responsable de bloquer les lignes en amont (ex. `WHERE 1 = 0`).
    """
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params or {})
        return [(d[0], d[1].name.removeprefix("DB_TYPE_")) for d in cursor.description]
