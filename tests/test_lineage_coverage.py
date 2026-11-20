"""Couverture du lignage colonne : analyse d'une operation et resume, sans base."""

import signal
import unittest

from tests.oracle_env import require_oracle
from vivia import lineage_coverage as cov

COLUMNS = {
    "SDEINT": {"V_P_TIERS": {"ID_TIERS": "NUMBER", "NOM": "VARCHAR2", "CD_SEG": "VARCHAR2"}},
    "SDETRG": {"T": {"A": "NUMBER", "B": "VARCHAR2", "C": "VARCHAR2"}},
}
TRAC = {"T": {"P_TIERS"}}


def op(sql, cible="T", nr=1):
    return (("CH", "T", nr, None, cible, sql), 60)


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        cov.init(COLUMNS, TRAC)

    def test_star_is_expanded_from_the_dictionary_and_matches_trac(self):
        row = cov.analyze(op("SELECT t.* FROM SDEINT.V_P_TIERS t"))
        self.assertEqual(row["statut"], "ok")
        self.assertEqual((row["colonnes"], row["exactes"], row["etoile"]), (3, 3, 0))
        self.assertEqual(row["hors_trac"], [])  # V_P_TIERS -> P_TIERS, declare dans TRAC

    def test_star_on_an_unknown_table_is_reported_not_guessed(self):
        row = cov.analyze(op("SELECT * FROM SDESTG.TMP"))
        self.assertEqual((row["colonnes"], row["etoile"], row["sans_source"]), (3, 1, 2))
        self.assertEqual(row["inconnues"], ["SDESTG.TMP"])
        self.assertEqual(row["hors_trac"], [])  # un schema STG n'est pas declare dans TRAC

    def test_source_missing_from_trac_is_listed(self):
        sql = "INSERT INTO T (A) SELECT f.ID FROM SDEINT.V_P_FLUX$CV f"
        self.assertEqual(cov.analyze(op(sql))["hors_trac"], ["P_FLUX"])

    def test_unsupported_sql_and_errors_become_a_status(self):
        self.assertEqual(cov.analyze(op("BEGIN NULL; END;"))["statut"], "non_analysable:plsql")
        self.assertEqual(
            cov.analyze(op("INSERT ALL INTO T (A) VALUES (1) SELECT 1 FROM DUAL"))["statut"],
            "non_analysable:insert_all",
        )
        row = cov.analyze(op("SELECT FROM WHERE ((("))
        self.assertEqual(row["statut"], "erreur")
        self.assertTrue(row["message"])

    def test_bare_target_is_resolved_to_its_unique_trg_schema(self):
        self.assertEqual(cov.target_of("t"), "SDETRG.T")
        self.assertEqual(cov.target_of("SDETRG.T"), "SDETRG.T")
        self.assertEqual(cov.target_of("INCONNUE"), "INCONNUE")

    @unittest.skipUnless(hasattr(signal, "setitimer"), "Unix seulement")
    def test_time_limit_interrupts_a_long_analysis(self):
        with self.assertRaises(cov.Timeout), cov.time_limit(0.05):
            while True:
                pass


class SummaryTests(unittest.TestCase):
    def test_summary_counts_statuses_columns_and_unknown_tables(self):
        ok = {"op": "C.F.1", "cible": "T", "lignes": 10, "statut": "ok", "secondes": 1.5,
              "colonnes": 4, "exactes": 3, "etoile": 1, "sans_source": 0,
              "inconnues": ["SDESTG.TMP"], "hors_trac": ["X"]}  # fmt: skip
        bad = {"op": "C.F.2", "cible": "T", "lignes": 5, "statut": "erreur", "secondes": 0.1,
               "message": "ParseError: boom"}  # fmt: skip
        skipped = {"op": "C.F.3", "cible": "T", "lignes": 5, "statut": "non_analysable:plsql"}
        text = cov.summarize([ok, bad, skipped])
        self.assertIn("3 operations", text)
        self.assertIn("non_analysable:plsql : 1", text)
        self.assertIn("avec source", text)
        self.assertIn("75%", text)  # 3 colonnes sur 4
        self.assertIn("ParseError: boom", text)
        self.assertIn("SDESTG.TMP", text)
        self.assertIn("C.F.1 : X", text)


class DatabaseTests(unittest.TestCase):
    """Contre `docker/oracle-test` : lecture des operations, du dictionnaire et de TRAC_DATA."""

    @classmethod
    def setUpClass(cls):
        require_oracle()

    def test_every_operation_of_the_test_database_is_analyzed(self):
        ops, columns, trac = cov.load([], None)
        cov.init(columns, trac)
        rows = [cov.analyze((op, 60)) for op in ops]
        self.assertTrue(
            any(r["op"].endswith("W_CLIENT_360.4") and r["statut"] == "ok" for r in rows)
        )
        self.assertIn(f"{len(rows)} operations", cov.summarize(rows))
