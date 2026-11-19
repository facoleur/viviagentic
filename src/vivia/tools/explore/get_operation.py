"""SQL des operations ELT d'un flux, tel qu'execute par le framework (templates #NOM# compris)."""

from typing import Annotated

from pydantic import Field

from vivia.oracle import format as fmt
from vivia.tools.explore.operations import by_flux, fetch_operations


def get_operation(
    flux: Annotated[str, Field(description="Nom du flux (ex. 'P_TIERS').")],
    operation_nr: Annotated[
        int | None,
        Field(description="Numero de l'operation dans le flux. Omis = toutes, dans l'ordre."),
    ] = None,
    chaine: Annotated[
        str | None,
        Field(description="Chaine du flux, si le meme nom de flux existe dans plusieurs chaines."),
    ] = None,
) -> str:
    """SQL complet des operations d'un flux (ou d'une seule), avec table cible et description.

    200 000 caracteres au plus : au-dela, un flux entier est refuse (rappeler avec
    `operation_nr`) et une operation seule est tronquee, avec un avertissement.

    Exemple : get_operation("P_TIERS"), ou get_operation("P_FLUX", operation_nr=2)
    """
    return fmt.operations_sql(flux, fetch_operations(*by_flux(flux, operation_nr, chaine)))
