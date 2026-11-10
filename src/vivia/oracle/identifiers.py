"""Normalisation des noms Oracle : SCHEMA.TABLE ou nom seul, ambiguite levee par requete."""

import re

from vivia.oracle.client import fetch

_QUALIFIED = re.compile(r"^([A-Za-z0-9_$#]+)\.([A-Za-z0-9_$#]+)$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")


class ResolutionError(Exception):
    """Base commune : les outils l'attrapent pour renvoyer un message exploitable."""


class UnknownObject(ResolutionError):
    def __init__(self, name: str):
        super().__init__(f"objet inconnu : {name}. Utiliser search_objects pour le retrouver.")


class AmbiguousObject(ResolutionError):
    def __init__(self, name: str, schemas: list[str]):
        self.schemas = schemas
        super().__init__(
            f"« {name} » existe dans plusieurs schemas ({', '.join(schemas)}). "
            f"Preciser SCHEMA.{name}."
        )


class ObjectName:
    def __init__(self, schema: str, name: str):
        self.schema, self.name = schema, name

    def __str__(self) -> str:
        return f"{self.schema}.{self.name}"


def parse(name: str) -> tuple[str | None, str]:
    """Normalise en majuscules ; separe SCHEMA.TABLE sans toucher la base."""
    normalized = name.strip().upper()
    match = _QUALIFIED.match(normalized)
    return (match[1], match[2]) if match else (None, normalized)


def resolve(name: str) -> ObjectName:
    """Comme `parse`, mais resout un nom seul par requete sur ALL_OBJECTS si besoin."""
    schema, obj = parse(name)
    if schema:
        return ObjectName(schema, obj)
    _, rows = fetch(
        "SELECT DISTINCT owner FROM all_objects WHERE object_name = :name", {"name": obj}
    )
    owners = sorted(r[0] for r in rows)
    if not owners:
        raise UnknownObject(obj)
    if len(owners) > 1:
        raise AmbiguousObject(obj, owners)
    return ObjectName(owners[0], obj)


def ensure_identifier(name: str) -> str:
    """Valide un identifiant Oracle nu (colonne), sans requete : refuse tout fragment SQL."""
    normalized = name.strip().upper()
    if not _IDENT.match(normalized):
        raise ValueError(f"nom de colonne invalide : {name}")
    return normalized
