<p align="center">
  <img src="https://img.shields.io/badge/Adobe-FF0000?style=for-the-badge&logo=adobe&logoColor=white" alt="Adobe"/>
  <img src="https://img.shields.io/badge/MCP-Server-blueviolet?style=for-the-badge&logo=anthropic&logoColor=white" alt="MCP Server"/>
  <img src="https://img.shields.io/badge/Claude-Compatible-orange?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Compatible"/>
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"/>
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <br/>
  <a href="https://pypi.org/project/adobe-mcp/"><img src="https://img.shields.io/pypi/v/adobe-mcp?style=for-the-badge&logo=pypi&logoColor=white&label=PyPI" alt="PyPI"/></a>
  <a href="https://www.npmjs.com/package/adobe-mcp"><img src="https://img.shields.io/npm/v/adobe-mcp?style=for-the-badge&logo=npm&logoColor=white&label=npm" alt="npm"/></a>
</p>

<h1 align="center">Adobe MCP Server</h1>

<p align="center">
  <strong>Full Creative Cloud automation for Claude via the Model Context Protocol</strong><br/>
  Control Photoshop, Illustrator, Premiere Pro, After Effects, InDesign, Animate & more — directly from Claude conversations.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Tools-45_MCP_Tools-success?style=flat-square" alt="45 Tools"/>
  <img src="https://img.shields.io/badge/Apps-8_Adobe_Apps-FF0000?style=flat-square&logo=adobe&logoColor=white" alt="8 Apps"/>
  <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square" alt="MIT License"/>
  <img src="https://img.shields.io/badge/Platform-Windows_10%2F11-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Windows"/>
</p>

---

## Supported Applications

<p align="center">
  <img src="https://img.shields.io/badge/Photoshop-2026-31A8FF?style=for-the-badge&logo=adobephotoshop&logoColor=white" alt="Photoshop"/>
  <img src="https://img.shields.io/badge/Illustrator-30-FF9A00?style=for-the-badge&logo=adobeillustrator&logoColor=white" alt="Illustrator"/>
  <img src="https://img.shields.io/badge/Premiere_Pro-26-9999FF?style=for-the-badge&logo=adobepremierepro&logoColor=white" alt="Premiere Pro"/>
  <img src="https://img.shields.io/badge/After_Effects-26-9999FF?style=for-the-badge&logo=adobeaftereffects&logoColor=white" alt="After Effects"/>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/InDesign-FF3366?style=for-the-badge&logo=adobeindesign&logoColor=white" alt="InDesign"/>
  <img src="https://img.shields.io/badge/Animate-2024-FF0000?style=for-the-badge&logo=adobeanimate&logoColor=white" alt="Animate"/>
  <img src="https://img.shields.io/badge/Media_Encoder-9999FF?style=for-the-badge&logo=adobe&logoColor=white" alt="Media Encoder"/>
  <img src="https://img.shields.io/badge/Character_Animator-00D4B5?style=for-the-badge&logo=adobe&logoColor=white" alt="Character Animator"/>
</p>

| App | Version | COM | ExtendScript | Tools |
|-----|---------|-----|-------------|-------|
| ![PS](https://img.shields.io/badge/Photoshop-31A8FF?style=flat-square&logo=adobephotoshop&logoColor=white) | 2026 | ✅ | ✅ | 13 |
| ![AI](https://img.shields.io/badge/Illustrator-FF9A00?style=flat-square&logo=adobeillustrator&logoColor=white) | 30 | ✅ | ✅ | 5 |
| ![PR](https://img.shields.io/badge/Premiere_Pro-9999FF?style=flat-square&logo=adobepremierepro&logoColor=white) | 26 | ✅ | ✅ | 6 |
| ![AE](https://img.shields.io/badge/After_Effects-9999FF?style=flat-square&logo=adobeaftereffects&logoColor=white) | 26 | ✅ | ✅ | 6 |
| ![ID](https://img.shields.io/badge/InDesign-FF3366?style=flat-square&logo=adobeindesign&logoColor=white) | Latest | ✅ | ✅ | 3 |
| ![AN](https://img.shields.io/badge/Animate-FF0000?style=flat-square&logo=adobeanimate&logoColor=white) | 2024 | ✅ | ✅ | 2 |
| ![CH](https://img.shields.io/badge/Character_Animator-00D4B5?style=flat-square&logo=adobe&logoColor=white) | Latest | — | — | 1 |
| ![AME](https://img.shields.io/badge/Media_Encoder-9999FF?style=flat-square&logo=adobe&logoColor=white) | Latest | ✅ | ✅ | 1 |

---

## Requirements

<p>
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D6?style=flat-square&logo=windows&logoColor=white"/>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/Claude_Code_CLI-or_Desktop-orange?style=flat-square&logo=anthropic&logoColor=white"/>
  <img src="https://img.shields.io/badge/Adobe_Creative_Cloud-Any_Supported_App-FF0000?style=flat-square&logo=adobecreativecloud&logoColor=white"/>
</p>

- **Windows 10/11** (COM automation is Windows-only)
- **Python 3.10+** in PATH
- **One or more supported Adobe Creative Cloud apps**
- **Claude Code CLI** or **Claude Desktop App**

---

## Installation

### One-Command Install

```bash
# pip (recommended)
pip install adobe-mcp

# or npx (zero install, auto-creates venv)
npx adobe-mcp

# or npm global
npm install -g adobe-mcp
```

### Auto-Configure CLI Tools

After installing via pip, run the setup script to auto-configure all detected CLI tools:

**Windows (PowerShell):**
```powershell
# Auto-detects and configures Claude Code, Codex CLI, and Gemini CLI
powershell -ExecutionPolicy Bypass -File setup-cli.ps1
```

**Linux / macOS:**
```bash
./setup-cli.sh
```

Or configure each CLI manually:

<details>
<summary><b>Claude Code CLI</b></summary>

```bash
claude mcp add adobe-mcp -- python -m adobe_mcp
```

Or add to `~/.claude.json`:
```json
{
  "mcpServers": {
    "adobe-mcp": {
      "command": "python",
      "args": ["-m", "adobe_mcp"]
    }
  }
}
```
</details>

<details>
<summary><b>Claude Desktop App</b></summary>

Add to `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "adobe-mcp": {
      "command": "python",
      "args": ["-m", "adobe_mcp"]
    }
  }
}
```
</details>

<details>
<summary><b>Codex CLI</b></summary>

Add to `~/.codex/config.json`:
```json
{
  "mcpServers": {
    "adobe-mcp": {
      "command": "python",
      "args": ["-m", "adobe_mcp"]
    }
  }
}
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

Add to `~/.gemini/settings.json`:
```json
{
  "mcpServers": {
    "adobe-mcp": {
      "command": "python",
      "args": ["-m", "adobe_mcp"]
    }
  }
}
```
</details>

> **Restart** your CLI tool after configuration.

---

## Tool Reference

### Core / Cross-App (11 tools)

| Tool | Description |
|------|-------------|
| `adobe_list_apps` | List all supported Adobe apps and status |
| `adobe_app_status` | Check if a specific app is running |
| `adobe_launch_app` | Launch an Adobe application |
| `adobe_run_jsx` | Execute raw ExtendScript in an app |
| `adobe_run_jsx_file` | Execute an ExtendScript file |
| `adobe_run_powershell` | Execute PowerShell for COM automation |
| `adobe_open_file` | Open a file in the specified app |
| `adobe_save_file` | Save the active document |
| `adobe_close_document` | Close a document (with optional save) |
| `adobe_get_doc_info` | Get document metadata and properties |
| `adobe_list_fonts` | List available fonts |

### ![PS](https://img.shields.io/badge/Photoshop-31A8FF?style=flat-square&logo=adobephotoshop&logoColor=white) Photoshop (13 tools)

| Tool | Description |
|------|-------------|
| `adobe_ps_new_document` | Create a new document |
| `adobe_ps_layers` | Create, delete, rename, merge, reorder layers |
| `adobe_ps_filter` | Apply filters (blur, sharpen, noise, distort, stylize) |
| `adobe_ps_selection` | Make selections (rect, ellipse, magic wand, lasso, etc.) |
| `adobe_ps_transform` | Transform layers (scale, rotate, skew, flip, warp) |
| `adobe_ps_adjustment` | Add adjustment layers (curves, levels, hue/sat, color balance) |
| `adobe_ps_text` | Create and style text layers |
| `adobe_ps_export` | Export to PNG, JPEG, TIFF, PSD, PDF, WebP |
| `adobe_ps_batch` | Batch process files with an action |
| `adobe_ps_action` | Record and play Photoshop actions |
| `adobe_ps_smart_object` | Convert layers to smart objects |

### ![AI](https://img.shields.io/badge/Illustrator-FF9A00?style=flat-square&logo=adobeillustrator&logoColor=white) Illustrator (5 tools)

| Tool | Description |
|------|-------------|
| `adobe_ai_new_document` | Create a new document |
| `adobe_ai_shapes` | Draw shapes (rectangle, ellipse, polygon, star, spiral) |
| `adobe_ai_text` | Create and style text objects |
| `adobe_ai_path` | Create and manipulate paths |
| `adobe_ai_export` | Export to SVG, PDF, PNG, JPEG, EPS |

### ![PR](https://img.shields.io/badge/Premiere_Pro-9999FF?style=flat-square&logo=adobepremierepro&logoColor=white) Premiere Pro (6 tools)

| Tool | Description |
|------|-------------|
| `adobe_pr_project` | Create and open Premiere projects |
| `adobe_pr_sequence` | Create sequences with custom settings |
| `adobe_pr_media` | Import media files |
| `adobe_pr_timeline` | Add clips to timeline tracks |
| `adobe_pr_export` | Export via Adobe Media Encoder |
| `adobe_pr_effects` | Apply video and audio effects |

### ![AE](https://img.shields.io/badge/After_Effects-9999FF?style=flat-square&logo=adobeaftereffects&logoColor=white) After Effects (6 tools)

| Tool | Description |
|------|-------------|
| `adobe_ae_comp` | Create and manage compositions |
| `adobe_ae_layer` | Add and manage layers (solid, text, shape, null, camera) |
| `adobe_ae_property` | Set layer properties (position, scale, rotation, opacity) |
| `adobe_ae_expression` | Apply expressions to properties |
| `adobe_ae_effect` | Apply effects to layers |
| `adobe_ae_render` | Add to render queue and render |

### ![ID](https://img.shields.io/badge/InDesign-FF3366?style=flat-square&logo=adobeindesign&logoColor=white) InDesign (3 tools)

| Tool | Description |
|------|-------------|
| `adobe_id_document` | Create InDesign documents |
| `adobe_id_text` | Create text frames and apply styles |
| `adobe_id_image` | Place images in documents |

### ![AN](https://img.shields.io/badge/Animate-FF0000?style=flat-square&logo=adobeanimate&logoColor=white) Animate (2 tools)

| Tool | Description |
|------|-------------|
| `adobe_an_document` | Create documents (HTML5 Canvas, AIR, ActionScript) |
| `adobe_an_timeline` | Manage timeline layers and keyframes |

### ![AME](https://img.shields.io/badge/Media_Encoder-9999FF?style=flat-square&logo=adobe&logoColor=white) Media Encoder (1 tool)

| Tool | Description |
|------|-------------|
| `adobe_ame_encode` | Encode files with custom presets |

---

## Usage Examples

Once installed, use natural language in Claude:

```
"Open Photoshop, create a 1920x1080 document with a dark gradient background,
 and add the text 'Hello World' centered in white 72pt"

"In Illustrator, draw a red hexagon with a gold stroke and export it as SVG
 to my Desktop"

"Create a new Premiere Pro project, import all MP4s from C:/footage,
 and arrange them in a 4K sequence"

"In After Effects, create a 10-second comp and animate a text layer
 flying in from the left with motion blur"

"Batch export all PSD files in C:/designs to JPEG at 80% quality"

"Run this ExtendScript in Photoshop:
 app.activeDocument.flatten();
 app.activeDocument.save();"
```

---

## Architecture

```
Claude / Claude Code
        │
        ▼ MCP (stdio)
  adobe_mcp.py  (FastMCP server)
        │
   ┌────┴────┐
   ▼         ▼
PowerShell  ExtendScript (.jsx)
(COM auto)  (legacy scripting)
   │         │
   └────┬────┘
        ▼
  Adobe CC Apps
```

**Two automation backends** are used transparently:

| Backend | Method | Best For |
|---------|--------|----------|
| COM Automation | PowerShell `New-Object -ComObject` | App control, file ops, quick commands |
| ExtendScript | `estk` / `doScript` CLI | Complex document manipulation, batch ops |

---

## Troubleshooting

**App not responding**
> Make sure the target app is running first. Use `adobe_launch_app` or launch it manually, then retry.

**PowerShell execution policy error**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**`mcp` module not found**
```bash
pip install "mcp[cli]" pydantic httpx
```

**COM errors with Premiere Pro or After Effects**
> These apps sometimes require the window to be in the foreground (not minimized) for COM to work reliably.

**`python` not found in PATH**
> Install Python 3.10+ from [python.org](https://python.org) and ensure it's added to PATH during installation.

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built for <img src="https://img.shields.io/badge/Claude_Code-orange?style=flat-square&logo=anthropic&logoColor=white" alt="Claude Code"/> &nbsp;|&nbsp;
  Powered by <img src="https://img.shields.io/badge/MCP-Model_Context_Protocol-blueviolet?style=flat-square" alt="MCP"/>
</p>
