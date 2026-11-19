"""Retro-doc sans base ni LLM : Oracle et l'enricher sont remplaces par des faux."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vivia.retrodoc import cli, collect, llm, sql
from vivia.retrodoc.doc import Colonne, Redaction
from vivia.tools.explore.queries import DESCRIBE_TABLE_PK, VIEW_TABLES

OPS = [("SDE_LOAD", "P_TIERS", 1, "SDETRG.P_TIERS", "SELECT ID_TIERS, CD_SEG FROM SDAINT.V_TIERS")]
ANSWERS = {
    VIEW_TABLES: [("SDAINT.V_TIERS", "SDATRG.TIERS")],
    "V_M_TRAC_DATA": [
        ("SDE_LOAD", "P_TIERS", "SDETRG.P_TIERS", "SDAINT.V_TIERS"),
        ("DMD_LOAD", "D_TIERS", "DMDTRG.D_TIERS", "SDETRG.P_TIERS"),
        ("DMD_LOAD", "F_OPE", "DMDTRG.F_OPE", "SDETRG.P_TIERS"),
    ],
    "V_M_FLOWDATA": [("SDE_LOAD", "P_TIERS", "DAILY")],
    DESCRIBE_TABLE_PK: [("ID_TIERS",)],
    sql.TABLE_COMMENT: [("Tiers historises",)],
    sql.OPERATIONS.format(source="V_M_OPERATION"): OPS,
}


def fake_fetch(query, params=None, max_rows=0):
    if query == sql.COLUMNS:
        cols = {"P_TIERS": [("ID_TIERS", "NUMBER", None), ("CD_SEG", "VARCHAR2", "segment")]}
        return ["C", "T", "M"], cols.get(params["name"], [("ID_TIERS", "NUMBER", None)])
    if query.startswith("SELECT COUNT(*)"):
        return [], [(2000, 2000, 2000, 1500, 4)]
    if query.startswith("SELECT * FROM"):
        return ["ID_TIERS", "CD_SEG"], [(1, "PRO")]
    return [], ANSWERS[query]


REDACTION = Redaction(
    description="Tiers.",
    grain="une ligne = un tiers",
    colonnes=[
        Colonne(
            nom="CD_SEG",
            description="Segment.",
            regle_calcul=None,
            origine=["SDATRG.TIERS.CD_SEG"],
            preuve="SDE_LOAD.P_TIERS",
            confiance="haute",
        )
    ],
    acronymes_non_resolus=["SEG"],
)


class RetrodocTests(unittest.TestCase):
    def setUp(self):
        for name, fake in (("fetch", fake_fetch), ("union", lambda view, cols: view)):
            patcher = mock.patch.object(collect, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fw = collect.framework()

    def test_strategic_ranks_tables_by_reading_flows(self):
        self.assertEqual(collect.strategic(self.fw, 5), {"SDETRG.P_TIERS": 2, "SDATRG.TIERS": 1})

    def test_facts_resolve_views_and_keep_only_relevant_glossary(self):
        facts = collect.facts("SDETRG.P_TIERS", self.fw, {"SEG": "segment", "XYZ": "?"})
        self.assertEqual(list(facts["sources"]), ["SDATRG.TIERS"])
        self.assertEqual(facts["consommateurs"], ["DMD_LOAD.D_TIERS", "DMD_LOAD.F_OPE"])
        self.assertEqual(facts["producteurs"], [{"flux": "SDE_LOAD.P_TIERS", "frequence": "DAILY"}])
        self.assertEqual(facts["colonnes"][1]["taux_null"], 0.25)
        self.assertEqual(facts["glossaire"], {"SEG": "segment"})
        self.assertIn("SDAINT.V_TIERS", llm.render("table.j2", **facts))

    def test_document_merges_facts_text_and_overrides_and_reuses_the_draft(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with mock.patch.object(cli, "STORE", Path(folder.name)) as store:
            cli.save(store / "overrides" / "SDETRG.P_TIERS.json", {"grain": "corrige"})
            with mock.patch.object(llm, "enrich", return_value=REDACTION) as enrich:
                cli.document("SDETRG.P_TIERS", self.fw, {})
                cli.document("SDETRG.P_TIERS", self.fw, {})
            doc = cli.load(store / "doc" / "SDETRG.P_TIERS.json")
            self.assertEqual(enrich.call_count, 1)
            self.assertEqual(doc["grain"], "corrige")
            self.assertEqual(doc["colonnes"]["CD_SEG"]["origine"], ["SDATRG.TIERS.CD_SEG"])
            self.assertEqual(doc["colonnes"]["CD_SEG"]["cardinalite"], 4)
            self.assertNotIn("description", doc["colonnes"]["ID_TIERS"])
