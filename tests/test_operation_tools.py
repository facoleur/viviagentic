"""Outils d'operations et lignage recursif, sans base : `client.fetch` est simule."""

import unittest
from unittest import mock

from vivia.oracle import client
from vivia.tools.explore import framework, queries
from vivia.tools.explore.get_dependencies import get_dependencies
from vivia.tools.explore.get_operation import get_operation
from vivia.tools.explore.list_operations import list_operations
from vivia.tools.explore.search_operations import search_operations

SQL = "SELECT ID_TIERS,\n  NVL(SEGMENT, 'X') SEGMENT\nFROM SDAINT.V_TIERS"
OP = ("SDE_LOAD", "P_TIERS", 1, "Alimente P_TIERS", "SDETRG.P_TIERS")
TRAC = {
    "F_OPE": [("P_TIERS",), ("W_AGG",)],
    "P_TIERS": [("TIERS",)],
    "W_AGG": [("W_AGG",), ("P_TIERS",)],  # boucle sur elle-meme, source deja vue
    "TIERS": [("RAW_TIERS",)],
}


class OperationToolsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fetch(sql, params=None, max_rows=0, max_seconds=None):
            self.calls.append((sql, params))
            if sql == queries.VIEW_OWNERS:
                return [], [("SDEINT",), ("DMDINT",)]
            if "target_name = :target" in sql:
                return [], TRAC.get(params["target"], [])
            last = 3 if "REGEXP_COUNT" in sql else SQL
            return [], [(*OP, last)]

        framework.schemas.cache_clear()
        self.addCleanup(framework.schemas.cache_clear)  # ne pas laisser les schemas simules
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

    def test_level_one_is_the_direct_sources_only(self):
        result = get_dependencies("f_ope")
        self.assertIn("P_TIERS --> F_OPE", result)
        self.assertIn("W_AGG --> F_OPE", result)
        self.assertNotIn("TIERS --> P_TIERS", result)

    def test_each_level_repeats_the_search_for_every_new_source(self):
        result = get_dependencies("F_OPE", niveaux=3)
        self.assertIn("TIERS --> P_TIERS", result)
        self.assertIn("RAW_TIERS --> TIERS", result)
        self.assertNotIn("W_AGG --> W_AGG", result)
        targets = [p["target"] for s, p in self.calls if p and "target" in p]
        self.assertEqual(targets, ["F_OPE", "P_TIERS", "W_AGG", "TIERS"])

    def test_framework_views_are_read_from_the_discovered_schemas(self):
        get_dependencies("F_OPE")
        sql = self.calls[-1][0]
        self.assertIn("FROM SDEINT.V_M_TRAC_DATA UNION ALL SELECT", sql)
        self.assertIn("FROM DMDINT.V_M_TRAC_DATA", sql)


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
