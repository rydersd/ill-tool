# adobe-mcp

Full Adobe Creative Cloud automation for Claude via MCP -- 45 tools for Photoshop, Illustrator, Premiere Pro, After Effects, InDesign, Animate & more.

## Quick Start

```bash
# Run directly (no install needed)
npx adobe-mcp

# Or install globally
npm install -g adobe-mcp
adobe-mcp
```

## Requirements

- **Python 3.10+** in PATH
- **Windows 10/11** (COM automation for Adobe apps)
- **One or more Adobe Creative Cloud applications**

The wrapper automatically creates a Python virtual environment and installs dependencies on first run. No manual Python setup needed.

## Claude Configuration

### Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "adobe": {
      "command": "npx",
      "args": ["-y", "adobe-mcp"]
    }
  }
}
```

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "adobe": {
      "command": "npx",
      "args": ["-y", "adobe-mcp"]
    }
  }
}
```

## What You Can Do

Once configured, use natural language in Claude:

- "Open Photoshop, create a 1920x1080 canvas with a gradient background"
- "In Illustrator, draw a red hexagon and export it as SVG"
- "Create a Premiere Pro project and import all MP4s from a folder"
- "In After Effects, animate text flying in from the left"
- "Batch export all PSD files to JPEG at 80% quality"

## Supported Apps

| App | Tools |
|-----|-------|
| Photoshop | 13 |
| Illustrator | 5 |
| Premiere Pro | 6 |
| After Effects | 6 |
| InDesign | 3 |
| Animate | 2 |
| Character Animator | 1 |
| Media Encoder | 1 |
| **Core / Cross-App** | **11** |

## How It Works

The npm package is a thin wrapper that:

1. Finds Python 3.10+ on your system
2. Creates a virtual environment in `~/.cache/adobe-mcp/venv`
3. Installs Python dependencies (`mcp`, `pydantic`, `httpx`)
4. Runs the MCP server with stdio transport

All setup happens automatically on first run. Subsequent launches skip straight to starting the server.

## License

MIT
