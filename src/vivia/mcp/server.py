"""Serveur MCP : assemble les sous-serveurs par categorie d'outils.

Un process, un port, plusieurs montages FastMCP sans namespace (`mount(server)`) :
chaque categorie d'outils (et, a terme, chaque profil d'agent expert) vit dans son
propre module sous `vivia.mcp`, et ce fichier se contente de les assembler. Sans
namespace, les tools et resources gardent leurs noms/URIs d'origine.
"""

import os

from fastmcp import FastMCP

from vivia.mcp import explore, lineage, rendering, sanity

mcp = FastMCP("vivia")
mcp.mount(sanity.mcp)
mcp.mount(rendering.mcp)
mcp.mount(lineage.mcp)
mcp.mount(explore.mcp)


def main() -> None:
    mcp.run(transport="http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
