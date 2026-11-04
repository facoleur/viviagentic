"""Lineage SQL Oracle, niveau table ou colonne, a partir de scripts, via sqlglot.

Les templates `#NOM#` ne sont pas du SQL : ils sont masques en `TPL#NOM#` (Oracle accepte `#`
dans un identifiant, pas en premiere position) avant le parsing, puis restitues dans les noms.
"""

import argparse
import html
import re
import sys
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage as _column_lineage
from sqlglot.optimizer.qualify import qualify

_TPL = re.compile(r"#(\w+)#")
_MASK = re.compile(r"TPL#(\w+)#")
_WRITES = exp.Insert | exp.Merge | exp.Update | exp.Create


def _unmask(name: str) -> str:
    return _MASK.sub(r"#\1#", name).upper()


def _name(table: exp.Table) -> str:
    return _unmask(".".join(p.name for p in table.parts))


def _query(stmt: exp.Expr) -> tuple[exp.Query | None, list[str] | None]:
    """Requete dont la i-eme sortie alimente la i-eme colonne cible, et ces colonnes (None :
    celles de la requete, une fois les `*` developpes)."""
    if isinstance(stmt, exp.Update):
        sets = stmt.expressions
        query = exp.select(*(e.expression for e in sets)).from_(stmt.this)
        return query, [e.this.name for e in sets]
    if isinstance(stmt, exp.Merge):
        pairs = []
        for then in (w.args["then"] for w in stmt.args["whens"].expressions):
            if isinstance(then, exp.Update):
                pairs += [(e.this, e.expression) for e in then.expressions]
            elif isinstance(then, exp.Insert) and then.this:
                pairs += zip(then.this.expressions, then.expression.expressions, strict=False)
        query = exp.select(*(v for _, v in pairs)).from_(stmt.args["using"])
        return query.join(stmt.this, on=stmt.args["on"]), [c.name for c, _ in pairs]
    query = stmt.expression
    if not isinstance(query, exp.Query):
        return None, None
    schema = stmt.this if isinstance(stmt.this, exp.Schema) else None
    return query, [c.name for c in schema.expressions] if schema else None


def lineage(
    sql: str, columns: bool = False, schema: dict | None = None, target: str | None = None
) -> list[dict[str, str]]:
    """Aretes source -> cible, au format du tool MCP `graph`.

    `columns=True` donne des noeuds `TABLE.COLONNE`. `schema` (format sqlglot, noms masques)
    permet de developper les `SELECT *` ; sans lui, ils restent des colonnes `*`.
    `target` : table alimentee par les `SELECT` seuls, quand c'est l'outil ETL qui les ecrit
    (lus comme `CREATE TABLE <target> AS SELECT ...`) ; sans lui, ils sont ignores.
    """
    edges = {}
    for stmt in sqlglot.parse(_TPL.sub(r"TPL#\1#", sql), read="oracle"):
        if target and isinstance(stmt, exp.Query):
            table = exp.to_table(_TPL.sub(r"TPL#\1#", target), dialect="oracle")
            stmt = exp.Create(this=table, kind="TABLE", expression=stmt)
        if not isinstance(stmt, _WRITES):
            continue
        out = _name(stmt.this.find(exp.Table))
        if not columns:
            skip = {out} | {c.alias_or_name.upper() for c in stmt.find_all(exp.CTE)}
            edges |= {(s, out): None for s in map(_name, stmt.find_all(exp.Table)) if s not in skip}
            continue
        query, cols = _query(stmt.copy())
        if query is None:
            continue
        for c in list(query.find_all(exp.Column)):  # `SELECT #pndate#` : une valeur
            if not c.table and _MASK.fullmatch(c.name):
                c.replace(exp.Literal.string(_unmask(c.name)))
        opts = {"validate_qualify_columns": False, "identify": False}
        query = qualify(query, schema=schema or {}, dialect="oracle", **opts)
        cols = cols or query.named_selects
        keys = []  # alias positionnels (doublons, expressions sans nom), sauf `*` non resolu
        for i, sel in enumerate(query.selects):
            keys.append("*" if isinstance(sel, exp.Star) else f"C{i}")
            if keys[-1] != "*":
                sel.replace(exp.alias_(sel.unalias(), keys[-1]))
        nodes = _column_lineage(None, query, schema or {}, dialect="oracle")
        for key, col in zip(keys, cols, strict=False):
            dst = f"{out}.{_unmask(col)}"
            for leaf in nodes[key].walk():
                if not leaf.downstream and isinstance(leaf.expression, exp.Table):
                    name = _unmask(leaf.name.rsplit(".", 1)[-1].strip('"'))
                    edges[f"{_name(leaf.expression)}.{name}", dst] = None
    return [{"source": s, "target": t} for s, t in edges]


def to_html(edges: list[dict[str, str]], columns: bool = False, title: str = "Lineage") -> str:
    """Page autonome (Mermaid via CDN) ; en mode colonne, une boite par table."""
    ids: dict[str, str] = {}
    tables: dict[str, list[str]] = {}
    for node in (n for e in edges for n in (e["source"], e["target"])):
        if node not in ids:
            ids[node] = f"n{len(ids)}"
            tables.setdefault(node.rsplit(".", 1)[0] if columns else node, []).append(node)

    def label(text: str) -> str:
        return '"' + html.escape(text).replace("#", "#35;") + '"'

    lines = ["flowchart LR"]
    for i, (table, nodes) in enumerate(tables.items()):
        if columns:
            lines.append(f"  subgraph t{i}[{label(table)}]")
            lines += [f"    {ids[n]}[{label(n.rsplit('.', 1)[-1])}]" for n in nodes]
            lines.append("  end")
        else:
            lines.append(f"  {ids[table]}[{label(table)}]")
    lines += [f"  {ids[e['source']]} --> {ids[e['target']]}" for e in edges]
    return f"""<!doctype html>
<meta charset="utf-8"><title>{html.escape(title)}</title>
<pre class="mermaid">
{chr(10).join(lines)}
</pre>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs";
mermaid.initialize({{startOnLoad: true, maxTextSize: 1e7, maxEdges: 1e5}});
</script>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Lineage d'un script SQL Oracle.")
    parser.add_argument("script", nargs="?", type=Path, help="fichier SQL (stdin par defaut)")
    parser.add_argument("-c", "--columns", action="store_true", help="lineage par colonne")
    parser.add_argument("--html", type=Path, help="ecrit le graphe dans cette page HTML")
    parser.add_argument(
        "-t", "--target", help="cible des SELECT seuls (defaut : nom du fichier sans extension)"
    )
    args = parser.parse_args()
    sql = args.script.read_text() if args.script else sys.stdin.read()
    target = args.target or (args.script.stem if args.script else None)
    edges = lineage(sql, columns=args.columns, target=target)
    if args.html:
        args.html.write_text(to_html(edges, args.columns, args.script.name if args.script else ""))
    for e in edges:
        print(f"{e['source']} -> {e['target']}")
