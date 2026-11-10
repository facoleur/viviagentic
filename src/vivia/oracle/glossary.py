"""Glossaire zones/types/termes : une seule source, lue par `format` (fiche de table)
et par le tool `glossary` (question libre de l'agent). Contenu dans glossary.toml, a cote.
"""

import tomllib
from pathlib import Path

_SECTIONS = tomllib.loads(Path(__file__).with_name("glossary.toml").read_text())
ZONES = _SECTIONS["zones"]
TYPES = _SECTIONS["types"]


def define(terme: str) -> str | None:
    """Definition d'une zone, d'un type ou d'un terme metier ; None si inconnu."""
    key = terme.strip().upper()
    for section in _SECTIONS.values():
        if key in section:
            return section[key]
    return None


def zone_type(schema: str) -> str:
    """Decode un schema en zone + type (ex. DMDTRG -> DMD / TRG), ou un message par defaut."""
    zone, kind = schema[:3], schema[3:]
    if zone in ZONES and kind in TYPES:
        return f"{zone} ({ZONES[zone]}) / {kind} ({TYPES[kind]})"
    return "zone/type non reconnus (hors convention SDA/SDE/DMD x STG/TRG/INT)"
