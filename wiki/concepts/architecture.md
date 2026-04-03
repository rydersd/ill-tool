# Architecture

> Brief: FastMCP server with app-based module structure, 245+ tools across 8 Adobe apps.
> Tags: architecture, mcp, fastmcp, adobe
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Understanding the system architecture is essential for adding new tools, debugging execution paths, and planning feature work.

## Overview

ill_tool is an Adobe MCP (Model Context Protocol) server that provides unified programmatic control over Adobe Creative Cloud applications through Claude. It enables Claude to draw, rig, animate, and storyboard directly in Adobe apps via ExtendScript and COM automation.

## Server Structure

```
src/adobe_mcp/
  server.py            # FastMCP entry point, registers all app tools
  engine.py            # Execution engine: WebSocket relay + JSX subprocess fallback
  apps/
    illustrator/       # 185 tools (198 Python files) — primary focus
    photoshop/         # 16 tools
    premiere/          # 9 tools
    aftereffects/      # 16 tools
    indesign/          # 4 tools
    animate/           # 3 tools
    media_encoder/     # 3 tools
    common/            # 13 cross-app meta-tools
  jsx/
    polyfills.py       # ES3 JSON polyfill for Illustrator
  models/              # Pydantic input models (69 classes, 818 lines)
```

## Execution Backends

1. **WebSocket Relay** (preferred) — CEP panels inside Adobe apps connect to `ws://localhost:8765` for low-latency bidirectional communication
2. **JSX Subprocess** (fallback) — osascript/AppleScript sends ExtendScript to Adobe app, waits for result
3. **PowerShell COM** (Windows-only) — deeper access to some app features

## Entry Points

| Command | Server |
|---------|--------|
| `adobe-mcp` | All apps |
| `adobe-mcp-ai` | Illustrator only |
| `adobe-mcp-ps` | Photoshop only |
| `adobe-mcp-pr` | Premiere Pro only |
| `adobe-mcp-ae` | After Effects only |
| `adobe-mcp-id` | InDesign only |

## Tool Registration Pattern

Each module exposes a `register(mcp)` function. FastMCP decorates async tool handlers. Central `__init__.py` imports and registers all modules.

## Key Dependencies

- **Core**: mcp>=1.0.0, pydantic>=2.0.0, httpx, websockets, opencv-python-headless, vtracer, numpy, shapely
- **ML optional**: torch, transformers, trimesh, open3d
- **Timeline optional**: opentimelineio

## See Also
- [[WebSocket Relay]]
- [[ExtendScript Guide]]
- [[Tool Inventory]]
