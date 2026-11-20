"""Couverture du lignage colonne : analyse d'une operation et resume, sans base."""

import json
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_operation_without_target_table(self):
        """TABLE_CIBLE vide : un INSERT garde sa table, un SELECT seul est signale."""
        job = lambda sql: (("CH", "T", 1, None, None, sql), 60)  # noqa: E731
        row = cov.analyze(job("INSERT INTO SDETRG.T (A) SELECT t.ID_TIERS FROM SDEINT.V_P_TIERS t"))
        self.assertEqual((row["statut"], row["colonnes"], row["cible"]), ("ok", 1, None))
        self.assertEqual(cov.analyze(job("SELECT 1 FROM DUAL"))["statut"], "sans_cible")

    def test_analyze_never_raises(self):
        with mock.patch.object(cov, "_analyze", side_effect=AttributeError("boom")):
            row = cov.analyze(op("SELECT 1 FROM DUAL"))
        self.assertEqual((row["statut"], row["message"]), ("erreur", "AttributeError: boom"))

    def test_bare_target_is_resolved_to_its_unique_trg_schema(self):
        self.assertEqual(cov.target_of("t"), "SDETRG.T")
        self.assertEqual(cov.target_of("SDETRG.T"), "SDETRG.T")
        self.assertEqual(cov.target_of("INCONNUE"), "INCONNUE")

    @unittest.skipUnless(hasattr(signal, "setitimer"), "Unix seulement")
    def test_time_limit_interrupts_a_long_analysis(self):
        with self.assertRaises(cov.Timeout), cov.time_limit(0.05):
            while True:
                pass


class Inline:
    """ProcessPoolExecutor sans processus : meme interface, execute sur place."""

    def __init__(self, workers, initializer, initargs):
        initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, items, chunksize=1):
        return map(fn, items)


class MainTests(unittest.TestCase):
    def run_main(self, ops, *flags):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patches = [
            mock.patch.object(cov, "OUT", Path(folder.name)),
            mock.patch.object(cov, "load", lambda cibles, limit: (ops, COLUMNS, TRAC)),
            mock.patch.object(cov, "ProcessPoolExecutor", Inline),
            mock.patch.object(sys, "argv", ["vivia-lineage-coverage", *flags]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        cov.main()
        return Path(folder.name)

    def test_rows_are_written_as_they_come_and_resume_skips_the_done_ones(self):
        sql = "SELECT t.* FROM SDEINT.V_P_TIERS t"
        ops = [("CH", "F1", 1, None, "T", sql), ("CH", "F2", 1, None, "T", sql)]
        out = self.run_main(ops[:1])
        self.assertEqual(len((out / "report.jsonl").read_text().splitlines()), 1)

        with mock.patch.object(cov, "analyze", wraps=cov.analyze) as analyze:
            self.run_main_again(out, ops)
        self.assertEqual(analyze.call_count, 1)  # seule F2 est analysee
        lines = (out / "report.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(x)["op"] for x in lines], ["CH.F1.1", "CH.F2.1"])

    def run_main_again(self, out, ops):
        with (
            mock.patch.object(cov, "OUT", out),
            mock.patch.object(cov, "load", lambda cibles, limit: (ops, COLUMNS, TRAC)),
            mock.patch.object(cov, "ProcessPoolExecutor", Inline),
            mock.patch.object(sys, "argv", ["vivia-lineage-coverage", "--resume"]),
        ):
            cov.main()


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
