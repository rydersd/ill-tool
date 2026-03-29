"""Adobe MCP Server — Illustration-to-production pipeline via Adobe Creative Cloud.

Originally based on adobe-mcp by VoidChecksum:
    https://github.com/VoidChecksum/adobe-mcp

Extended with 200+ illustration-specific tools: contour scanning, skeleton
building, joint geometry, 3D form projection, curve fitting, rigging,
storyboarding, and animation pipeline automation.
"""

from adobe_mcp.server import mcp, main

__all__ = ["mcp", "main"]
__version__ = "0.2.0"
