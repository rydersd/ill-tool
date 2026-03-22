"""Standalone Premiere Pro MCP server — loads only common + Premiere tools.

Entry point: `adobe-mcp-pr` (registered in pyproject.toml)
"""

from mcp.server.fastmcp import FastMCP

from adobe_mcp.apps.common import register_common_tools
from adobe_mcp.apps.premiere import register_premiere_tools

mcp = FastMCP("adobe_premiere")
register_common_tools(mcp)
register_premiere_tools(mcp)


def main():
    """Run the Premiere Pro-only MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
