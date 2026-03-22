"""Standalone After Effects MCP server — loads only common + AE tools.

Entry point: `adobe-mcp-ae` (registered in pyproject.toml)
"""

from mcp.server.fastmcp import FastMCP

from adobe_mcp.apps.common import register_common_tools
from adobe_mcp.apps.aftereffects import register_aftereffects_tools

mcp = FastMCP("adobe_aftereffects")
register_common_tools(mcp)
register_aftereffects_tools(mcp)


def main():
    """Run the After Effects-only MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
