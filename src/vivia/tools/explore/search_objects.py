"""Recherche de tables/vues par nom ou par commentaire, dans le dictionnaire Oracle standard."""

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.tools.explore import queries

_DEFAULT_LIMIT = 25


def search_objects(texte: str, zone: str | None = None, limite: int = _DEFAULT_LIMIT) -> str:
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
