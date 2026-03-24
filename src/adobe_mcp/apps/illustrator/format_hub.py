"""Universal export hub — route exports to the correct format tool.

Provides a single entry point for all export formats, with a registry
that maps format names to their corresponding tools and required
dependencies. Checks availability based on installed packages.

Pure Python — no JSX or Adobe required.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiFormatHubInput(BaseModel):
    """Universal export hub for all supported formats."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: export, list_formats, status",
    )
    format_name: Optional[str] = Field(
        default=None,
        description="Export format (e.g. 'lottie', 'spine', 'usdz')",
    )
    data: Optional[dict] = Field(
        default=None,
        description="Data to export (format-specific)",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier for export",
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Output file path (auto-generated if None)",
    )


# ---------------------------------------------------------------------------
# Format registry
# ---------------------------------------------------------------------------

FORMAT_REGISTRY: dict[str, dict] = {
    "otio": {
        "tool": "otio_export",
        "dep": "opentimelineio",
        "desc": "Universal timeline",
        "extension": ".otio",
    },
    "spine": {
        "tool": "spine_export",
        "dep": None,
        "desc": "Game animation",
        "extension": ".json",
    },
    "rive": {
        "tool": "rive_export",
        "dep": None,
        "desc": "Interactive web",
        "extension": ".riv",
    },
    "lottie": {
        "tool": "lottie_workflow",
        "dep": None,
        "desc": "Web/mobile animation",
        "extension": ".json",
    },
    "live2d": {
        "tool": "live2d_export",
        "dep": None,
        "desc": "VTuber/character",
        "extension": ".moc3",
    },
    "usdz": {
        "tool": "export_usdz",
        "dep": "trimesh",
        "desc": "Apple ecosystem",
        "extension": ".usdz",
    },
    "fcpxml": {
        "tool": "edl_export",
        "dep": None,
        "desc": "Final Cut Pro",
        "extension": ".fcpxml",
    },
    "edl": {
        "tool": "edl_export",
        "dep": None,
        "desc": "Universal edit list",
        "extension": ".edl",
    },
    "pdf": {
        "tool": "pdf_export",
        "dep": None,
        "desc": "Storyboard PDF",
        "extension": ".pdf",
    },
}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def available_formats(installed_deps: Optional[set[str]] = None) -> dict:
    """Check which formats can be exported based on installed packages.

    If installed_deps is None, auto-detects by attempting imports.
    Formats with dep=None are always available.

    Args:
        installed_deps: set of installed package names (for testing/override).

    Returns:
        dict with available and unavailable format lists.
    """
    if installed_deps is None:
        installed_deps = set()
        # Auto-detect common optional deps
        for pkg in {"opentimelineio", "trimesh"}:
            try:
                __import__(pkg)
                installed_deps.add(pkg)
            except ImportError:
                pass

    available = []
    unavailable = []

    for fmt_name, fmt_info in FORMAT_REGISTRY.items():
        dep = fmt_info["dep"]
        entry = {
            "format": fmt_name,
            "tool": fmt_info["tool"],
            "description": fmt_info["desc"],
            "extension": fmt_info["extension"],
            "dependency": dep,
        }

        if dep is None or dep in installed_deps:
            entry["available"] = True
            available.append(entry)
        else:
            entry["available"] = False
            entry["missing_dep"] = dep
            unavailable.append(entry)

    return {
        "available": available,
        "unavailable": unavailable,
        "available_count": len(available),
        "unavailable_count": len(unavailable),
        "total_formats": len(FORMAT_REGISTRY),
    }


def route_export(format_name: str, data: Optional[dict] = None) -> dict:
    """Dispatch to the correct export tool for the given format.

    Validates that the format exists in the registry and returns the
    routing information. The actual export is handled by the referenced
    tool via MCP dispatch.

    Args:
        format_name: name of the target format (must be in FORMAT_REGISTRY).
        data: export data to pass to the target tool.

    Returns:
        dict with routing info (tool name, params) or error.
    """
    if not format_name or not format_name.strip():
        return {"error": "format_name is required"}

    fmt_key = format_name.lower().strip()
    if fmt_key not in FORMAT_REGISTRY:
        return {
            "error": f"Unknown format: '{format_name}'",
            "available_formats": sorted(FORMAT_REGISTRY.keys()),
        }

    fmt_info = FORMAT_REGISTRY[fmt_key]

    # Check if dependency is available
    dep = fmt_info["dep"]
    if dep:
        try:
            __import__(dep)
        except ImportError:
            return {
                "error": f"Format '{fmt_key}' requires package '{dep}' which is not installed",
                "install_hint": f"pip install {dep}",
            }

    return {
        "routed": True,
        "format": fmt_key,
        "tool": fmt_info["tool"],
        "description": fmt_info["desc"],
        "extension": fmt_info["extension"],
        "data": data,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_format_hub tool."""

    @mcp.tool(
        name="adobe_ai_format_hub",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_format_hub(params: AiFormatHubInput) -> str:
        """Universal export hub — route to the correct format exporter.

        Actions:
        - export: route data to the appropriate format exporter
        - list_formats: show all supported formats and availability
        - status: show hub configuration
        """
        action = params.action.lower().strip()

        if action == "status":
            fmt_info = available_formats()
            return json.dumps({
                "action": "status",
                "tool": "format_hub",
                "total_formats": fmt_info["total_formats"],
                "available_count": fmt_info["available_count"],
                "ready": True,
            }, indent=2)

        elif action == "list_formats":
            return json.dumps({
                "action": "list_formats",
                **available_formats(),
            }, indent=2)

        elif action == "export":
            if not params.format_name:
                return json.dumps({"error": "export requires format_name"})

            result = route_export(params.format_name, params.data)
            if "error" not in result:
                result["action"] = "export"
                result["character_name"] = params.character_name
                if params.output_path:
                    result["output_path"] = params.output_path

            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["export", "list_formats", "status"],
            })
