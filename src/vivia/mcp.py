"""Serveur MCP minimal : quelques tools jouets pour valider les tool calls."""

import ast
import operator
import os
import random
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastmcp import FastMCP

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


def main() -> None:
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
