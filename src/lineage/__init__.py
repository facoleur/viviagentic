"""Lineage SQL Oracle (niveau table pour l'instant) a partir de scripts, via sqlglot.

Les templates `#NOM#` ne sont pas du SQL : ils sont masques en `TPL#NOM#` (Oracle accepte `#`
dans un identifiant, pas en premiere position) avant le parsing, puis restitues dans les noms.
"""

import re
import sys
from pathlib import Path

import sqlglot
from sqlglot import exp

_TPL = re.compile(r"#(\w+)#")
_MASK = re.compile(r"TPL#(\w+)#")


def _name(table: exp.Table) -> str:
    return _MASK.sub(r"#\1#", ".".join(p.name for p in table.parts)).upper()


def lineage(sql: str) -> list[dict[str, str]]:
    """Aretes source -> cible, au format du tool MCP `graph`."""
    edges = {}
    for stmt in sqlglot.parse(_TPL.sub(r"TPL#\1#", sql), read="oracle"):
        if not isinstance(stmt, exp.Insert | exp.Merge | exp.Update | exp.Create):
            continue
        target = _name(stmt.this.find(exp.Table))
        skip = {target} | {c.alias_or_name.upper() for c in stmt.find_all(exp.CTE)}
        for src in map(_name, stmt.find_all(exp.Table)):
            if src not in skip:
                edges[src, target] = None
    return [{"source": s, "target": t} for s, t in edges]


def main() -> None:
    for e in lineage(Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()):
        print(f"{e['source']} -> {e['target']}")
