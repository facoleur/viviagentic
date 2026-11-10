import ast
import operator

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


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
