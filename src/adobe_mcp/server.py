"""Adobe MCP Server — Full automation for all Adobe Creative Cloud apps.

Entry point for both pip (`adobe-mcp`) and direct execution (`python -m adobe_mcp`).
"""

from mcp.server.fastmcp import FastMCP

from adobe_mcp.apps import register_all_tools

mcp = FastMCP("adobe_mcp")
register_all_tools(mcp)


def main():
    """Run the MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
