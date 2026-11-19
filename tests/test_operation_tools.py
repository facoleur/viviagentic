"""Outils d'operations et lignage recursif, sans base : `client.fetch` est simule."""

import unittest
from unittest import mock

from vivia.oracle import client
from vivia.tools.explore import queries
from vivia.tools.explore.get_dependencies import get_dependencies, table_name
from vivia.tools.explore.get_operation import get_operation
from vivia.tools.explore.list_operations import list_operations
from vivia.tools.explore.search_operations import search_operations

SQL = "SELECT ID_TIERS,\n  NVL(SEGMENT, 'X') SEGMENT\nFROM SDAINT.V_TIERS"
OP = ("SDE_LOAD", "P_TIERS", 1, "Alimente P_TIERS", "SDETRG.P_TIERS")
TRAC = {
    "F_OPE": [("SDE", "V_P_TIERS$CV"), ("SDE", "V_W_AGG"), ("SDA", "COMPTE")],
    "P_TIERS": [("SDA", "V_TIERS"), ("SDE", "P_ADRESSE")],
    "W_AGG": [("SDE", "V_W_AGG"), ("SDE", "W_BASE")],  # boucle sur elle-meme
    "W_BASE": [("SDA", "MOUVEMENT")],
}


class OperationToolsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fetch(sql, params=None, max_rows=0, max_seconds=None):
            self.calls.append((sql, params))
            if sql == queries.TRAC_DATA_SOURCES:
                return [], TRAC.get(params["target"], [])
            last = 3 if "REGEXP_COUNT" in sql else SQL
            return [], [(*OP, last)]

        patcher = mock.patch.object(client, "fetch", fetch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_operation_returns_the_full_sql_and_filters_by_number_and_chain(self):
        result = get_operation("p_tiers", operation_nr=1, chaine="sde_load")
        self.assertIn(SQL, result)
        self.assertIn("SDE_LOAD.P_TIERS op 1 -> `SDETRG.P_TIERS`", result)
        sql, params = self.calls[-1]
        self.assertIn("operation_nr = :nr AND chaine = :chaine", sql)
        self.assertEqual(params, {"flux": "P_TIERS", "nr": 1, "chaine": "SDE_LOAD"})

    def test_search_in_sql_shows_numbered_matching_lines(self):
        result = search_operations("nvl(", chaines=["sde_load"])
        self.assertIn("l.2 : `NVL(SEGMENT, 'X') SEGMENT`", result)
        sql, params = self.calls[-1]
        self.assertIn("OR UPPER(sql_text) LIKE :needle) AND chaine IN (:chaine_0)", sql)
        self.assertEqual(params, {"needle": "%NVL(%", "chaine_0": "SDE_LOAD"})

    def test_list_operations_counts_sql_lines_without_fetching_the_sql(self):
        result = list_operations(["SDE_LOAD", "DMD_LOAD"])
        self.assertIn("| SDE_LOAD | P_TIERS | 1 | Alimente P_TIERS | SDETRG.P_TIERS | 3 |", result)
        self.assertIn("chaine IN (:chaine_0, :chaine_1)", self.calls[-1][0])

    def test_one_level_by_default_with_the_size_of_each_branch(self):
        result = get_dependencies("sdetrg.f_ope")
        self.assertIn('P_TIERS["P_TIERS (SDE, table P, 2 sources)"]', result)
        self.assertIn('W_AGG["W_AGG (SDE, 2 sources)"]', result)
        self.assertIn('COMPTE["COMPTE (SDA, source)"]', result)
        self.assertIn("P_TIERS --> F_OPE", result)
        self.assertNotIn("W_BASE", result)
        self.assertIn("Branches non remontees : P_TIERS (2), W_AGG (2).", result)

    def test_several_levels_stop_at_p_tables_and_sda(self):
        result = get_dependencies("F_OPE", niveaux=5)
        self.assertIn("W_BASE --> W_AGG", result)
        self.assertIn("MOUVEMENT --> W_BASE", result)
        self.assertNotIn("P_ADRESSE", result)  # table P non remontee
        self.assertIn("Branches non remontees : P_TIERS (2).", result)

    def test_view_names_are_reduced_to_their_table(self):
        self.assertEqual(table_name("SDEINT.V_P_FLUX$CV"), "P_FLUX")
        self.assertEqual(table_name("p_flux"), "P_FLUX")


class OperationSizeTests(unittest.TestCase):
    def test_long_flux_is_refused_and_long_single_operation_is_truncated(self):
        from vivia.oracle import format as fmt

        big = "x" * 150_000
        two = [(*OP, big), ("SDE_LOAD", "P_TIERS", 2, None, "SDETRG.P_TIERS", big)]
        refused = fmt.operations_sql("P_TIERS", two)
        self.assertIn("rappeler get_operation avec `operation_nr`", refused)
        self.assertIn("- op 2 : 150,000 caracteres", refused)
        self.assertLess(len(refused), 1000)

        cut = fmt.operations_sql("P_TIERS", [(*OP, "y" * 300_000)])
        self.assertTrue(cut.startswith("ATTENTION : SQL tronque"))
        self.assertLess(len(cut), fmt.MAX_SQL_CHARS + 200)


class FrameworkViewsTests(unittest.TestCase):
    def test_framework_queries_never_read_sdaint(self):
        for sql in (queries.OPERATIONS, queries.TRAC_DATA_SOURCES):
            self.assertNotIn("SDAINT", sql)
            self.assertIn("SDEINT", sql)
            self.assertIn("DMDINT", sql)
