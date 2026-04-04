"""Save or load a complete posable character (paths + skeleton + bindings).

A character template captures the full rig data AND the Illustrator path
geometry into a single JSON file.  This lets you:
  - save: export a fully-rigged character for reuse
  - load: recreate all paths + rig in a new document
  - list: browse saved templates
  - delete: remove a template

Templates are stored at:
    ~/.claude/memory/illustration/characters/{template_name}.json
unless a custom path is provided.
"""

import json
import os
import time

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiCharacterTemplateInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


def _default_template_dir() -> str:
    """Return the default directory for character templates."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "memory", "illustration", "characters")


def _template_path(template_name: str, custom_path: str | None = None) -> str:
    """Return the full file path for a template."""
    if custom_path:
        return custom_path
    d = _default_template_dir()
    return os.path.join(d, f"{template_name}.json")


def register(mcp):
    """Register the adobe_ai_character_template tool."""

    @mcp.tool(
        name="adobe_ai_character_template",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_template(params: AiCharacterTemplateInput) -> str:
        """Save or load a complete posable character template.

        Actions:
        - save: export the full rig + all path geometry to a template file
        - load: read a template, create all paths in Illustrator, restore rig
        - list: show available templates
        - delete: remove a template file
        """
        # ── LIST ──────────────────────────────────────────────
        if params.action == "list":
            template_dir = _default_template_dir()
            if not os.path.isdir(template_dir):
                return json.dumps({"templates": [], "directory": template_dir})

            templates = []
            for fname in sorted(os.listdir(template_dir)):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(template_dir, fname)
                try:
                    with open(fpath) as f:
                        data = json.load(f)
                    templates.append({
                        "name": fname.replace(".json", ""),
                        "character_name": data.get("character_name", ""),
                        "created": data.get("created", ""),
                        "joint_count": len(data.get("rig", {}).get("joints", {})),
                        "path_count": len(data.get("paths", {})),
                        "pose_count": len(data.get("rig", {}).get("poses", {})),
                    })
                except (json.JSONDecodeError, OSError):
                    templates.append({"name": fname, "error": "unreadable"})

            return json.dumps({
                "templates": templates,
                "directory": template_dir,
                "total": len(templates),
            })

        # ── DELETE ────────────────────────────────────────────
        if params.action == "delete":
            fpath = _template_path(params.template_name, params.template_path)
            if not os.path.exists(fpath):
                return json.dumps({
                    "error": f"Template not found: {fpath}"
                })
            os.remove(fpath)
            return json.dumps({"deleted": fpath})

        # ── SAVE ──────────────────────────────────────────────
        if params.action == "save":
            rig = _load_rig(params.character_name)

            # Collect all bound path names
            bindings = rig.get("bindings", {})
            all_path_names = set()
            for parts in bindings.values():
                if isinstance(parts, str):
                    all_path_names.add(parts)
                elif isinstance(parts, list):
                    all_path_names.update(parts)
            all_path_names = sorted(all_path_names)

            if not all_path_names:
                return json.dumps({
                    "error": "No paths are bound to bones. "
                             "Use adobe_ai_part_bind first."
                })

            # Read all path geometry from Illustrator
            path_names_js = json.dumps(all_path_names)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var pathNames = {path_names_js};
    var paths = {{}};

    for (var n = 0; n < pathNames.length; n++) {{
        var pName = pathNames[n];
        var item = null;
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{
                item = doc.layers[l].pathItems.getByName(pName);
                if (item) break;
            }} catch(e) {{}}
        }}
        if (!item) continue;

        var pts = item.pathPoints;
        var points = [];
        var handles = [];
        for (var i = 0; i < pts.length; i++) {{
            var p = pts[i];
            points.push([
                Math.round(p.anchor[0] * 1000) / 1000,
                Math.round(p.anchor[1] * 1000) / 1000
            ]);
            handles.push({{
                left: [
                    Math.round(p.leftDirection[0] * 1000) / 1000,
                    Math.round(p.leftDirection[1] * 1000) / 1000
                ],
                right: [
                    Math.round(p.rightDirection[0] * 1000) / 1000,
                    Math.round(p.rightDirection[1] * 1000) / 1000
                ]
            }});
        }}

        // Capture visual properties for reconstruction
        var fillColor = null;
        if (item.filled) {{
            try {{
                var fc = item.fillColor;
                if (fc.typename === "RGBColor") {{
                    fillColor = {{r: fc.red, g: fc.green, b: fc.blue}};
                }}
            }} catch(e) {{}}
        }}

        var strokeColor = null;
        if (item.stroked) {{
            try {{
                var sc = item.strokeColor;
                if (sc.typename === "RGBColor") {{
                    strokeColor = {{r: sc.red, g: sc.green, b: sc.blue}};
                }}
            }} catch(e) {{}}
        }}

        paths[pName] = {{
            points: points,
            handles: handles,
            closed: item.closed,
            filled: item.filled,
            fill_color: fillColor,
            stroked: item.stroked,
            stroke_color: strokeColor,
            stroke_width: item.stroked ? item.strokeWidth : 0,
            opacity: item.opacity,
            layer_name: item.layer.name
        }};
    }}

    return JSON.stringify(paths);
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})

            try:
                path_data = json.loads(result["stdout"])
            except json.JSONDecodeError:
                return json.dumps({
                    "error": "Failed to parse path data from Illustrator",
                    "raw": result["stdout"],
                })

            # Build the template
            template = {
                "template_name": params.template_name,
                "character_name": params.character_name,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "rig": rig,
                "paths": path_data,
            }

            # Write the template file
            fpath = _template_path(params.template_name, params.template_path)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                json.dump(template, f, indent=2)

            return json.dumps({
                "saved": fpath,
                "template_name": params.template_name,
                "character_name": params.character_name,
                "joint_count": len(rig.get("joints", {})),
                "bone_count": len(rig.get("bones", [])),
                "path_count": len(path_data),
                "pose_count": len(rig.get("poses", {})),
            })

        # ── LOAD ──────────────────────────────────────────────
        if params.action == "load":
            fpath = _template_path(params.template_name, params.template_path)
            if not os.path.exists(fpath):
                return json.dumps({"error": f"Template not found: {fpath}"})

            with open(fpath) as f:
                template = json.load(f)

            # Restore the rig file
            rig = template.get("rig", {})
            rig["character_name"] = params.character_name
            _save_rig(params.character_name, rig)

            # Recreate all paths in Illustrator
            path_data = template.get("paths", {})
            if not path_data:
                return json.dumps({
                    "loaded_rig": True,
                    "paths_created": 0,
                    "note": "Rig restored but no path data in template.",
                })

            path_data_js = json.dumps(path_data)
            jsx = f"""(function() {{
    var doc = app.activeDocument;
    var pathData = {path_data_js};
    var created = [];
    var errors = [];

    // Ensure target layers exist
    var layerCache = {{}};
    function getLayer(name) {{
        if (layerCache[name]) return layerCache[name];
        try {{
            layerCache[name] = doc.layers.getByName(name);
        }} catch(e) {{
            layerCache[name] = doc.layers.add();
            layerCache[name].name = name;
        }}
        return layerCache[name];
    }}

    for (var pName in pathData) {{
        if (!pathData.hasOwnProperty(pName)) continue;
        var pd = pathData[pName];

        try {{
            var targetLayer = getLayer(pd.layer_name || "Drawing");
            var item = targetLayer.pathItems.add();
            item.name = pName;

            // Set anchor points
            item.setEntirePath(pd.points);

            // Restore bezier handles
            var handles = pd.handles || [];
            for (var h = 0; h < item.pathPoints.length && h < handles.length; h++) {{
                item.pathPoints[h].leftDirection = handles[h].left;
                item.pathPoints[h].rightDirection = handles[h].right;
            }}

            item.closed = pd.closed || false;

            // Restore fill
            if (pd.filled && pd.fill_color) {{
                item.filled = true;
                var fc = new RGBColor();
                fc.red = pd.fill_color.r;
                fc.green = pd.fill_color.g;
                fc.blue = pd.fill_color.b;
                item.fillColor = fc;
            }} else {{
                item.filled = false;
            }}

            // Restore stroke
            if (pd.stroked && pd.stroke_color) {{
                item.stroked = true;
                var sc = new RGBColor();
                sc.red = pd.stroke_color.r;
                sc.green = pd.stroke_color.g;
                sc.blue = pd.stroke_color.b;
                item.strokeColor = sc;
                item.strokeWidth = pd.stroke_width || 1;
            }} else if (pd.stroked) {{
                item.stroked = true;
                item.strokeWidth = pd.stroke_width || 1;
            }} else {{
                item.stroked = false;
            }}

            // Restore opacity
            if (pd.opacity !== undefined && pd.opacity !== null) {{
                item.opacity = pd.opacity;
            }}

            created.push(pName);
        }} catch(e) {{
            errors.push(pName + ": " + e.message);
        }}
    }}

    return JSON.stringify({{
        paths_created: created,
        errors: errors
    }});
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result["success"]:
                return json.dumps({"error": result["stderr"]})

            try:
                jsx_data = json.loads(result["stdout"])
            except json.JSONDecodeError:
                jsx_data = {"raw": result["stdout"]}

            jsx_data["template_name"] = params.template_name
            jsx_data["character_name"] = params.character_name
            jsx_data["rig_restored"] = True
            jsx_data["joint_count"] = len(rig.get("joints", {}))
            jsx_data["bone_count"] = len(rig.get("bones", []))
            jsx_data["pose_count"] = len(rig.get("poses", {}))
            return json.dumps(jsx_data)

        return json.dumps({
            "error": f"Unknown action: {params.action}. "
                     f"Valid: save, load, list, delete"
        })
