"""Serveur MCP minimal : quelques tools jouets pour valider les tool calls.

Les trois derniers sont des MCP Apps : ils rendent une vue dans la conversation
au lieu de renvoyer du texte. Voir `vivia.ui` pour le contrat avec l'hote.
"""

import ast
import operator
import os
import random
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field

from vivia import ui

mcp = FastMCP("vivia")

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


@mcp.tool
def now(timezone: str = "UTC") -> str:
    """Date et heure courantes au format ISO 8601, dans le fuseau demandé."""
    tz = UTC if timezone.upper() == "UTC" else ZoneInfo(timezone)
    return datetime.now(tz).isoformat()


@mcp.tool
def calc(expression: str) -> float:
    """Évalue une expression arithmétique (+ - * / % **), sans variables ni appels."""

    def walk(node: ast.AST) -> float:
        match node:
            case ast.Constant(value=int() | float() as value):
                return value
            case ast.BinOp(op=op) if type(op) in _OPS:
                return _OPS[type(op)](walk(node.left), walk(node.right))
            case ast.UnaryOp(op=ast.USub()):
                return -walk(node.operand)
            case _:
                raise ValueError(f"expression non supportée : {ast.dump(node)}")

    return walk(ast.parse(expression, mode="eval").body)


@mcp.tool
def roll_dice(count: int = 1, sides: int = 20) -> dict[str, int | list[int]]:
    """Lance `count` dés à `sides` faces et retourne les tirages et leur somme."""
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {"rolls": rolls, "total": sum(rolls)}


@mcp.tool
def text_stats(text: str) -> dict[str, int]:
    """Compte les caractères, mots et lignes d'un texte."""
    return {
        "characters": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
    }


# --------------------------------------------------------------------------
# MCP Apps : une ressource `ui://` par vue, servie en text/html;profile=mcp-app
# (le type MIME est deduit du schema de l'URI par FastMCP).
# --------------------------------------------------------------------------


@mcp.resource("ui://vivia/chart.html")
def chart_app() -> str:
    return ui.CHART_HTML


@mcp.resource("ui://vivia/graph.html")
def graph_app() -> str:
    return ui.GRAPH_HTML


@mcp.resource("ui://vivia/table.html")
def table_app() -> str:
    return ui.TABLE_HTML


@mcp.tool(app=AppConfig(resource_uri="ui://vivia/chart.html"))
def chart(
    labels: Annotated[list[str], Field(description="Etiquettes de l'axe des abscisses.")],
    series: Annotated[
        list[dict[str, Any]],
        Field(
            description='Series : [{"name": "ventes", "values": [1, 2, 3]}]. '
            "Chaque `values` est aligne sur `labels`."
        ),
    ],
    title: Annotated[str, Field(description="Titre affiche au-dessus du graphique.")] = "",
    kind: Annotated[Literal["bar", "line", "area"], Field(description="Type de trace.")] = "bar",
    subtitle: str = "",
    height: Annotated[int, Field(ge=200, le=700)] = 300,
) -> dict[str, Any]:
    """Trace un graphique (barres, lignes ou aires) a partir de series chiffrees.

    A utiliser des qu'une reponse comporte des valeurs comparables : evolution,
    repartition, comparaison entre categories.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "kind": kind,
        "labels": labels,
        "series": series,
        "height": height,
    }


@mcp.tool(app=AppConfig(resource_uri="ui://vivia/graph.html"))
def graph(
    edges: Annotated[
        list[dict[str, Any]],
        Field(
            description='Aretes : [{"source": "a", "target": "b", "weight": 1}]. '
            "`weight` est optionnel et raccourcit l'arete."
        ),
    ],
    nodes: Annotated[
        list[dict[str, Any]],
        Field(
            description='Noeuds : [{"id": "a", "label": "A", "group": "x", "value": 3}]. '
            "Optionnel : les noeuds cites par une arete sont crees d'office. "
            "`group` colore, `value` dimensionne."
        ),
    ] = [],  # noqa: B006 — FastMCP lit la valeur par defaut pour le schema JSON.
    title: str = "",
    subtitle: str = "",
    directed: Annotated[bool, Field(description="Affiche des fleches.")] = False,
    height: Annotated[int, Field(ge=260, le=760)] = 420,
) -> dict[str, Any]:
    """Dessine un graphe de noeuds et d'aretes, dispose par forces et manipulable.

    Pour tout ce qui est relationnel : dependances, arborescence, reseau,
    enchainement d'etapes.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "nodes": nodes,
        "edges": edges,
        "directed": directed,
        "height": height,
    }


@mcp.tool(app=AppConfig(resource_uri="ui://vivia/table.html"))
def table(
    rows: Annotated[
        list[Any],
        Field(
            description="Lignes, soit une liste d'objets, soit une liste de listes "
            "accompagnee de `columns`."
        ),
    ],
    columns: Annotated[
        list[str],
        Field(description="Noms de colonnes. Deduits des cles des objets si omis."),
    ] = [],  # noqa: B006 — idem : valeur par defaut lue pour le schema JSON.
    title: str = "",
    subtitle: str = "",
) -> dict[str, Any]:
    """Affiche des donnees tabulaires, triables par colonne et filtrables.

    Preferable a une liste en Markdown des qu'il y a plusieurs colonnes ou plus
    d'une dizaine de lignes.
    """
    return {
        "title": title,
        "subtitle": subtitle,
        "columns": columns or None,
        "rows": rows,
    }


def main() -> None:
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
