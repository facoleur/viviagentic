"""Outils d'operations et lignage recursif, sans base : `client.fetch` est simule."""

import re
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


REAL_COLUMNS = [  # colonnes des vues du framework en prod
    "CHAIN_NAME", "FLOW_NAME", "OPERATION_NR", "OPERATION", "OPERATION_DESCRIPTION",
    "TARGET_SCHEMA", "TARGET_TABLE", "VALIDITY_END_DATE", "INSTRUCTION",
    "SOURCE_APPLICATION_CODE", "SOURCE_NAME", "TARGET_NAME", "TARGET_TYPE",
]  # fmt: skip


class OperationToolsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fetch(sql, params=None, max_rows=0, max_seconds=None):
            self.calls.append((sql, params))
            if sql == queries.VIEW_OWNERS:
                return [], [("SDEINT",), ("DMDINT",)]
            if sql == queries.VIEW_COLUMNS:
                return [], [(o, c) for o in ("SDEINT", "DMDINT") for c in REAL_COLUMNS]
            if "target_name = :target" in sql:
                return [], TRAC.get(params["target"], [])
            last = 3 if "REGEXP_COUNT" in sql else SQL
            return [], [(*OP, last)]

        for cached in (framework.schemas, framework.columns_of):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)  # ne pas laisser les schemas simules
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

    def test_only_versions_still_valid_are_read(self):
        get_operation("P_TIERS")
        sql = self.calls[-1][0]
        self.assertIn("WHERE validity_end_date > SYSDATE AND flux = :flux", sql)
        self.assertIn("chain_name AS chaine, flow_name AS flux, operation_nr", sql)
        self.assertIn("target_table AS table_cible, operation AS sql_text, validity_end_date", sql)

    def test_search_in_sql_shows_numbered_matching_lines(self):
        result = search_operations("nvl(")
        self.assertIn("l.2 : `NVL(SEGMENT, 'X') SEGMENT`", result)
        sql, params = self.calls[-1]
        self.assertIn("UPPER(flux) LIKE :needle OR UPPER(operation_description) LIKE", sql)
        self.assertIn("UPPER(sql_text) LIKE :needle", sql)
        self.assertEqual(params, {"needle": "%NVL(%"})

    def test_list_operations_counts_sql_lines_without_fetching_the_sql(self):
        result = list_operations("sde_load", "p_tiers")
        self.assertIn("| SDE_LOAD | P_TIERS | 1 | Alimente P_TIERS | SDETRG.P_TIERS | 3 |", result)
        sql, params = self.calls[-1]
        self.assertIn("chaine = :chaine AND flux = :flux", sql)
        self.assertEqual(params, {"chaine": "SDE_LOAD", "flux": "P_TIERS"})

    def test_list_operations_of_a_whole_chain_when_no_flux_is_given(self):
        list_operations("SDE_LOAD")
        sql, params = self.calls[-1]
        self.assertNotIn("flux = :flux", sql)
        self.assertEqual(params, {"chaine": "SDE_LOAD"})

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

    def test_only_current_trac_data_is_read(self):
        get_dependencies("F_OPE")
        sql = self.calls[-1][0]
        self.assertIn("target_name = :target AND validity_end_date > SYSDATE", sql)
        self.assertIn("SELECT source_name, target_name, validity_end_date FROM SDEINT", sql)

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


class BindNamesTests(unittest.TestCase):
    # Oracle refuse un mot reserve comme nom de bind : ORA-01745 (ex. `:view`, `:table`).
    RESERVED = frozenset(
        [
            "ACCESS",
            "ADD",
            "ALL",
            "ALTER",
            "AND",
            "ANY",
            "AS",
            "ASC",
            "AUDIT",
            "BETWEEN",
            "BY",
            "CHAR",
            "CHECK",
            "CLUSTER",
            "COLUMN",
            "COMMENT",
            "COMPRESS",
            "CONNECT",
            "CREATE",
            "CURRENT",
            "DATE",
            "DECIMAL",
            "DEFAULT",
            "DELETE",
            "DESC",
            "DISTINCT",
            "DROP",
            "ELSE",
            "EXCLUSIVE",
            "EXISTS",
            "FILE",
            "FLOAT",
            "FOR",
            "FROM",
            "GRANT",
            "GROUP",
            "HAVING",
            "IDENTIFIED",
            "IMMEDIATE",
            "IN",
            "INCREMENT",
            "INDEX",
            "INITIAL",
            "INSERT",
            "INTEGER",
            "INTERSECT",
            "INTO",
            "IS",
            "LEVEL",
            "LIKE",
            "LOCK",
            "LONG",
            "MAXEXTENTS",
            "MINUS",
            "MODE",
            "MODIFY",
            "NOAUDIT",
            "NOCOMPRESS",
            "NOT",
            "NOWAIT",
            "NULL",
            "NUMBER",
            "OF",
            "OFFLINE",
            "ON",
            "ONLINE",
            "OPTION",
            "OR",
            "ORDER",
            "PCTFREE",
            "PRIOR",
            "PUBLIC",
            "RAW",
            "RENAME",
            "RESOURCE",
            "REVOKE",
            "ROW",
            "ROWID",
            "ROWNUM",
            "ROWS",
            "SELECT",
            "SESSION",
            "SET",
            "SHARE",
            "SIZE",
            "SMALLINT",
            "START",
            "SUCCESSFUL",
            "SYNONYM",
            "SYSDATE",
            "TABLE",
            "THEN",
            "TO",
            "TRIGGER",
            "UID",
            "UNION",
            "UNIQUE",
            "UPDATE",
            "USER",
            "VALIDATE",
            "VALUES",
            "VARCHAR",
            "VARCHAR2",
            "VIEW",
            "WHENEVER",
            "WHERE",
            "WITH",
        ]
    )

    def test_no_query_binds_a_reserved_word(self):
        from vivia.oracle import queries as oracle_queries
        from vivia.retrodoc import sql as retrodoc_sql

        found = set()
        for module in (queries, oracle_queries, retrodoc_sql):
            for name, text in vars(module).items():
                if isinstance(text, str) and name.isupper():
                    found |= {(name, b) for b in re.findall(r"(?<![:\w]):([A-Za-z_]\w*)", text)}
        bad = sorted(n for n, bind in found if bind.upper() in self.RESERVED)
        self.assertEqual(bad, [])


class FrameworkColumnsTests(unittest.TestCase):
    def setUp(self):
        columns = {"SDEINT": ["CHAIN_NAME", "FLOW_NAME", "OPERATION_NR", "SQL_TEXT"]}
        self.patches = [
            mock.patch.object(framework, "schemas", lambda view: ("SDEINT",)),
            mock.patch.object(framework, "columns_of", lambda view: columns),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_internal_names_are_mapped_to_the_real_columns(self):
        with mock.patch.dict(
            framework.COLUMNS, {"V_X": {"chaine": "CHAIN_NAME", "flux": "FLOW_NAME"}}
        ):
            sql = framework.union("V_X", "chaine, flux, operation_nr")
        self.assertEqual(
            sql, "SELECT CHAIN_NAME AS chaine, FLOW_NAME AS flux, operation_nr FROM SDEINT.V_X"
        )

    def test_a_missing_column_is_named_with_the_real_columns(self):
        with self.assertRaises(LookupError) as ctx:
            framework.union("V_X", "chaine, operation_nr")
        message = str(ctx.exception)
        self.assertIn("SDEINT.V_X : colonne(s) chaine absente(s)", message)
        self.assertIn("Colonnes reelles : CHAIN_NAME, FLOW_NAME, OPERATION_NR, SQL_TEXT", message)


class FrameworkSchemasTests(unittest.TestCase):
    def test_only_sdeint_and_dmdint_are_read(self):
        rows = [("AUTREINT",), ("DMDINT",), ("SDAINT",), ("SDEINT",)]
        framework.schemas.cache_clear()
        self.addCleanup(framework.schemas.cache_clear)
        with mock.patch.object(client, "fetch", lambda sql, params=None: ([], rows)):
            self.assertEqual(framework.schemas("V_M_OPERATION"), ("DMDINT", "SDEINT"))
        framework.schemas.cache_clear()
        only_sda = lambda sql, params=None: ([], [("SDAINT",)])  # noqa: E731
        with mock.patch.object(client, "fetch", only_sda), self.assertRaises(LookupError) as ctx:
            framework.schemas("V_M_OPERATION")
        self.assertIn("SDEINT, DMDINT", str(ctx.exception))
