/**
 * Shape Cleanup — ExtendScript host functions for Illustrator.
 *
 * Thin file that #includes shared libraries and adds panel-specific
 * workflow functions. All math runs locally in ExtendScript — no
 * WebSocket dependency.
 *
 * Called from the CEP panel via CSInterface.evalScript().
 */

// Include shared libraries
// Derive shared library path from this script's location
var _SA_SHARED = (function() {
    try {
        var thisFile = new File($.fileName);
        var jsxDir = thisFile.parent;
        var panelDir = jsxDir.parent;
        var cepDir = panelDir.parent;
        var sharedDir = new Folder(cepDir.fsName + "/shared");
        if (sharedDir.exists) return sharedDir.fsName + "/";
    } catch (e) { /* $.fileName empty or parent traversal failed */ }
    // Fallback: try relative from known CEP install location
    try {
        var f = new File($.fileName);
        return f.parent.parent.parent.fsName + "/shared/";
    } catch(e2) {}
    return "";
})();
$.evalFile(_SA_SHARED + "json_es3.jsx");
$.evalFile(_SA_SHARED + "logging.jsx");
$.evalFile(_SA_SHARED + "math2d.jsx");
$.evalFile(_SA_SHARED + "geometry.jsx");
$.evalFile(_SA_SHARED + "shapes.jsx");
$.evalFile(_SA_SHARED + "pathutils.jsx");
$.evalFile(_SA_SHARED + "ui.jsx");

// Module-level cache (persists across evalScript calls)
var _sa_cachedSortedPoints = null;
var _sa_cachedClassification = null;
var _sa_cachedLOD = null;

/**
 * Get info about the current selection.
 * Returns pipe-delimited: "anchorCount|pathCount"
 */
function sa_getSelectionInfo() {
    var counts = getSelectionCounts();
    return counts.anchorCount + "|" + counts.pathCount;
}

/**
 * Main entry point: read selected anchors, classify shape, place preview.
 *
 * Returns pipe-delimited: "shape|confidence|inputCount|outputCount"
 * On error: "error|message"
 */
// Track hidden source paths so we can restore on cancel
var _sa_hiddenSourcePaths = [];

function sa_averageSelectedAnchors() {
    var doc = app.activeDocument;
    var anchors = getSelectedAnchors();
    if (anchors.length < 2) return "error|Need at least 2 selected anchors";

    // Hide the original selected paths so they don't interfere visually
    // Don't reset — append new items, checking for duplicates
    var sel = doc.selection;
    for (var s = 0; s < sel.length; s++) {
        if (sel[s].typename === "PathItem" && sel[s].opacity > 0) {
            // Check if already tracked
            var alreadyTracked = false;
            for (var h = 0; h < _sa_hiddenSourcePaths.length; h++) {
                if (_sa_hiddenSourcePaths[h].item === sel[s]) { alreadyTracked = true; break; }
            }
            if (!alreadyTracked) {
                _sa_hiddenSourcePaths.push({ item: sel[s], prevOpacity: sel[s].opacity });
                sel[s].opacity = 0;
            }
        }
    }

    var sorted = sortByPCA(anchors);
    _sa_cachedSortedPoints = sorted;

    var classification = classifyShape(sorted);
    _sa_cachedClassification = classification;

    // Precompute LOD levels for instant slider scrubbing
    _sa_cachedLOD = precomputeLOD(sorted, 20);

    // Place preview path on "Cleaned Forms" layer (pass handles if available)
    var previewPath = placePreview(classification.points, classification.closed, "Cleaned Forms", classification.handles || null);

    // Compute and draw bounding box with 2x anchor points in blue
    var rect = minAreaRect(anchors);
    drawBoundingBox(rect.center[0], rect.center[1], rect.width, rect.height, rect.angle, 5, "Cleaned Forms");

    // Select the preview so user can see/edit its anchor handles
    // (user can delete stray points with Delete Anchor Point tool)
    try {
        doc.selection = null;
        previewPath.selected = true;
    } catch (e) {}

    // Return result as pipe-delimited string
    return classification.shape + "|" + classification.confidence + "|" + sorted.length + "|" + classification.points.length;
}

/**
 * Restore hidden source paths (called on cancel/undo).
 */
function _sa_restoreHiddenPaths() {
    for (var i = 0; i < _sa_hiddenSourcePaths.length; i++) {
        try {
            _sa_hiddenSourcePaths[i].item.opacity = _sa_hiddenSourcePaths[i].prevOpacity;
        } catch (e) {}
    }
    _sa_hiddenSourcePaths = [];
}

/**
 * Force reclassify cached points as a specific shape type.
 *
 * Returns pipe-delimited: "shape|confidence|outputCount"
 * On error: "error|message"
 */
function sa_reclassifyAs(shapeType) {
    if (!_sa_cachedSortedPoints) return "error|No cached data";

    var result = fitToShape(_sa_cachedSortedPoints, shapeType);
    _sa_cachedClassification = result;

    placePreview(result.points, result.closed, "Cleaned Forms", result.handles || null);

    logInteraction("shapeaverager", "reclassify",
        {shape: _sa_cachedClassification ? _sa_cachedClassification.shape : "unknown"},
        {shape: result.shape, confidence: result.confidence, pointCount: result.points.length},
        {inputAnchors: _sa_cachedSortedPoints ? _sa_cachedSortedPoints.length : 0});

    return result.shape + "|" + result.confidence + "|" + result.points.length;
}

/**
 * Apply a precomputed LOD level from the cache.
 * The slider value (0..100) maps to the nearest cached level.
 *
 * Returns the point count at that level as a string.
 * On error: "error|message"
 */
function sa_applyLODLevel(level) {
    if (!_sa_cachedLOD) return "error|No LOD cached";

    // Find the closest cached level at or below the requested value
    var best = _sa_cachedLOD[0];
    for (var i = 0; i < _sa_cachedLOD.length; i++) {
        if (_sa_cachedLOD[i].value <= level) best = _sa_cachedLOD[i];
    }

    placePreview(best.points, false, "Cleaned Forms");
    return best.count + "";
}

/**
 * Recompute smooth handles on the current preview path.
 *
 * @param {number} tension - handle length factor (default 1/6)
 * Returns "ok" or "error|message"
 */
function sa_resmooth(tension) {
    try {
        var lyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var preview = lyr.pathItems.getByName("__preview__");
        computeSmoothHandles(preview, tension || (1 / 6));
        app.redraw();
        return "ok";
    } catch (e) {
        return "error|" + e.message;
    }
}

/**
 * Confirm the preview: solidify stroke, clear caches, enter isolation mode.
 * Returns "confirmed|<pathName>" or "confirmed|unknown"
 */
function sa_doConfirm() {
    logInteraction("shapeaverager", "confirm",
        {shape: _sa_cachedClassification ? _sa_cachedClassification.shape : "unknown",
         confidence: _sa_cachedClassification ? _sa_cachedClassification.confidence : 0},
        null, null);
    var pathName = confirmPreview("Cleaned Forms");
    removeBoundingBox("Cleaned Forms");
    // Delete hidden source paths — they've been replaced by the confirmed preview
    for (var hp = _sa_hiddenSourcePaths.length - 1; hp >= 0; hp--) {
        try { _sa_hiddenSourcePaths[hp].item.remove(); } catch(e3) {}
    }
    _sa_hiddenSourcePaths = [];

    _sa_cachedSortedPoints = null;
    _sa_cachedClassification = null;
    _sa_cachedLOD = null;

    // Enter isolation mode on the confirmed path and activate Free Transform
    if (pathName) {
        try {
            var doc = app.activeDocument;
            doc.selection = null;  // deselect all
            var lyr = doc.layers.getByName("Cleaned Forms");
            var confirmed = lyr.pathItems.getByName(pathName);
            confirmed.selected = true;
            app.executeMenuCommand("isolate");
        } catch (e) {
            // isolation mode not available or path not found — non-fatal
        }
        try {
            app.executeMenuCommand("Live Free Transform");
        } catch (e2) {
            // Free Transform may not be available in all versions — non-fatal
        }
    }

    return "confirmed|" + (pathName || "unknown");
}

/**
 * Undo the preview: remove preview path, clear caches.
 * Returns "undone"
 */
function sa_doUndoAverage() {
    logInteraction("shapeaverager", "undo", null, null, null);
    undoPreview("Cleaned Forms");
    removeBoundingBox("Cleaned Forms");
    _sa_restoreHiddenPaths();
    _sa_cachedSortedPoints = null;
    _sa_cachedClassification = null;
    _sa_cachedLOD = null;
    return "undone";
}

/**
 * Clean up orphaned preview paths left from a previous session or crash.
 * Called on panel load. Returns the count of removed items as a string.
 */
function sa_cleanupOrphans() {
    try {
        var lyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var toRemove = [];
        for (var i = 0; i < lyr.pathItems.length; i++) {
            var name = lyr.pathItems[i].name;
            if (name === "__preview__" || name === "__bbox_guide__" || name.indexOf("__bbox_handle_") === 0) {
                toRemove.push(lyr.pathItems[i]);
            }
        }
        for (var j = toRemove.length - 1; j >= 0; j--) toRemove[j].remove();
        if (toRemove.length > 0) app.redraw();
        return toRemove.length + "";
    } catch (e) { return "0"; }
}

// ── Clustering State ─────────────────────────────────────────────
var _sa_clusters = null;       // array of cluster objects from MCP
var _sa_clusterPaths = [];     // references to colored paths on artboard
var _sa_clusterMode = false;   // whether clustering mode is active
// Saved original stroke state for paths colored by clustering
var _sa_origStrokes = [];      // [{path, color, width, dashes}]

/**
 * Read all paths from specified extraction layers.
 * Returns JSON array of {name, layer, points: [[x,y],...]}
 * for the MCP clustering tool.
 */
function sa_readLayerPaths(layerNames) {
    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    var allPaths = [];
    var names = layerNames ? layerNames.split(",") : null;

    for (var li = 0; li < doc.layers.length; li++) {
        var lyr = doc.layers[li];
        // If layer names specified, filter; otherwise include extraction layers
        if (names) {
            var found = false;
            for (var ni = 0; ni < names.length; ni++) {
                if (lyr.name === names[ni]) { found = true; break; }
            }
            if (!found) continue;
        } else {
            // Auto-detect extraction layers by common prefixes
            var n = lyr.name;
            if (n.indexOf("Scale") !== 0 && n.indexOf("Ink") !== 0 &&
                n.indexOf("Form") !== 0 && n.indexOf("Curvature") !== 0 &&
                n.indexOf("Plane") !== 0 && n !== "contour_paths") continue;
        }

        for (var pi = 0; pi < lyr.pathItems.length; pi++) {
            var path = lyr.pathItems[pi];
            var pts = [];
            for (var pp = 0; pp < path.pathPoints.length; pp++) {
                pts.push([path.pathPoints[pp].anchor[0], path.pathPoints[pp].anchor[1]]);
            }
            allPaths.push({
                name: path.name,
                layer: lyr.name,
                points: pts
            });
        }
    }

    return jsonStringify(allPaths);
}

/**
 * Color-code paths by cluster assignment.
 * Takes JSON: [{cluster_id, identity_key, path_names: [...], color: [r,g,b],
 *               stroke_width, dashed, confidence_tier, member_count}]
 * Saves original stroke state for restore on exit.
 * Returns "colored|count" or "error|message"
 */
function sa_colorClusters(clusterJson) {
    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    var clusters;
    try { clusters = jsonParse(clusterJson); } catch(e) { return "error|Invalid JSON"; }
    if (!clusters) return "error|Parse failed";

    _sa_clusterMode = true;
    _sa_clusters = clusters;
    _sa_origStrokes = [];

    var colored = 0;
    for (var ci = 0; ci < clusters.length; ci++) {
        var cluster = clusters[ci];
        var clr = new RGBColor();
        clr.red = cluster.color[0];
        clr.green = cluster.color[1];
        clr.blue = cluster.color[2];

        var pathNames = cluster.path_names;
        for (var ni = 0; ni < pathNames.length; ni++) {
            // Search all layers for the path by name
            for (var li = 0; li < doc.layers.length; li++) {
                try {
                    var p = doc.layers[li].pathItems.getByName(pathNames[ni]);
                    // Save original stroke state before modifying
                    _sa_origStrokes.push({
                        path: p,
                        color: p.strokeColor,
                        width: p.strokeWidth,
                        dashes: p.strokeDashes ? p.strokeDashes.slice(0) : []
                    });
                    p.strokeColor = clr;
                    p.strokeWidth = cluster.stroke_width || 1;
                    if (cluster.dashed) {
                        p.strokeDashes = [4, 4];
                    }
                    colored++;
                    break;  // found it, stop searching layers
                } catch(e) {
                    // not on this layer, try next
                }
            }
        }
    }

    app.redraw();
    return "colored|" + colored;
}

/**
 * Accept a single cluster: average all paths in that cluster.
 * Returns "accepted|shape|confidence|inputCount|outputCount" or "error|message"
 */
function sa_acceptCluster(clusterIndex) {
    if (!_sa_clusters || clusterIndex >= _sa_clusters.length) return "error|Invalid cluster";

    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    var cluster = _sa_clusters[clusterIndex];
    var pathNames = cluster.path_names;

    // Select all paths in this cluster
    doc.selection = null;
    var selected = [];
    for (var ni = 0; ni < pathNames.length; ni++) {
        for (var li = 0; li < doc.layers.length; li++) {
            try {
                var p = doc.layers[li].pathItems.getByName(pathNames[ni]);
                p.selected = true;
                selected.push(p);
                break;
            } catch(e) {}
        }
    }

    if (selected.length < 2) return "error|Need at least 2 paths";

    // Use existing averaging pipeline
    var result = sa_averageSelectedAnchors();
    if (result.indexOf("error") === 0) return result;

    // Auto-confirm the average
    var confirmResult = sa_doConfirm();

    logInteraction("shapeaverager", "cluster_accept",
        {cluster_id: clusterIndex, identity_key: cluster.identity_key || "", member_count: pathNames.length},
        null, null);

    return "accepted|" + result;
}

/**
 * Accept ALL clusters: batch average each cluster in sequence.
 * Returns "accepted_all|count" or "error|message"
 */
function sa_acceptAllClusters() {
    if (!_sa_clusters) return "error|No clusters";

    var accepted = 0;
    // Process in reverse so layer indices don't shift
    for (var ci = _sa_clusters.length - 1; ci >= 0; ci--) {
        var result = sa_acceptCluster(ci);
        if (result.indexOf("accepted") === 0) accepted++;
    }

    logInteraction("shapeaverager", "cluster_accept_all",
        {total_clusters: _sa_clusters.length, accepted: accepted},
        null, null);

    _sa_clusters = null;
    _sa_clusterMode = false;
    _sa_origStrokes = [];
    return "accepted_all|" + accepted;
}

/**
 * Reject a cluster: remove all paths in that cluster.
 * Returns "rejected|count" or "error|message"
 */
function sa_rejectCluster(clusterIndex) {
    if (!_sa_clusters || clusterIndex >= _sa_clusters.length) return "error|Invalid cluster";

    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    var cluster = _sa_clusters[clusterIndex];
    var pathNames = cluster.path_names;
    var removed = 0;

    for (var ni = 0; ni < pathNames.length; ni++) {
        for (var li = 0; li < doc.layers.length; li++) {
            try {
                var p = doc.layers[li].pathItems.getByName(pathNames[ni]);
                // Remove from origStrokes tracking too
                for (var oi = _sa_origStrokes.length - 1; oi >= 0; oi--) {
                    if (_sa_origStrokes[oi].path === p) {
                        _sa_origStrokes.splice(oi, 1);
                        break;
                    }
                }
                p.remove();
                removed++;
                break;
            } catch(e) {}
        }
    }

    // Remove this cluster from the array
    _sa_clusters.splice(clusterIndex, 1);

    logInteraction("shapeaverager", "cluster_reject",
        {cluster_id: clusterIndex, removed: removed},
        null, null);

    app.redraw();
    return "rejected|" + removed;
}

/**
 * Exit clustering mode: restore original strokes, clear state.
 * Returns "exited"
 */
function sa_exitClusterMode() {
    // Restore original stroke colors/widths
    for (var i = 0; i < _sa_origStrokes.length; i++) {
        try {
            var entry = _sa_origStrokes[i];
            entry.path.strokeColor = entry.color;
            entry.path.strokeWidth = entry.width;
            entry.path.strokeDashes = entry.dashes;
        } catch(e) {}
    }
    _sa_origStrokes = [];
    _sa_clusters = null;
    _sa_clusterMode = false;
    app.redraw();
    return "exited";
}

