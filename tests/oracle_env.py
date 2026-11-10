"""Verifie l'accessibilite de la base de test (`docker/oracle-test`) pour les tests d'integration.

Lit les memes variables d'environnement que `vivia.oracle.client`, avec les defauts du
conteneur `docker/oracle-test/docker-compose.yml` (compte AGENT, lecture seule).
"""

import os
import unittest

import oracledb

from vivia.oracle import client

os.environ.setdefault("ORACLE_DSN", "localhost:1521/FREEPDB1")
os.environ.setdefault("ORACLE_USER", "AGENT")
os.environ.setdefault("ORACLE_PASSWORD", "Welcome_1")


def require_oracle() -> None:
    """A appeler en premiere ligne de `setUpClass` : skip si la base de test n'est pas joignable."""
    try:
        with client.connection():
            pass
    except oracledb.Error as err:
        raise unittest.SkipTest(f"base de test Oracle injoignable : {err}") from None
