"""Recherche de tables/vues par nom ou par commentaire, dans le dictionnaire Oracle standard."""

from typing import Annotated, Literal

from pydantic import Field

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.explore import queries

_DEFAULT_LIMIT = 25

# Garde en phase avec la section [zones] de vivia/oracle/glossary.toml.
_Zone = Literal["SDA", "SDE", "DMD"]


def search_objects(
    texte: Annotated[
        str,
        Field(
            description="Terme a chercher dans le nom ou le commentaire d'une table/vue "
            "(ex. 'tiers', 'flux'). Sous-chaine, insensible a la casse ; pas de wildcard SQL."
        ),
    ],
    zone: Annotated[
        _Zone | None,
        Field(
            description="Filtre sur le prefixe de schema : SDA (sources applicatives), "
            "SDE (sources enrichies) ou DMD (data marts). Omis = toutes les zones."
        ),
    ] = None,
    limite: Annotated[
        int, Field(description="Nombre maximal de resultats renvoyes.", ge=1, le=200)
    ] = _DEFAULT_LIMIT,
) -> str:
    """Cherche une table ou une vue par nom ou par commentaire. 25 resultats par defaut.

    `zone` filtre sur le prefixe de schema (ex. "DMD" -> DMDSTG/DMDTRG/DMDINT). `limite` ajuste
    le nombre maximal de resultats. Les fiches de documentation (phase 4) seront cherchees ici
    aussi une fois qu'elles existeront.

    Exemple : search_objects("tiers"), ou search_objects("flux", zone="SDE", limite=50)
    """
    params: dict[str, str] = {"needle": f"%{texte.upper()}%"}
    filter_t, filter_v = "", ""
    if zone:
        params["zone"] = f"{zone.upper()}%"
        filter_t, filter_v = "AND t.owner LIKE :zone", "AND v.owner LIKE :zone"

    sql = queries.SEARCH_OBJECTS.format(filter_t=filter_t, filter_v=filter_v)
    _, rows = client.fetch(sql, params, max_rows=limite)
    return fmt.search_objects_report(texte, zone, rows, limite)
