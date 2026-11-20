"""Erreurs des outils : un message que l'agent peut exploiter, jamais une exception brute."""

import functools
import logging

import oracledb

from vivia.oracle import format as fmt
from vivia.oracle.identifiers import ResolutionError
from vivia.oracle.sql_guard import RejectedSQL

log = logging.getLogger(__name__)


def guarded(tool):
    """Transforme les erreurs de `tool` en texte : nom inconnu, SQL refuse, erreur Oracle (avec
    un conseil), bug interne. L'agent lit le message et corrige sa demande."""

    @functools.wraps(tool)
    def run(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except RejectedSQL as err:
            return f"Rejete : {err}"
        except (ResolutionError, LookupError, ValueError) as err:
            return f"Erreur : {err}"
        except oracledb.Error as err:
            return fmt.oracle_error(err)
        except Exception as err:
            log.exception("outil %s", tool.__name__)
            return fmt.internal_error(tool.__name__, err)

    return run
