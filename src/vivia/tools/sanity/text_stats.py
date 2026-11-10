def text_stats(text: str) -> dict[str, int]:
    """Compte les caractères, mots et lignes d'un texte."""
    return {
        "characters": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
    }
