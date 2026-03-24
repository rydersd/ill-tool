"""Auto-group paths by spatial proximity and name groups by body region.

Uses a simple clustering algorithm: iterate all pathItem centers on a layer,
merge any two items within the proximity threshold into the same cluster,
then create Illustrator groups from each cluster. Groups are named from
the shape manifest (if provided) or by spatial region (top/center/bottom).
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiGroupAndNameInput


def register(mcp):
    """Register the adobe_ai_group_and_name tool."""

    @mcp.tool(
        name="adobe_ai_group_and_name",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_group_and_name(params: AiGroupAndNameInput) -> str:
        """Group pathItems by spatial proximity and name each group by region
        or shape manifest data.

        Clustering: paths whose centers are within proximity_threshold of any
        other path in the same cluster are grouped together (union-find).
        Naming: if a shape_manifest is provided, groups are named using the
        shape type and index from the closest manifest entry; otherwise
        groups are named by vertical region (top-group, center-group,
        bottom-group).
        """
        escaped_source = escape_jsx_string(params.source_layer)
        threshold = params.proximity_threshold

        # Prepare manifest data if provided
        manifest_js = "null"
        if params.shape_manifest:
            try:
                manifest_data = json.loads(params.shape_manifest)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid shape_manifest JSON: {e}"})
            manifest_js = json.dumps(manifest_data)

        jsx = f"""(function() {{
    var doc = app.activeDocument;

    // Find source layer
    var srcLayer = null;
    try {{ srcLayer = doc.layers.getByName("{escaped_source}"); }} catch(e) {{}}
    if (!srcLayer) return JSON.stringify({{error: "Source layer not found: {escaped_source}"}});

    // Collect all pathItems with their centers
    var items = [];
    for (var i = 0; i < srcLayer.pathItems.length; i++) {{
        var p = srcLayer.pathItems[i];
        var gb = p.geometricBounds; // [left, top, right, bottom]
        var cx = (gb[0] + gb[2]) / 2;
        var cy = (gb[1] + gb[3]) / 2;
        items.push({{
            idx: i,
            cx: cx,
            cy: cy,
            name: p.name || ("path_" + i),
            cluster: i  // union-find: each starts as its own cluster
        }});
    }}

    if (items.length === 0) return JSON.stringify({{error: "No pathItems on source layer."}});

    // --- Union-Find clustering by proximity ---
    var threshold = {threshold};

    // Find root of a cluster
    function findRoot(idx) {{
        while (items[idx].cluster !== idx) {{
            items[idx].cluster = items[items[idx].cluster].cluster; // path compression
            idx = items[idx].cluster;
        }}
        return idx;
    }}

    // Union two items
    function unite(a, b) {{
        var ra = findRoot(a);
        var rb = findRoot(b);
        if (ra !== rb) items[rb].cluster = ra;
    }}

    // Cluster items within threshold distance
    for (var a = 0; a < items.length; a++) {{
        for (var b = a + 1; b < items.length; b++) {{
            var dx = items[a].cx - items[b].cx;
            var dy = items[a].cy - items[b].cy;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist <= threshold) {{
                unite(a, b);
            }}
        }}
    }}

    // Collect clusters: map root -> list of indices
    var clusters = {{}};
    for (var c = 0; c < items.length; c++) {{
        var root = findRoot(c);
        if (!clusters[root]) clusters[root] = [];
        clusters[root].push(c);
    }}

    // Convert to array and sort by average Y (top-first in AI coords = highest Y first)
    var clusterList = [];
    for (var key in clusters) {{
        var indices = clusters[key];
        var sumY = 0;
        var sumX = 0;
        for (var d = 0; d < indices.length; d++) {{
            sumY += items[indices[d]].cy;
            sumX += items[indices[d]].cx;
        }}
        clusterList.push({{
            indices: indices,
            avgX: sumX / indices.length,
            avgY: sumY / indices.length,
            count: indices.length
        }});
    }}
    // Sort by avgY descending (top of artboard = highest Y in AI)
    clusterList.sort(function(a, b) {{ return b.avgY - a.avgY; }});

    // --- Determine names from manifest or spatial position ---
    var manifest = {manifest_js};
    var artboardRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abTop = artboardRect[1];
    var abBottom = artboardRect[3];
    var abHeight = abTop - abBottom;

    function getRegionName(avgY, clusterIdx) {{
        // Divide artboard into thirds for naming
        var pos = (abTop - avgY) / abHeight; // 0=top, 1=bottom
        if (pos < 0.33) return "top-group";
        if (pos < 0.66) return "center-group";
        return "bottom-group";
    }}

    function getManifestName(avgX, avgY, clusterIdx) {{
        if (!manifest || !manifest.shapes || manifest.shapes.length === 0) {{
            return getRegionName(avgY, clusterIdx);
        }}
        // Find closest manifest shape by centroid distance
        var bestDist = Infinity;
        var bestShape = null;
        for (var s = 0; s < manifest.shapes.length; s++) {{
            var shape = manifest.shapes[s];
            if (!shape.center) continue;
            var sdx = avgX - shape.center[0];
            var sdy = avgY - shape.center[1];
            var sDist = Math.sqrt(sdx * sdx + sdy * sdy);
            if (sDist < bestDist) {{
                bestDist = sDist;
                bestShape = shape;
            }}
        }}
        if (bestShape) {{
            var shapeName = bestShape.shape_type || bestShape.type || "shape";
            var shapeIdx = bestShape.index !== undefined ? bestShape.index : clusterIdx;
            return shapeName + "_" + shapeIdx;
        }}
        return getRegionName(avgY, clusterIdx);
    }}

    // --- Create groups and move items ---
    // We need to collect pathItem references before moving them (indices shift during moves)
    var pathRefs = [];
    for (var r = 0; r < srcLayer.pathItems.length; r++) {{
        pathRefs.push(srcLayer.pathItems[r]);
    }}

    var results = [];
    var usedNames = {{}};

    for (var g = 0; g < clusterList.length; g++) {{
        var cl = clusterList[g];

        // Skip single-item "clusters" — no need to group a single path
        // (still name it though)
        if (cl.count === 1) {{
            var singleName = manifest ? getManifestName(cl.avgX, cl.avgY, g) : getRegionName(cl.avgY, g);
            // Deduplicate name
            if (usedNames[singleName]) {{
                usedNames[singleName]++;
                singleName = singleName + "_" + usedNames[singleName];
            }} else {{
                usedNames[singleName] = 1;
            }}
            var singleItem = pathRefs[cl.indices[0]];
            singleItem.name = singleName;
            results.push({{name: singleName, item_count: 1}});
            continue;
        }}

        // Determine group name
        var groupName = manifest ? getManifestName(cl.avgX, cl.avgY, g) : getRegionName(cl.avgY, g);
        if (usedNames[groupName]) {{
            usedNames[groupName]++;
            groupName = groupName + "_" + usedNames[groupName];
        }} else {{
            usedNames[groupName] = 1;
        }}

        // Create a new group on the source layer
        var grp = srcLayer.groupItems.add();
        grp.name = groupName;

        // Move items into the group (iterate in reverse to avoid index shifting)
        var clIndices = cl.indices.slice().sort(function(x, y) {{ return y - x; }});
        for (var h = 0; h < clIndices.length; h++) {{
            var pathItem = pathRefs[clIndices[h]];
            pathItem.move(grp, ElementPlacement.PLACEATEND);
        }}

        results.push({{name: groupName, item_count: cl.count}});
    }}

    // Build group name list
    var groupNames = [];
    for (var q = 0; q < results.length; q++) {{
        groupNames.push(results[q].name);
    }}

    return JSON.stringify({{
        groups_created: results.length,
        total_items: items.length,
        proximity_threshold: threshold,
        groups: results,
        group_names: groupNames
    }});
}})();"""

        result = await _async_run_jsx("illustrator", jsx)
        if not result["success"]:
            return json.dumps({"error": result["stderr"]})

        return result["stdout"]
