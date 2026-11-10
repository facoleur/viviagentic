"""Outils d'exploration Oracle : compilation, dictionnaire, recherche, requetes bornees."""

from fastmcp import FastMCP

from vivia.tools.explore.check_grain import check_grain as _check_grain
from vivia.tools.explore.column_stats import column_stats as _column_stats
from vivia.tools.explore.compile_sql import compile_sql as _compile_sql
from vivia.tools.explore.describe_table import describe_table as _describe_table
from vivia.tools.explore.find_usages import find_usages as _find_usages
from vivia.tools.explore.get_source import get_source as _get_source
from vivia.tools.explore.run_select import run_select as _run_select
from vivia.tools.explore.search_objects import search_objects as _search_objects

mcp = FastMCP("vivia-explore")

mcp.tool(_compile_sql, name="compile_sql")
mcp.tool(_describe_table, name="describe_table")
mcp.tool(_search_objects, name="search_objects")
mcp.tool(_run_select, name="run_select")
mcp.tool(_check_grain, name="check_grain")
mcp.tool(_column_stats, name="column_stats")
mcp.tool(_find_usages, name="find_usages")
mcp.tool(_get_source, name="get_source")
