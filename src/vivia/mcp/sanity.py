"""Tools jouets qui valident le mecanisme de tool call, sans logique metier."""

from fastmcp import FastMCP

from vivia.tools.sanity.calc import calc as _calc
from vivia.tools.sanity.now import now as _now
from vivia.tools.sanity.roll_dice import roll_dice as _roll_dice
from vivia.tools.sanity.text_stats import text_stats as _text_stats

mcp = FastMCP("vivia-sanity")

mcp.tool(_now, name="now")
mcp.tool(_calc, name="calc")
mcp.tool(_roll_dice, name="roll_dice")
mcp.tool(_text_stats, name="text_stats")
