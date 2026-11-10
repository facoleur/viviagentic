"""Glossaire et verified queries (sans base) ; distinct_values et get_dependencies (avec base,
contre `docker/oracle-test` apres recreation du conteneur : TRAC_DATA a change de forme).
"""

import unittest

from tests.oracle_env import require_oracle
from vivia.tools.explore.distinct_values import distinct_values
from vivia.tools.explore.find_verified_query import find_verified_query
from vivia.tools.explore.get_dependencies import get_dependencies
from vivia.tools.explore.glossary import glossary


class GlossaryTests(unittest.TestCase):
    def test_zone_definition(self):
        self.assertIn("sources applicatives", glossary("SDA"))

    def test_type_definition_is_case_insensitive(self):
        self.assertIn("staging", glossary("stg"))

    def test_unknown_term(self):
        self.assertIn("inconnu", glossary("NOPE_XYZ"))


class FindVerifiedQueryTests(unittest.TestCase):
    def test_matches_by_keyword(self):
        result = find_verified_query("tiers crees avant")
        self.assertIn("```sql", result)
        self.assertIn("SDATRG.TIERS", result)

    def test_no_match(self):
        result = find_verified_query("xyzzy inexistant")
        self.assertIn("Aucune requete", result)


class SemanticLayerOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_oracle()

    def test_distinct_values_on_a_known_column(self):
        result = distinct_values("SDATRG.MOUVEMENT", "devise")
        self.assertIn("EUR", result)

    def test_distinct_values_unknown_table_gives_actionable_error(self):
        result = distinct_values("NOPE_TABLE_XYZ", "col")
        self.assertIn("Erreur", result)

    def test_get_dependencies_lists_every_source(self):
        # F_OPERATION a deux sources dans TRAC_DATA (voir docker/oracle-test/init.sql).
        result = get_dependencies("DMDTRG.F_OPERATION")
        self.assertIn("SDEINT.V_P_FLUX", result)
        self.assertIn("SDEINT.V_P_TIERS", result)

    def test_get_dependencies_on_a_root_table_is_empty(self):
        result = get_dependencies("SDATRG.TIERS")
        self.assertIn("Aucune dependance", result)


if __name__ == "__main__":
    unittest.main()
