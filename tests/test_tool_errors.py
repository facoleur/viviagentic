"""Erreurs des outils : toujours un texte que l'agent peut exploiter, sans base."""

import inspect
import types
import unittest
from unittest import mock

import oracledb

from vivia.oracle import client
from vivia.oracle.identifiers import UnknownObject
from vivia.tools.errors import guarded
from vivia.tools.explore.compile_sql import compile_sql
from vivia.tools.explore.get_dependencies import get_dependencies
from vivia.tools.explore.run_select import run_select


def oracle_error(code, message):
    return oracledb.DatabaseError(types.SimpleNamespace(full_code=code, message=message))


def failing(error):
    @guarded
    def tool(table: str) -> str:
        """Doc."""
        raise error

    return tool


class GuardedTests(unittest.TestCase):
    def test_unknown_object_and_bad_input_are_told_plainly(self):
        self.assertEqual(
            failing(UnknownObject("X"))("x"),
            "Erreur : objet inconnu : X. Utiliser search_objects pour le retrouver.",
        )
        self.assertEqual(failing(ValueError("colonne invalide"))("x"), "Erreur : colonne invalide")
        self.assertEqual(failing(LookupError("vue absente"))("x"), "Erreur : vue absente")

    def test_oracle_errors_come_with_the_code_and_a_next_step(self):
        text = failing(oracle_error("ORA-00942", "table or view does not exist\n"))("x")
        self.assertEqual(
            text,
            "Erreur Oracle ORA-00942 : table or view does not exist "
            "Table ou vue inexistante ou non accessible : verifier le nom (search_objects).",
        )
        self.assertIn("Delai depasse", failing(oracle_error("DPY-4024", "call timeout"))("x"))
        # Sans conseil connu, le code et le message suffisent.
        self.assertEqual(
            failing(oracle_error("ORA-01476", "divisor is equal to zero"))("x"),
            "Erreur Oracle ORA-01476 : divisor is equal to zero",
        )

    def test_a_bug_is_reported_with_the_tool_name_not_raised(self):
        with self.assertLogs("vivia.tools.errors", "ERROR"):
            text = failing(RuntimeError("boom"))("x")
        self.assertIn("Erreur interne dans tool (RuntimeError : boom)", text)

    def test_the_wrapper_keeps_the_signature_and_the_doc_the_agent_reads(self):
        tool = failing(ValueError())
        self.assertEqual(list(inspect.signature(tool).parameters), ["table"])
        self.assertEqual(tool.__doc__, "Doc.")
        self.assertEqual(tool.__name__, "tool")


class RealToolsTests(unittest.TestCase):
    def test_rejected_sql_never_reaches_the_database(self):
        for tool in (run_select, compile_sql):
            self.assertTrue(tool("DROP TABLE t").startswith("Rejete"), tool.__name__)

    def test_an_oracle_failure_inside_a_tool_is_returned(self):
        def fetch(*args, **kwargs):
            raise oracle_error("ORA-00904", '"X": invalid identifier')

        with (
            mock.patch.object(client, "fetch", fetch),
            mock.patch("vivia.tools.explore.framework.union", return_value="V"),
        ):
            text = get_dependencies("P_FLUX")
        self.assertIn("Erreur Oracle ORA-00904", text)
        self.assertIn("describe_table", text)
