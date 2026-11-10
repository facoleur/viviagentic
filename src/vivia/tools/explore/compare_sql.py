"""Compare le SQL d'une operation ELT (M_OPERATION) a une version optimisee : diff et duree."""

import time
from typing import Annotated

import oracledb
from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle.sql_guard import RejectedSQL, ensure_single_select
from vivia.tools.explore import queries
from vivia.tools.explore import templates as sql_templates

_DEFAULT_MAX_SECONDS = client.CALL_TIMEOUT_MS / 1000


class OperationNotFound(Exception):
    def __init__(self, flux: str, operation: int):
        super().__init__(f"operation introuvable : flux={flux}, id_operation={operation}")


class AmbiguousOperation(Exception):
    def __init__(self, flux: str, operation: int, schemas: list[str]):
        super().__init__(
            f"flux={flux}, id_operation={operation} existe dans plusieurs schemas "
            f"({', '.join(schemas)}) : M_OPERATION n'est pas encore indexe par chaine/appli."
        )


def _lookup_operation(flux: str, operation: int) -> str:
    """Cherche (flux, operation) dans M_OPERATION, quel que soit le schema qui le porte."""
    _, owners = client.fetch(queries.FIND_OPERATION_SCHEMAS)
    schemas = sorted(owner for (owner,) in owners)
    if not schemas:
        raise OperationNotFound(flux, operation)

    union = " UNION ALL ".join(queries.FIND_OPERATION_IN_SCHEMA.format(schema=s) for s in schemas)
    _, rows = client.fetch(union, {"flux": flux.upper(), "operation": operation})
    if not rows:
        raise OperationNotFound(flux, operation)
    if len(rows) > 1:
        raise AmbiguousOperation(flux, operation, [owner for owner, _ in rows])
    return rows[0][1]


def _is_timeout(err: oracledb.DatabaseError) -> bool:
    (error,) = err.args
    return "DPY-4024" in (getattr(error, "full_code", "") or str(error))


def _probe(sql: str, max_seconds: float) -> tuple[int, int, float]:
    """Execute `sql` en entier (compte + somme de controle), sans rapatrier une seule ligne."""
    probe_sql = queries.COMPARE_SQL_PROBE.format(sql=sql)
    start = time.perf_counter()
    _, rows = client.fetch(probe_sql, max_rows=1, max_seconds=max_seconds)
    duree = time.perf_counter() - start
    n, checksum = rows[0]
    return n or 0, checksum or 0, duree


def compare_sql(
    flux: Annotated[
        str, Field(description="Nom du flux ELT (M_OPERATION) dont on compare le SQL d'origine.")
    ],
    operation: Annotated[
        int, Field(description="Identifiant de l'operation (id_operation) dans le flux.")
    ],
    sql_optimise: Annotated[
        str,
        Field(
            description="Version optimisee du SQL a comparer a l'original (compte de lignes, "
            "somme de controle et duree de chaque version)."
        ),
    ],
    templates: Annotated[
        dict[str, str] | None,
        Field(description="Valeurs pour les templates #NOM# communs aux deux versions du SQL."),
    ] = None,
    max_seconds: Annotated[
        float,
        Field(
            description="Delai maximal en secondes accorde a l'execution de chaque version "
            "avant timeout.",
            gt=0,
        ),
    ] = _DEFAULT_MAX_SECONDS,
) -> str:
    """Compare le SQL d'une operation ELT (M_OPERATION) a une version optimisee.

    Retrouve le SQL d'origine via `flux` + `operation` (= id_operation), substitue les templates
    `#NOM#` sur les deux versions (comme `compile_sql`), puis execute chacune en entier (compte +
    somme de controle, sans rapatrier les lignes) pour comparer resultat et duree.

    `max_seconds` borne chaque execution (defaut : ORACLE_CALL_TIMEOUT_MS). Pour une operation
    sciemment longue (ex. 40 min) : itérer avec le defaut sur une version du SQL temporairement
    filtree/reduite, puis ne rappeler qu'une fois avec un `max_seconds` eleve, sans filtre, pour
    la mesure reelle avant de conclure.

    Exemple : compare_sql("TIERS", 1, "SELECT * FROM SDATRG.TIERS WHERE ...")
    """
    try:
        ensure_single_select(sql_optimise)
    except RejectedSQL as err:
        return f"Rejete : {err}"

    try:
        sql_original = _lookup_operation(flux, operation)
    except (OperationNotFound, AmbiguousOperation) as err:
        return f"Erreur : {err}"

    try:
        ensure_single_select(sql_original)
    except RejectedSQL as err:
        return f"Erreur : SQL d'origine invalide (M_OPERATION) : {err}"

    resolved_new = sql_templates.substitute(sql_optimise, templates)
    resolved_old = sql_templates.substitute(sql_original, templates)

    try:
        n_new, checksum_new, duree_new = _probe(resolved_new, max_seconds)
    except oracledb.DatabaseError as err:
        if _is_timeout(err):
            return fmt.compare_sql_timeout(max_seconds, nouveau=True)
        return fmt.compile_error(err, resolved_new)

    try:
        n_old, checksum_old, duree_old = _probe(resolved_old, max_seconds)
    except oracledb.DatabaseError as err:
        if _is_timeout(err):
            return fmt.compare_sql_timeout(max_seconds, nouveau=False)
        return fmt.compile_error(err, resolved_old)

    return fmt.compare_sql_report(n_old, checksum_old, duree_old, n_new, checksum_new, duree_new)
