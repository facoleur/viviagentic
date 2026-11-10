"""MCP Apps : les outils qui rendent une vue (chart, graph, table) au lieu de texte.

Voir `vivia.tools.rendering.views` pour le contrat avec l'hote.
"""

from fastmcp import FastMCP
from fastmcp.apps import AppConfig

from vivia.tools.rendering import views
from vivia.tools.rendering.chart import chart as _chart
from vivia.tools.rendering.graph import graph as _graph
from vivia.tools.rendering.table import table as _table

mcp = FastMCP("vivia-rendering")


@mcp.resource("ui://vivia/chart.html")
def chart_app() -> str:
    return views.CHART_HTML


@mcp.resource("ui://vivia/graph.html")
def graph_app() -> str:
    return views.GRAPH_HTML


@mcp.resource("ui://vivia/table.html")
def table_app() -> str:
    return views.TABLE_HTML


mcp.tool(_chart, name="chart", app=AppConfig(resource_uri="ui://vivia/chart.html"))
mcp.tool(_graph, name="graph", app=AppConfig(resource_uri="ui://vivia/graph.html"))
mcp.tool(_table, name="table", app=AppConfig(resource_uri="ui://vivia/table.html"))
