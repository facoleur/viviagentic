"""Profil par echantillon : requetes et texte, avec `client.fetch` simule."""

import unittest
from datetime import datetime
from unittest import mock

import oracledb

from vivia.oracle import client
from vivia.oracle import format as fmt
from vivia.oracle import profile as prof

COLUMNS = (
    ("ID", "NUMBER"),
    ("CD_STATUT", "VARCHAR2"),
    ("DT_FIN", "DATE"),
    ("NOTE", "CLOB"),
)
# COUNT(*) puis, par colonne : non nuls, distinctes, min, max, mesure x, mesure y.
STATS = (
    2000,
    2000, 2000, 1, 2000, 0, 0,
    1960, 3, "A", "S", None, None,
    2000, 5, datetime(2019, 1, 1), datetime(9999, 12, 31), 1420, 0,
)  # fmt: skip
FREQUENT = [("A", 1640, 0), ("C", 300, 0), ("S", 20, 0), (None, 40, 0)]


class Oracle:
    """Repond selon la requete et garde celles qu'on lui a posees."""

    def __init__(self, sample_rows=2000, no_sample=False):
        self.sql, self.sample_rows, self.no_sample = [], sample_rows, no_sample

    def __call__(self, sql, params=None, max_rows=0, max_seconds=None):
        self.sql.append(sql)
        if "GROUPING SETS" in sql:
            return [], FREQUENT
        if self.no_sample and "SAMPLE" in sql:
            raise oracledb.DatabaseError("ORA-01446")
        rows = self.sample_rows if "SAMPLE" in sql else 5000
        return [], [(rows, *STATS[1:])]


class ProfileTests(unittest.TestCase):
    def run_profile(self, **kwargs):
        oracle = Oracle(**kwargs)
        with mock.patch.object(client, "fetch", oracle):
            return prof.profile("SDETRG", "P_TIERS", COLUMNS), oracle

    def test_one_aggregate_query_and_one_for_the_codes_and_lobs_are_skipped(self):
        result, oracle = self.run_profile()
        self.assertEqual(len(oracle.sql), 2)
        self.assertIn("SAMPLE BLOCK (1) SEED (42)", oracle.sql[0])
        self.assertNotIn("NOTE", oracle.sql[0])
        self.assertIn('GROUPING SETS (("CD_STATUT"))', oracle.sql[1])  # un code, pas la date
        self.assertEqual((result["rows"], result["sampled"]), (2000, True))
        # La valeur NULL n'est pas une valeur frequente : elle a sa propre part de nulls.
        self.assertEqual(
            result["columns"]["CD_STATUT"]["values"], [("A", 1640), ("C", 300), ("S", 20)]
        )
        self.assertNotIn("NOTE", result["columns"])

    def test_a_too_small_sample_falls_back_to_the_first_rows(self):
        result, oracle = self.run_profile(sample_rows=50)
        self.assertFalse(result["sampled"])
        self.assertNotIn("SAMPLE", oracle.sql[1])
        self.assertIn("FETCH FIRST 100000 ROWS ONLY", oracle.sql[1])

    def test_a_view_that_refuses_sample_falls_back_too(self):
        result, _ = self.run_profile(no_sample=True)
        self.assertFalse(result["sampled"])

    def test_a_table_with_only_lob_columns_has_no_profile(self):
        self.assertIsNone(prof.profile("S", "T", (("NOTE", "CLOB"),)))

    def test_wide_tables_are_split_in_batches(self):
        columns = tuple((f"C{i}", "NUMBER") for i in range(prof.BATCH + 5))
        calls = []

        def fetch(sql, params=None, max_rows=0, max_seconds=None):
            calls.append(sql)
            if "GROUPING SETS" in sql:
                return [], []
            n = sql.count('COUNT("C')
            return [], [(5000, *([5000, 10, 1, 9, 0, 0] * n))]

        with mock.patch.object(client, "fetch", fetch):
            result = prof.profile("S", "T", columns)
        self.assertEqual(len(calls), 2 + 1)  # 2 lots de colonnes, puis les colonnes de codes
        self.assertEqual(len(result["columns"]), prof.BATCH + 5)


class TextTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(client, "fetch", Oracle()):
            self.result = prof.profile("SDETRG", "P_TIERS", COLUMNS)

    def line(self, column):
        return fmt.profile_text(self.result["columns"][column], self.result["rows"])

    def test_candidate_key(self):
        self.assertEqual(self.line("ID"), "0 % null, unique (cle candidate), min 1, max 2000")

    def test_code_column_lists_its_frequent_values(self):
        self.assertEqual(self.line("CD_STATUT"), "2 % null, 3 valeurs : A 82 %, C 15 %, S 1 %")

    def test_date_with_a_sentinel_end_date(self):
        self.assertIn(
            "min 2019-01-01, max 9999-12-31, 71 % a 9999-12-31 (sentinelle)", self.line("DT_FIN")
        )

    def test_empty_and_constant_columns(self):
        empty = {"kind": "text", "non_null": 0, "distinct": 0, "values": []}
        self.assertEqual(fmt.profile_text(empty, 100), "vide (100 % null)")
        const = {"kind": "text", "non_null": 100, "distinct": 1, "min": "X", "values": []}
        self.assertEqual(fmt.profile_text(const, 100), "constante : X")

    def test_sentinel_text_value_is_flagged(self):
        s = {"kind": "text", "non_null": 100, "distinct": 2, "values": [("A", 60), ("N/A", 40)]}
        self.assertIn("N/A (sentinelle) 40 %", fmt.profile_text(s, 100))

    def test_report_puts_the_profile_next_to_each_column_and_explains_a_missing_one(self):
        class Obj:
            schema, name = "SDETRG", "P_TIERS"

            def __str__(self):
                return "SDETRG.P_TIERS"

        cols = [("ID", "NUMBER", "N", None), ("NOTE", "CLOB", "Y", None)]
        report = fmt.describe_table_report(Obj(), cols, [], [], [], None, None, self.result)
        self.assertIn("Profil sur 2000 lignes (echantillon de 1 % des blocs)", report)
        self.assertIn("- `ID` NUMBER NOT NULL | 0 % null, unique", report)
        self.assertIn("- `NOTE` CLOB NULL", report)
        self.assertNotIn("CLOB NULL |", report)  # LOB : pas de profil
        failed = fmt.describe_table_report(
            Obj(), cols, [], [], [], None, None, "Profil non calcule (ORA-00942)."
        )
        self.assertIn("Profil non calcule (ORA-00942).", failed)
        self.assertNotIn("|", failed.split("### Colonnes")[1].split("###")[0])
