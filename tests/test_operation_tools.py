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
TRAC = {"F_OPE": [("SDE", "P_TIERS"), ("SDE", "W_AGG"), ("SDA", "COMPTE")]}


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
        self.assertIn("operation_nr = :nr AND chain_name = :chaine", sql)
        self.assertEqual(params, {"flux": "P_TIERS", "nr": 1, "chaine": "SDE_LOAD"})

    def test_only_versions_still_valid_are_read(self):
        get_operation("P_TIERS")
        sql = self.calls[-1][0]
        self.assertIn("WHERE validity_end_date > SYSDATE AND flow_name = :flux", sql)
        self.assertIn("operation, validity_end_date FROM SDEINT.V_M_OPERATION", sql)

    def test_search_in_sql_shows_numbered_matching_lines(self):
        result = search_operations("nvl(")
        self.assertIn("l.2 : `NVL(SEGMENT, 'X') SEGMENT`", result)
        sql, params = self.calls[-1]
        self.assertIn("UPPER(flow_name) LIKE :needle OR UPPER(operation_description) LIKE", sql)
        self.assertIn("UPPER(operation) LIKE :needle", sql)
        self.assertEqual(params, {"needle": "%NVL(%"})

    def test_list_operations_counts_sql_lines_without_fetching_the_sql(self):
        result = list_operations("sde_load", "p_tiers")
        self.assertIn("| SDE_LOAD | P_TIERS | 1 | Alimente P_TIERS | SDETRG.P_TIERS | 3 |", result)
        sql, params = self.calls[-1]
        self.assertIn("chain_name = :chaine AND flow_name = :flux", sql)
        self.assertEqual(params, {"chaine": "SDE_LOAD", "flux": "P_TIERS"})

    def test_list_operations_of_a_whole_chain_when_no_flux_is_given(self):
        list_operations("SDE_LOAD")
        sql, params = self.calls[-1]
        self.assertNotIn("flux = :flux", sql)
        self.assertEqual(params, {"chaine": "SDE_LOAD"})

    def test_dependencies_are_one_select_on_the_current_sources_with_their_zone(self):
        result = get_dependencies("f_ope")
        self.assertEqual(
            result.splitlines(),
            ["## Sources de F_OPE", "- `P_TIERS` (SDE)", "- `W_AGG` (SDE)", "- `COMPTE` (SDA)"],
        )
        sql, params = self.calls[-1]
        self.assertIn("WHERE target_name = :target AND validity_end_date > SYSDATE", sql)
        self.assertIn("SELECT source_application_code, source_name, target_name", sql)
        self.assertEqual(params, {"target": "F_OPE"})
        self.assertEqual(len([c for c in self.calls if "target_name = :target" in c[0]]), 1)

    def test_a_table_without_source_says_so(self):
        self.assertEqual(
            get_dependencies("RACINE"), "Aucune source declaree dans V_M_TRAC_DATA pour RACINE."
        )

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
        columns = {"SDEINT": ["FLOW_NAME", "OPERATION_NR", "OPERATION"]}
        self.patches = [
            mock.patch.object(framework, "schemas", lambda view: ("SDEINT",)),
            mock.patch.object(framework, "columns_of", lambda view: columns),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_missing_column_is_named_with_the_real_columns(self):
        with self.assertRaises(LookupError) as ctx:
            framework.union("V_X", "chain_name, operation_nr")
        message = str(ctx.exception)
        self.assertIn("SDEINT.V_X : colonne(s) chain_name absente(s)", message)
        self.assertIn("Colonnes reelles : FLOW_NAME, OPERATION_NR, OPERATION", message)


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
