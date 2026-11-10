"""Garde commune a tout SQL libre : une seule instruction, de type SELECT ou WITH.

Les templates `#NOM#` du framework ELT sont masques avant l'analyse (sqlglot ne les
comprend pas tels quels) via `lineage.mask_templates` ; le SQL rendu reste inchange.
"""

import sqlglot
from sqlglot import exp

from lineage import mask_templates


class RejectedSQL(Exception):
    """Le SQL n'est pas une unique instruction SELECT/WITH : jamais execute."""


def ensure_single_select(sql: str) -> None:
    """Leve `RejectedSQL` si `sql` n'est pas une unique instruction SELECT ou WITH."""
    try:
        statements = [s for s in sqlglot.parse(mask_templates(sql), read="oracle") if s]
    except sqlglot.errors.ParseError as err:
        raise RejectedSQL(f"SQL illisible : {err}") from err
    if len(statements) != 1:
        raise RejectedSQL(f"une seule instruction attendue, {len(statements)} trouvee(s)")
    if not isinstance(statements[0], exp.Query):
        raise RejectedSQL("seuls SELECT et WITH sont acceptes (ni DDL, ni DML, ni PL/SQL)")


def ensure_safe_fragment(fragment: str) -> None:
    """Valide un fragment WHERE libre (filtre) en le rejouant comme clause d'un SELECT jouet.

    Leve `RejectedSQL` s'il empile une autre instruction (ex. `1=1; DROP TABLE x`).
    """
    ensure_single_select(f"SELECT 1 FROM dual WHERE {fragment}")
