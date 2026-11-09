"""Contrat MCP Apps : ce qu'Open WebUI exige pour accepter et afficher une vue.

Ces verifications doublent la relecture du code hote : un tool sans
`resourceUri`, un type MIME different ou une ressource qui reference un domaine
externe est rejete ou rendu vide, sans message exploitable cote chat.
"""

import json
import re
import unittest

from fastmcp import Client

from vivia import ui
from vivia.mcp import mcp

# Valeurs imposees par `open_webui/utils/mcp/apps.py`.
APP_MIME_TYPE = "text/html;profile=mcp-app"
MAX_APP_BYTES = 5 * 1024 * 1024

APPS = {
    "chart": "ui://vivia/chart.html",
    "graph": "ui://vivia/graph.html",
    "sql_lineage": "ui://vivia/graph.html",
    "table": "ui://vivia/table.html",
}
DOCUMENTS = {
    "ui://vivia/chart.html": ui.CHART_HTML,
    "ui://vivia/graph.html": ui.GRAPH_HTML,
    "ui://vivia/table.html": ui.TABLE_HTML,
}


async def call(name, **arguments):
    async with Client(mcp) as client:
        return await client.call_tool(name, arguments)


class WiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_ui_tools_declare_their_resource(self):
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        for name, uri in APPS.items():
            with self.subTest(tool=name):
                meta = getattr(tools[name], "meta", None) or {}
                # `ui_resource_uri()` lit exactement cette cle et exige `ui://`.
                self.assertEqual((meta.get("ui") or {}).get("resourceUri"), uri)

    async def test_plain_tools_stay_plain(self):
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        for name in ("now", "calc", "roll_dice", "text_stats"):
            with self.subTest(tool=name):
                meta = getattr(tools[name], "meta", None) or {}
                self.assertNotIn("ui", meta)

    async def test_resources_are_served_as_mcp_apps(self):
        async with Client(mcp) as client:
            listed = {str(r.uri): r for r in await client.list_resources()}
            for uri in APPS.values():
                with self.subTest(uri=uri):
                    self.assertEqual(listed[uri].mime_type, APP_MIME_TYPE)
                    contents = await client.read_resource(uri)
                    self.assertEqual(contents[0].mime_type, APP_MIME_TYPE)
                    self.assertTrue(contents[0].text.startswith("<!doctype html>"))

    async def test_every_declared_resource_exists(self):
        async with Client(mcp) as client:
            available = {str(r.uri) for r in await client.list_resources()}
        self.assertTrue(set(APPS.values()) <= available)


class DocumentTests(unittest.TestCase):
    """La CSP de l'hote est `default-src 'none'` : tout doit etre embarque."""

    def test_no_external_reference(self):
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                self.assertNotRegex(html, r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""")
                self.assertNotIn("cdn.", html)

    def test_no_network_calls(self):
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "importScripts"):
                    self.assertNotIn(forbidden, html)

    def test_no_browser_storage(self):
        # L'iframe n'a pas `allow-same-origin` : y toucher leve une exception.
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
                    self.assertNotIn(forbidden, html)

    def test_within_the_host_size_limit(self):
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                self.assertLess(len(html.encode()), MAX_APP_BYTES)

    def test_handshake_is_complete(self):
        # L'hote n'envoie le resultat qu'apres `initialized` : sans cette
        # notification la vue reste vide, sans erreur visible.
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                for message in (
                    "ui/initialize",
                    "ui/notifications/initialized",
                    "ui/notifications/tool-result",
                    "ui/notifications/size-changed",
                ):
                    self.assertIn(message, html)
                self.assertIn(ui.PROTOCOL_VERSION, html)
                self.assertNotIn("__PROTOCOL__", html)

    def test_height_is_measured_on_the_body(self):
        # `documentElement.scrollHeight` ne redescend jamais sous la hauteur de
        # l'iframe : la vue resterait trop haute apres un filtrage. Le commentaire
        # du code le mentionne, donc seule la ligne de mesure est examinee.
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                measure = re.search(r"const height = (.+);", html)
                self.assertIsNotNone(measure)
                self.assertIn("document.body.getBoundingClientRect()", measure.group(1))
                self.assertNotIn("scrollHeight", measure.group(1))

    def test_dark_theme_is_defined(self):
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                self.assertIn('[data-theme="dark"]', html)


class PayloadTests(unittest.IsolatedAsyncioTestCase):
    """Le widget lit `structuredContent` : la forme du retour est un contrat."""

    async def test_chart_payload(self):
        result = await call(
            "chart",
            labels=["a", "b"],
            series=[{"name": "s", "values": [1, 2]}],
            title="T",
            kind="line",
        )
        data = result.structured_content
        self.assertEqual(data["labels"], ["a", "b"])
        self.assertEqual(data["series"][0]["values"], [1, 2])
        self.assertEqual(data["kind"], "line")
        self.assertEqual(data["title"], "T")

    async def test_graph_payload_keeps_implicit_nodes_empty(self):
        result = await call("graph", edges=[{"source": "a", "target": "b"}], directed=True)
        data = result.structured_content
        # Les noeuds non declares sont crees cote vue, pas inventes ici.
        self.assertEqual(data["nodes"], [])
        self.assertTrue(data["directed"])

    async def test_sql_lineage_payload_groups_columns_by_table(self):
        sql = "SELECT #pndate#, o.id FROM #SCH#.orders o"
        result = await call("sql_lineage", sql=sql, columns=True, target="dwh.f")
        data = result.structured_content
        self.assertEqual(data["edges"], [{"source": "#SCH#.ORDERS.ID", "target": "DWH.F.ID"}])
        self.assertEqual(data["nodes"][0], {"id": "#SCH#.ORDERS.ID", "group": "#SCH#.ORDERS"})
        self.assertTrue(data["directed"])

    async def test_table_payload_omits_absent_columns(self):
        result = await call("table", rows=[{"a": 1}])
        self.assertIsNone(result.structured_content["columns"])

    async def test_table_payload_keeps_explicit_columns(self):
        result = await call("table", rows=[[1, 2]], columns=["x", "y"])
        self.assertEqual(result.structured_content["columns"], ["x", "y"])

    async def test_payloads_are_json_serialisable(self):
        result = await call("chart", labels=["a"], series=[{"name": "s", "values": [1]}])
        json.dumps(result.structured_content)


class ColorTests(unittest.TestCase):
    def test_palette_is_injected_as_valid_hex(self):
        for uri, html in DOCUMENTS.items():
            with self.subTest(uri=uri):
                colors = re.search(r"const COLORS = \[(.*?)\]", html, re.S)
                self.assertIsNotNone(colors)
                self.assertEqual(len(re.findall(r"#[0-9a-f]{6}", colors.group(1))), 8)


if __name__ == "__main__":
    unittest.main()
