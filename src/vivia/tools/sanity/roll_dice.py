import random


def roll_dice(count: int = 1, sides: int = 20) -> dict[str, int | list[int]]:
    """Lance `count` dés à `sides` faces et retourne les tirages et leur somme."""
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {"rolls": rolls, "total": sum(rolls)}
