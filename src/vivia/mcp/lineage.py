"""Outils de lineage SQL. Rendu via le graphe de `vivia.mcp.rendering`."""

from fastmcp import FastMCP
from fastmcp.apps import AppConfig

from vivia.tools.lineage.sql_lineage import sql_lineage as _sql_lineage

mcp = FastMCP("vivia-lineage")

mcp.tool(_sql_lineage, name="sql_lineage", app=AppConfig(resource_uri="ui://vivia/graph.html"))
