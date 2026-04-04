"""Auto-sort paths into named layers by spatial position or hierarchy.

Three strategies:
- spatial: divide the artboard into thirds by Y position and move items to
  "head" (top), "body" (middle), and "limbs" (bottom) layers.
- hierarchy: check bounding-box containment to sort items into
  "background" (outermost), "features" (contained), and "details" (nested).
- manifest: use a shape manifest from analyze_reference to match items
  to layers by centroid proximity.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiLayerAutoOrganizeInput


def register(mcp):
    """Register the adobe_ai_layer_auto_organize tool."""

    @mcp.tool(
        name="adobe_ai_layer_auto_organize",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_layer_auto_organize(params: AiLayerAutoOrganizeInput) -> str:
        """Auto-sort pathItems into named layers based on spatial position,
        bounding-box containment, or a shape manifest from analyze_reference.

        Strategies:
        - spatial: top/middle/bottom thirds -> head/body/limbs layers.
        - hierarchy: outer/inner/nested containment -> background/features/details.
        - manifest: match items to manifest layers by centroid proximity.
        """
        escaped_source = escape_jsx_string(params.source_layer)
        escaped_prefix = escape_jsx_string(params.prefix)

        if params.strategy == "spatial":
            jsx = _build_spatial_jsx(escaped_source, escaped_prefix)
        elif params.strategy == "hierarchy":
            jsx = _build_hierarchy_jsx(escaped_source, escaped_prefix)
        elif params.strategy == "manifest":
            if not params.shape_manifest:
                return json.dumps({
                    "error": "manifest strategy requires 'shape_manifest' parameter."
                })
            # Validate JSON before embedding
            try:
                manifest_data = json.loads(params.shape_manifest)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid shape_manifest JSON: {e}"})

            jsx = _build_manifest_jsx(
                escaped_source, escaped_prefix, json.dumps(manifest_data)
            )
        else:
            return json.dumps({
                "error": f"Unknown strategy: {params.strategy}. Valid: spatial, hierarchy, manifest"
            })

        result = await _async_run_jsx("illustrator", jsx)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        return result["stdout"]


def _build_spatial_jsx(escaped_source: str, escaped_prefix: str) -> str:
    """JSX: sort pathItems into top/middle/bottom layers by Y center position."""
    return f"""(function() {{
    var doc = app.activeDocument;

    // Get source layer
    var srcLayer = null;
    try {{ srcLayer = doc.layers.getByName("{escaped_source}"); }} catch(e) {{}}
    if (!srcLayer) return JSON.stringify({{error: "Source layer not found: {escaped_source}"}});

    // Get artboard bounds for zone calculation
    var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abTop = abRect[1];
    var abBottom = abRect[3];
    var totalHeight = abTop - abBottom;  // AI Y: top > bottom
    var thirdH = totalHeight / 3;

    // Zone boundaries (in AI coordinates where Y increases upward)
    var topZoneBound = abTop - thirdH;       // below this = middle zone
    var bottomZoneBound = abTop - 2 * thirdH; // below this = bottom zone

    // Collect all pathItems with their center Y
    var items = [];
    for (var i = srcLayer.pathItems.length - 1; i >= 0; i--) {{
        var p = srcLayer.pathItems[i];
        var gb = p.geometricBounds;
        var centerY = (gb[1] + gb[3]) / 2;
        items.push({{item: p, centerY: centerY, name: p.name || ("path_" + i)}});
    }}

    if (items.length === 0) return JSON.stringify({{error: "No pathItems found on source layer."}});

    // Layer names
    var prefix = "{escaped_prefix}";
    var zoneNames = [prefix + "head", prefix + "body", prefix + "limbs"];

    // Create or find target layers
    function getOrCreateLayer(name) {{
        for (var l = 0; l < doc.layers.length; l++) {{
            if (doc.layers[l].name === name) return doc.layers[l];
        }}
        var nl = doc.layers.add();
        nl.name = name;
        return nl;
    }}

    var headLayer = getOrCreateLayer(zoneNames[0]);
    var bodyLayer = getOrCreateLayer(zoneNames[1]);
    var limbsLayer = getOrCreateLayer(zoneNames[2]);

    var counts = {{head: 0, body: 0, limbs: 0}};

    for (var j = 0; j < items.length; j++) {{
        var cy = items[j].centerY;
        if (cy >= topZoneBound) {{
            items[j].item.move(headLayer, ElementPlacement.PLACEATEND);
            counts.head++;
        }} else if (cy >= bottomZoneBound) {{
            items[j].item.move(bodyLayer, ElementPlacement.PLACEATEND);
            counts.body++;
        }} else {{
            items[j].item.move(limbsLayer, ElementPlacement.PLACEATEND);
            counts.limbs++;
        }}
    }}

    return JSON.stringify({{
        strategy: "spatial",
        layers_created: zoneNames,
        items_per_layer: counts,
        total_items: items.length
    }});
}})();"""


def _build_hierarchy_jsx(escaped_source: str, escaped_prefix: str) -> str:
    """JSX: sort pathItems by bounding-box containment depth."""
    return f"""(function() {{
    var doc = app.activeDocument;

    var srcLayer = null;
    try {{ srcLayer = doc.layers.getByName("{escaped_source}"); }} catch(e) {{}}
    if (!srcLayer) return JSON.stringify({{error: "Source layer not found: {escaped_source}"}});

    // Gather all pathItems with bounds
    var items = [];
    for (var i = srcLayer.pathItems.length - 1; i >= 0; i--) {{
        var p = srcLayer.pathItems[i];
        var gb = p.geometricBounds; // [left, top, right, bottom]
        var area = (gb[2] - gb[0]) * (gb[1] - gb[3]);
        items.push({{
            item: p,
            left: gb[0], top: gb[1], right: gb[2], bottom: gb[3],
            area: area,
            name: p.name || ("path_" + i),
            depth: 0  // how many items contain this one
        }});
    }}

    if (items.length === 0) return JSON.stringify({{error: "No pathItems found on source layer."}});

    // Check containment: A contains B if A's bounds fully enclose B's bounds
    function contains(a, b) {{
        return a.left <= b.left && a.top >= b.top && a.right >= b.right && a.bottom <= b.bottom;
    }}

    // Compute containment depth for each item
    for (var j = 0; j < items.length; j++) {{
        for (var k = 0; k < items.length; k++) {{
            if (j !== k && contains(items[k], items[j])) {{
                items[j].depth++;
            }}
        }}
    }}

    // Classify: depth 0 = background, depth 1 = features, depth 2+ = details
    var prefix = "{escaped_prefix}";
    var layerNames = [prefix + "background", prefix + "features", prefix + "details"];

    function getOrCreateLayer(name) {{
        for (var l = 0; l < doc.layers.length; l++) {{
            if (doc.layers[l].name === name) return doc.layers[l];
        }}
        var nl = doc.layers.add();
        nl.name = name;
        return nl;
    }}

    var bgLayer = getOrCreateLayer(layerNames[0]);
    var featLayer = getOrCreateLayer(layerNames[1]);
    var detailLayer = getOrCreateLayer(layerNames[2]);

    var counts = {{background: 0, features: 0, details: 0}};

    for (var m = 0; m < items.length; m++) {{
        var d = items[m].depth;
        if (d === 0) {{
            items[m].item.move(bgLayer, ElementPlacement.PLACEATEND);
            counts.background++;
        }} else if (d === 1) {{
            items[m].item.move(featLayer, ElementPlacement.PLACEATEND);
            counts.features++;
        }} else {{
            items[m].item.move(detailLayer, ElementPlacement.PLACEATEND);
            counts.details++;
        }}
    }}

    return JSON.stringify({{
        strategy: "hierarchy",
        layers_created: layerNames,
        items_per_layer: counts,
        total_items: items.length
    }});
}})();"""


def _build_manifest_jsx(
    escaped_source: str, escaped_prefix: str, manifest_json: str
) -> str:
    """JSX: match pathItems to manifest layers by centroid proximity."""
    return f"""(function() {{
    var doc = app.activeDocument;

    var srcLayer = null;
    try {{ srcLayer = doc.layers.getByName("{escaped_source}"); }} catch(e) {{}}
    if (!srcLayer) return JSON.stringify({{error: "Source layer not found: {escaped_source}"}});

    // Parse the shape manifest
    var manifest = {manifest_json};

    // Extract layer assignments from manifest's drawing_plan if present
    var layerPlan = {{}};  // shape_index -> layer_name
    var planLayers = [];
    if (manifest.drawing_plan && manifest.drawing_plan.layers) {{
        var dpl = manifest.drawing_plan.layers;
        for (var li = 0; li < dpl.length; li++) {{
            var layerDef = dpl[li];
            var lName = layerDef.name || ("layer_" + li);
            planLayers.push(lName);
            if (layerDef.shapes) {{
                for (var si = 0; si < layerDef.shapes.length; si++) {{
                    layerPlan[layerDef.shapes[si]] = lName;
                }}
            }}
        }}
    }}

    // Collect manifest shape centroids (from shapes array)
    var manifestShapes = manifest.shapes || [];
    var manifestCentroids = [];
    for (var ms = 0; ms < manifestShapes.length; ms++) {{
        var s = manifestShapes[ms];
        var cx = 0, cy = 0;
        if (s.center) {{
            cx = s.center[0] || 0;
            cy = s.center[1] || 0;
        }}
        manifestCentroids.push({{index: ms, cx: cx, cy: cy, layer: layerPlan[ms] || null}});
    }}

    // Collect all pathItems with centroids
    var items = [];
    for (var i = srcLayer.pathItems.length - 1; i >= 0; i--) {{
        var p = srcLayer.pathItems[i];
        var gb = p.geometricBounds;
        var pcx = (gb[0] + gb[2]) / 2;
        var pcy = (gb[1] + gb[3]) / 2;
        items.push({{item: p, cx: pcx, cy: pcy, name: p.name || ("path_" + i)}});
    }}

    if (items.length === 0) return JSON.stringify({{error: "No pathItems found on source layer."}});

    // Get artboard dimensions for coordinate normalization (manifest uses pixel coords)
    var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abW = abRect[2] - abRect[0];
    var abH = abRect[1] - abRect[3];

    // Determine unique layer names from the plan, fallback to prefix-based names
    var prefix = "{escaped_prefix}";
    if (planLayers.length === 0) {{
        planLayers = [prefix + "primary", prefix + "secondary", prefix + "accent"];
    }}

    function getOrCreateLayer(name) {{
        for (var l = 0; l < doc.layers.length; l++) {{
            if (doc.layers[l].name === name) return doc.layers[l];
        }}
        var nl = doc.layers.add();
        nl.name = name;
        return nl;
    }}

    // Match each path item to closest manifest shape by centroid distance
    var layerCounts = {{}};
    var assignments = [];

    for (var j = 0; j < items.length; j++) {{
        var bestDist = Infinity;
        var bestShape = -1;

        for (var k = 0; k < manifestCentroids.length; k++) {{
            // Normalize manifest centroid to artboard coordinates
            // Manifest is in image pixels; scale to artboard space
            var msCx = manifestCentroids[k].cx;
            var msCy = manifestCentroids[k].cy;

            var dx = items[j].cx - msCx;
            var dy = items[j].cy - msCy;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < bestDist) {{
                bestDist = dist;
                bestShape = k;
            }}
        }}

        // Determine target layer
        var targetLayerName = prefix + "unmatched";
        if (bestShape >= 0 && manifestCentroids[bestShape].layer) {{
            targetLayerName = manifestCentroids[bestShape].layer;
        }} else if (bestShape >= 0 && planLayers.length > 0) {{
            // Distribute by shape index across available layers
            targetLayerName = planLayers[bestShape % planLayers.length];
        }}

        var targetLayer = getOrCreateLayer(targetLayerName);
        items[j].item.move(targetLayer, ElementPlacement.PLACEATEND);

        if (!layerCounts[targetLayerName]) layerCounts[targetLayerName] = 0;
        layerCounts[targetLayerName]++;
        assignments.push({{item: items[j].name, layer: targetLayerName}});
    }}

    // Collect all unique layer names created
    var createdLayers = [];
    for (var ln in layerCounts) {{
        createdLayers.push(ln);
    }}

    return JSON.stringify({{
        strategy: "manifest",
        layers_created: createdLayers,
        items_per_layer: layerCounts,
        total_items: items.length,
        assignments: assignments
    }});
}})();"""
