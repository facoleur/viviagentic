"""Mise en forme Markdown commune aux outils d'exploration (reponse compacte, 2000 tokens max)."""

MAX_CHARS = 8000  # ~2000 tokens


def markdown_table(
    columns: list[str], rows: list[tuple], limit: int, total: int | None = None
) -> str:
    """Tableau Markdown borne a `limit` lignes, avec une note explicite si tronque."""
    shown = rows[:limit]
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [head, sep]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in shown]
    text = "\n".join(lines)
    remaining = (total if total is not None else len(rows)) - len(shown)
    if remaining > 0:
        text += f"\n\n… {remaining} ligne(s) de plus, preciser le filtre."
    return text


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n… tronque a {limit} caracteres, preciser la demande."
