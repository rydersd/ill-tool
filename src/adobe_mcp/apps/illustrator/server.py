"""Standalone Illustrator MCP server — loads only common + Illustrator tools.

Entry point: `adobe-mcp-ai` (registered in pyproject.toml)

This starts a focused server with ~20 tools instead of the full 54,
saving ~6K tokens of tool descriptions in the LLM system prompt.
Ideal for dedicated Illustrator sessions.
"""

from mcp.server.fastmcp import FastMCP

from adobe_mcp.apps.common import register_common_tools
from adobe_mcp.apps.illustrator import register_illustrator_tools

mcp = FastMCP("adobe_illustrator")
register_common_tools(mcp)
register_illustrator_tools(mcp)


def main():
    """Run the Illustrator-only MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
