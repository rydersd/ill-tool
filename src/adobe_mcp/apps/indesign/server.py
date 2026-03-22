"""Standalone InDesign MCP server — loads only common + InDesign tools.

Entry point: `adobe-mcp-id` (registered in pyproject.toml)
"""

from mcp.server.fastmcp import FastMCP

from adobe_mcp.apps.common import register_common_tools
from adobe_mcp.apps.indesign import register_indesign_tools

mcp = FastMCP("adobe_indesign")
register_common_tools(mcp)
register_indesign_tools(mcp)


def main():
    """Run the InDesign-only MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
