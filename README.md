<h1 align="center">IllTool</h1>

<p align="center">
  <strong>Illustration-to-production toolkit for Adobe Illustrator on macOS</strong><br/>
  A native plugin (C++/Objective-C) plus a Python MCP pipeline for drawing, rigging, storyboarding, and automation.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/macOS-arm64-black?style=flat-square&logo=apple&logoColor=white"/>
  <img src="https://img.shields.io/badge/Illustrator-2026-FF9A00?style=flat-square&logo=adobeillustrator&logoColor=white"/>
  <img src="https://img.shields.io/badge/Vision-Apple_%2B_ONNX-blue?style=flat-square&logo=apple&logoColor=white"/>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square"/>
</p>

---

## What this is

Two projects in one repo:

1. **`plugin/` — IllTool Illustrator plugin**
   A native macOS Illustrator 2026 plugin (C++ + Objective-C panels). 13 task-focused modules that live inside Illustrator: subject cutout, perspective auto-match, symmetry correction, tracing, shape cleanup, smart layers, and more. Ships a local HTTP bridge (`127.0.0.1:8787`) so external tools can drive it.

2. **`src/ill_tool/` — Python MCP pipeline**
   A Model Context Protocol server for illustration-to-production work. Orchestrates drawing, rigging, animation, and storyboard workflows across Adobe CC apps (wraps the sibling `plugins/adobe-mcp-*` servers for PS, AI, AE).

You can use either half independently. The plugin is the day-to-day drawing surface; the MCP server is the batch / orchestration layer for agent workflows.

---

## Plugin: IllTool (macOS)

### Modules

| # | Module | What it does |
|---|--------|--------------|
| 1 | **Selection** | Smart selection by shape/color/surface identity |
| 2 | **Cleanup** | Average near-duplicate points, simplify shapes, clean up traces |
| 3 | **Perspective** | Auto-match VPs from a reference image (adaptive Canny, Hough, ML normals, optional 3-point); manual grid, snap-to-perspective, per-line color legend |
| 4 | **Merge** | Weld endpoints, join paths |
| 5 | **Grouping** | Group by surface identity (normal clusters), layer color presets |
| 6 | **Blend** | Interpolate between two paths with editable easing curves + saveable presets |
| 7 | **Shading** | Tonal fill / shading with light-direction widget + color sampling |
| 8 | **Decompose** | Break compounds, auto-decompose complex art |
| 9 | **Transform** | Relative / absolute transforms with live preview |
| 10 | **Trace** | Image → vectors with multiple backends: vtracer, OpenCV Contours, StarVector (ML), CartoonSeg, Apple Contours (Vision). Plus Normal Reference, Form Edge Extract, Depth Layers, Subject Cutout, Symmetry Correction, DiffVG Correction, Analyze Reference, Pose Detection |
| 11 | **Surface** | Normal-map driven surface extraction + grouping |
| 12 | **Pen** | Drawing with live preview, smart snaps, draw-in-layer mode |
| 13 | **Layer** | Smart layer panel with presets and activity accordion |

### Vision Intelligence

Cross-platform ML vision backend wrapping:

- **Apple Vision framework** — subject segmentation (`VNGenerateForegroundInstanceMaskRequest`), contour detection, body/face/hand pose
- **ONNX Runtime** — with CoreML execution provider on Apple Silicon
- **Metric3D v2** (ViT-S ONNX) — metric depth + surface normals from a single image
- **Depth Anything V2** — depth decomposition into layers

All model files in `plugin/models/`.

### Cutout workflow (example)

1. Open a reference image in Illustrator
2. **Trace panel → Subject Cutout → Preview** — Vision finds the subject, shows a green overlay
3. Shift-click to add regions, Option-click to subtract (mask-constrained flood fill)
4. **Cut Out** — creates vector cut lines on a new layer AND embeds a transparent-background PNG replacing the original raster

### Build / deploy

```bash
# Requires: Xcode, Adobe Illustrator 2026 SDK 30.2, Developer ID certificate
bash plugin/tools/deploy.sh
```

The script compiles against the SDK, codesigns with Apple Developer ID, submits for notarization, staples, and installs to `~/Developer/ai-plugins/IllTool.aip`. Restart Illustrator to load.

### Architecture

```
Illustrator (plugin loads on startup)
        │
        ├── 13 modules  ◄──┐
        ├── Panels (Objective-C, per module)
        ├── Annotator (draw overlays)
        ├── Timer op queue (10 Hz SDK context)
        └── HTTP bridge :8787
                │
                └── external clients (Python MCP, curl, Claude)
```

- `plugin/Source/*.cpp` — core plugin (startup, routing, bridge)
- `plugin/Source/modules/*.cpp` — per-feature module implementations
- `plugin/Source/panels/*.mm` — Objective-C++ panels (Cocoa NSViews)
- `plugin/Source/VisionEngine.cpp`, `VisionIntelligence.cpp`, `OnnxVisionBridge.cpp` — ML backends
- `plugin/models/` — ONNX weights (Metric3D, etc.)
- `plugin/Resources/en.lproj/Localizable.strings` — i18n infrastructure (213 strings)

---

## Python MCP pipeline (`ill-tool`)

### Install

```bash
pip install ill-tool
# or from source:
pip install -e .
```

### Run

```bash
python -m ill_tool
```

Registers as an MCP server. Point Claude Code, Claude Desktop, Codex CLI, or Gemini CLI at it. The sibling `plugins/adobe-mcp-ai`, `adobe-mcp-ps`, `adobe-mcp-ae` provide direct app automation; `ill_tool` orchestrates higher-level illustration-to-production flows (storyboard → rig → animate → export).

See `plugins/*/README.md` for per-app MCP servers.

---

## Repo layout

```
ill_tool/
├── plugin/                 # IllTool Illustrator plugin (C++/Obj-C)
│   ├── Source/             # Modules, panels, bridge, vision engine
│   ├── Resources/          # Localized strings, cursors
│   ├── models/             # ONNX weights
│   ├── blender/            # Blender render pass exporter
│   └── tools/deploy.sh     # Build + sign + notarize + install
├── src/ill_tool/           # Python MCP pipeline
├── plugins/
│   ├── adobe-mcp-ai/       # Illustrator MCP server
│   ├── adobe-mcp-ps/       # Photoshop MCP server
│   └── adobe-mcp-ae/       # After Effects MCP server
├── cep/                    # Legacy CEP extension (pre-plugin)
├── wiki/                   # Project knowledge base
├── thoughts/               # Handoffs, plans, research
└── docs/                   # Reference documentation
```

---

## Requirements

- **macOS** (Apple Silicon recommended; plugin is `arm64`)
- **Adobe Illustrator 2026** (SDK 30.2) for the plugin
- **Xcode** + Adobe Developer ID certificate to build
- **Python 3.10+** for the MCP pipeline
- **ONNX models** — download referenced in `plugin/models/THIRD_PARTY_NOTICES.md`

---

## Status

Active development. Branch: `fix/pen-tool-and-polish`. Recent work includes Vision Intelligence backend, symmetry correction, perspective auto-match enhancements, subject cutout with mask-constrained flood fill, localization infrastructure, and the Layer smart panel.

See `thoughts/shared/handoffs/` for session history and `wiki/index.md` for the project knowledge base.

---

## License

MIT — see [LICENSE](LICENSE).

Third-party model licenses: see `plugin/models/THIRD_PARTY_NOTICES.md`.
