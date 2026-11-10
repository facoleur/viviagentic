"""Integration : les 8 outils d'exploration contre `docker/oracle-test` (schemas zone+type)."""

import unittest

from tests.oracle_env import require_oracle
from vivia.tools.explore.check_grain import check_grain
from vivia.tools.explore.column_stats import column_stats
from vivia.tools.explore.compare_sql import compare_sql
from vivia.tools.explore.compile_sql import compile_sql
from vivia.tools.explore.describe_table import describe_table
from vivia.tools.explore.find_usages import find_usages
from vivia.tools.explore.get_source import get_source
from vivia.tools.explore.run_select import run_select
from vivia.tools.explore.search_objects import search_objects


class OracleExploreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_oracle()

    def test_compile_sql_accepts_a_valid_select(self):
        result = compile_sql("SELECT id_tiers, nom FROM DMDTRG.D_TIERS")
        self.assertIn("OK", result)
        self.assertIn("ID_TIERS", result)

    def test_compile_sql_reports_the_ora_error_and_location(self):
        result = compile_sql("SELECT nope_column FROM DMDTRG.D_TIERS")
        self.assertIn("ORA-00904", result)

    def test_compile_sql_substitutes_quoted_templates(self):
        result = compile_sql(
            "SELECT * FROM SDATRG.TIERS WHERE date_creation <= TO_DATE('#PNDATE#','YYYYMMDD')"
        )
        self.assertIn("OK", result)

    def test_compile_sql_rejects_dml(self):
        result = compile_sql("DELETE FROM SDATRG.TIERS")
        self.assertIn("Rejete", result)

    def test_describe_table_reports_columns_and_zone(self):
        result = describe_table("DMDTRG.D_TIERS")
        self.assertIn("ID_TIERS", result)
        self.assertIn("DMD", result)

    def test_describe_table_shows_the_view_definition(self):
        result = describe_table("SDAINT.V_TIERS")
        self.assertIn("SELECT", result.upper())

    def test_describe_table_unknown_object_gives_actionable_error(self):
        result = describe_table("NOPE_TABLE_XYZ")
        self.assertIn("search_objects", result)

    def test_describe_table_reports_ambiguous_bare_name(self):
        # M_OPERATION existe dans SDATRG, SDETRG et DMDTRG (init.sql).
        result = describe_table("M_OPERATION")
        self.assertIn("plusieurs schemas", result)

    def test_search_objects_finds_by_name(self):
        result = search_objects("tiers")
        self.assertIn("TIERS", result)

    def test_search_objects_filters_by_zone(self):
        result = search_objects("tiers", zone="DMD")
        self.assertIn("DMDTRG", result)
        self.assertNotIn("SDATRG", result)

    def test_run_select_caps_rows(self):
        result = run_select("SELECT * FROM SDATRG.MOUVEMENT", max_rows=3)
        data_lines = [line for line in result.splitlines() if line.startswith("| ")]
        self.assertEqual(len(data_lines) - 2, 3)  # moins l'entete et le separateur

    def test_run_select_rejects_dml(self):
        result = run_select("DELETE FROM SDATRG.MOUVEMENT")
        self.assertIn("Rejete", result)

    def test_check_grain_detects_duplicates(self):
        # DEVISE vaut 'EUR' pour les 20 lignes du jeu de test.
        result = check_grain("SDATRG.MOUVEMENT", ["devise"])
        self.assertIn("doublons", result.lower())

    def test_check_grain_on_a_true_key_has_no_duplicates(self):
        result = check_grain("SDATRG.MOUVEMENT", ["id_mouvement"])
        self.assertNotIn("doublons", result.lower())

    def test_check_grain_rejects_an_unsafe_filter(self):
        result = check_grain("SDATRG.MOUVEMENT", ["id_mouvement"], filtre="1=1; DROP TABLE x")
        self.assertIn("Erreur", result)

    def test_column_stats_live_computation_with_filter(self):
        result = column_stats("DMDTRG.D_TIERS", ["segment"], filtre="1=1")
        self.assertIn("SEGMENT", result.upper())

    def test_find_usages_on_a_known_table(self):
        result = find_usages("DMDTRG.D_TIERS")
        self.assertIn("Dependances", result)

    def test_get_source_reports_an_unknown_object_cleanly(self):
        result = get_source("NOPE_PACKAGE_XYZ")
        self.assertIn("Erreur", result)

    def test_compare_sql_reports_identical_when_logic_is_unchanged(self):
        # Operation 1 du flux TIERS (SDATRG.M_OPERATION, init.sql) : meme SQL mot pour mot.
        result = compare_sql(
            "TIERS",
            1,
            "SELECT * FROM SDATRG.TIERS WHERE DATE_CREATION <= TO_DATE('#PNDATE#','YYYYMMDD')",
        )
        self.assertIn("IDENTIQUE", result)

    def test_compare_sql_reports_different_when_logic_changes(self):
        result = compare_sql("TIERS", 1, "SELECT * FROM SDATRG.TIERS WHERE SEGMENT = 'PRO'")
        self.assertIn("DIFFERENT", result)

    def test_compare_sql_reports_the_ora_error_on_the_new_sql(self):
        result = compare_sql("TIERS", 1, "SELECT nope_column FROM SDATRG.TIERS")
        self.assertIn("ORA-00904", result)

    def test_compare_sql_rejects_dml(self):
        result = compare_sql("TIERS", 1, "DELETE FROM SDATRG.TIERS")
        self.assertIn("Rejete", result)

    def test_compare_sql_unknown_operation_gives_an_actionable_error(self):
        result = compare_sql("NOPE_FLUX_XYZ", 999, "SELECT 1 FROM DUAL")
        self.assertIn("introuvable", result)

    def test_compare_sql_reports_a_timeout_distinctly_from_a_compile_error(self):
        # Produit volontairement trop de lignes pour un budget d'1s, quelle que soit la machine.
        slow = (
            "SELECT a.c FROM "
            "(SELECT LEVEL c FROM DUAL CONNECT BY LEVEL <= 6000) a, "
            "(SELECT LEVEL c FROM DUAL CONNECT BY LEVEL <= 6000) b"
        )
        result = compare_sql("TIERS", 1, slow, max_seconds=1)
        self.assertIn("Depassement", result)


if __name__ == "__main__":
    unittest.main()
