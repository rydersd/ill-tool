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
    // Primary: derive from this script's file path (works when loaded via ScriptPath)
    try {
        if ($.fileName && $.fileName.length > 0) {
            var thisFile = new File($.fileName);
            var jsxDir = thisFile.parent;
            var panelDir = jsxDir.parent;
            var cepDir = panelDir.parent;
            var sharedDir = new Folder(cepDir.fsName + "/shared");
            if (sharedDir.exists) return sharedDir.fsName + "/";
        }
    } catch (e) {}
    // Fallback: known CEP extensions directory, follow symlink to find shared/
    try {
        var home = $.getenv("HOME") || "~";
        var cepBase = home + "/Library/Application Support/Adobe/CEP/extensions";
        var panelName = "com.illtool.shapeaverager";
        var candidate = new Folder(cepBase + "/" + panelName);
        if (candidate.exists) {
            var resolved = candidate.resolve();  // follow symlink
            if (resolved) {
                var sharedDir2 = new Folder(new Folder(resolved.fsName).parent.fsName + "/shared");
                if (sharedDir2.exists) return sharedDir2.fsName + "/";
            }
        }
    } catch (e2) {}
    return "";
})();
// Guard against double-loading when multiple panels share the same ExtendScript engine
if (typeof jsonStringify === "undefined") $.evalFile(_SA_SHARED + "json_es3.jsx");
if (typeof logInteraction === "undefined") $.evalFile(_SA_SHARED + "logging.jsx");
if (typeof dist2d === "undefined") $.evalFile(_SA_SHARED + "math2d.jsx");
if (typeof sortByPCA === "undefined") $.evalFile(_SA_SHARED + "geometry.jsx");
if (typeof classifyShape === "undefined") $.evalFile(_SA_SHARED + "shapes.jsx");
if (typeof getSelectedAnchors === "undefined") $.evalFile(_SA_SHARED + "pathutils.jsx");
if (typeof ensureLayer === "undefined") $.evalFile(_SA_SHARED + "ui.jsx");

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
 * Derive a surface hint string from a detected shape type.
 * Maps shape classification results to surface type names that
 * can inform both classifyShape() confidence boosting and
 * precomputeLOD() primitive-aware simplification.
 *
 * @param {string} shapeType - detected shape: "line", "arc", "lshape", "rectangle", "scurve", "ellipse", "freeform"
 * @returns {string|null} surface hint: "flat", "cylindrical", "angular", "rectangular", "saddle", or null
 */
function _sa_deriveSurfaceHint(shapeType) {
    switch (shapeType) {
        case "line":
            return "flat";
        case "rectangle":
            return "rectangular";
        case "arc":
        case "ellipse":
            return "cylindrical";
        case "lshape":
            return "angular";
        case "scurve":
            return "saddle";
        default:
            return null;
    }
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
                sel[s].opacity = 30;  // dim but visible so user can Shift+click source anchors
            }
        }
    }

    var sorted = sortByPCA(anchors);
    _sa_cachedSortedPoints = sorted;

    // First pass: classify without surface hint to get shape type
    var classification = classifyShape(sorted);

    // Derive surface hint from detected shape type for surface-aware simplification
    var surfaceHint = _sa_deriveSurfaceHint(classification.shape);

    // Re-classify with surface hint if one was derived (boosts confidence)
    if (surfaceHint) {
        classification = classifyShape(sorted, surfaceHint);
    }
    _sa_cachedClassification = classification;

    // Precompute LOD levels for instant slider scrubbing (surface-aware)
    _sa_cachedLOD = precomputeLOD(sorted, 20, surfaceHint);

    // Create a working group with copies of selected objects + the preview
    var cleanLayer = ensureLayer("Cleaned Forms");
    var workGroup = cleanLayer.groupItems.add();
    workGroup.name = "__preview_group__";

    // Copy the dimmed source paths into the group (for reference during editing)
    for (var sc = 0; sc < _sa_hiddenSourcePaths.length; sc++) {
        try {
            var srcCopy = _sa_hiddenSourcePaths[sc].item.duplicate();
            srcCopy.opacity = 30;
            srcCopy.name = "__src_copy_" + sc + "__";
            srcCopy.move(workGroup, ElementPlacement.PLACEATEND);
        } catch (e) {}
    }

    // Place preview path inside the group
    var previewPath = placePreview(classification.points, classification.closed, "Cleaned Forms", classification.handles || null);
    try {
        previewPath.move(workGroup, ElementPlacement.PLACEATEND);
    } catch (e) {}

    // Isolate the group — user can only interact with contents
    try {
        doc.selection = null;
        workGroup.selected = true;
        app.executeMenuCommand("isolate");

        // Select the preview path for direct editing
        doc.selection = null;
        previewPath.selected = true;
    } catch (e) {}

    // Switch to Direct Selection tool for anchor handle editing
    try {
        app.executeMenuCommand("direct");
    } catch (e2) {}

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

    // Recompute LOD cache with the new shape's surface hint
    var hint = _sa_deriveSurfaceHint(shapeType);
    _sa_cachedLOD = precomputeLOD(_sa_cachedSortedPoints, 20, hint);

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

    // High-simplification levels may include primitive fit metadata
    var isClosed = best.closed || false;
    var handles = best.handles || null;

    placePreview(best.points, isClosed, "Cleaned Forms", handles);
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
function sa_doConfirm(targetLayerName) {
    // Use custom layer name if provided, otherwise default
    var layerName = (targetLayerName && targetLayerName.length > 0) ? targetLayerName : "Cleaned Forms";

    logInteraction("shapeaverager", "confirm",
        {shape: _sa_cachedClassification ? _sa_cachedClassification.shape : "unknown",
         confidence: _sa_cachedClassification ? _sa_cachedClassification.confidence : 0,
         layer: layerName},
        null, null);

    // Exit isolation mode first
    try {
        app.executeMenuCommand("exitisolation");
    } catch (e) {}

    // Move preview out of the working group to the target layer
    var targetLyr = ensureLayer(layerName);
    try {
        var cleanLyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var previewGroup = cleanLyr.groupItems.getByName("__preview_group__");
        // Find the preview path inside the group
        var preview = previewGroup.pathItems.getByName("__preview__");
        preview.move(targetLyr, ElementPlacement.PLACEATEND);
        // Delete the working group (contains source copies)
        previewGroup.remove();
    } catch (e) {
        // If group structure isn't there, fall through to normal confirm
    }

    var pathName = confirmPreview(layerName);
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
            doc.selection = null;
            var lyr = doc.layers.getByName(layerName);
            var confirmed = lyr.pathItems.getByName(pathName);
            confirmed.selected = true;
            app.executeMenuCommand("isolate");
        } catch (e) {}
        try {
            app.executeMenuCommand("Live Free Transform");
        } catch (e2) {}
    }

    return "confirmed|" + (pathName || "unknown");
}

/**
 * Undo the preview: remove preview path, clear caches.
 * Returns "undone"
 */
function sa_doUndoAverage() {
    logInteraction("shapeaverager", "undo", null, null, null);

    // Exit isolation mode
    try {
        app.executeMenuCommand("exitisolation");
    } catch (e) {}

    // Remove the working group (contains preview + source copies)
    try {
        var cleanLyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var previewGroup = cleanLyr.groupItems.getByName("__preview_group__");
        previewGroup.remove();
    } catch (e) {}

    // Also clean up any preview not in a group (fallback)
    undoPreview("Cleaned Forms");

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
    // Cap total points to prevent evalScript return overflow (~500KB JSON)
    var MAX_TOTAL_POINTS = 5000;
    var totalPts = 0;
    var capReached = false;

    for (var li = 0; li < doc.layers.length; li++) {
        if (capReached) break;
        var lyr = doc.layers[li];
        // If layer names specified, filter; otherwise include extraction layers
        if (names) {
            var found = false;
            for (var ni = 0; ni < names.length; ni++) {
                if (lyr.name === names[ni]) { found = true; break; }
            }
            if (!found) continue;
        } else {
            // Auto-detect extraction layers by exact name match
            var EXTRACTION_LAYERS = [
                "Scale Fine", "Scale Medium", "Scale Coarse",
                "Ink Lines", "Forms 5%", "Forms 10%",
                "Curvature", "Plane Boundaries", "contour_paths",
                "Form Edges", "Form Edge Heuristic", "Form Edge Informative", "Form Edge DSINE"
            ];
            var n = lyr.name;
            var isExtraction = false;
            for (var ei = 0; ei < EXTRACTION_LAYERS.length; ei++) {
                if (n === EXTRACTION_LAYERS[ei]) { isExtraction = true; break; }
            }
            if (!isExtraction) continue;
        }

        // Ensure unique path names before collecting
        var nameCount = {};
        for (var pi = 0; pi < lyr.pathItems.length; pi++) {
            if (capReached) break;
            var path = lyr.pathItems[pi];
            if (!path.name || path.name === "") {
                path.name = "__cluster_" + lyr.name.replace(/[^a-zA-Z0-9]/g, "_") + "_" + pi + "__";
            } else if (nameCount[path.name]) {
                path.name = path.name + "_" + nameCount[path.name];
            }
            nameCount[path.name] = (nameCount[path.name] || 0) + 1;

            // Check if adding this path would exceed the safety cap
            if (totalPts + path.pathPoints.length > MAX_TOTAL_POINTS) {
                capReached = true;
                break;
            }

            var pts = [];
            for (var pp = 0; pp < path.pathPoints.length; pp++) {
                pts.push([path.pathPoints[pp].anchor[0], path.pathPoints[pp].anchor[1]]);
            }
            totalPts += pts.length;
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

    // Only save original strokes on the first call (not on re-color after accept/reject)
    var isFirstColor = (_sa_origStrokes.length === 0);

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
                    // Save original stroke state only on first coloring pass
                    if (isFirstColor) {
                        _sa_origStrokes.push({
                            path: p,
                            color: p.strokeColor,
                            width: p.strokeWidth,
                            dashes: p.strokeDashes ? p.strokeDashes.slice(0) : []
                        });
                    }
                    p.strokeColor = clr;
                    p.strokeWidth = cluster.stroke_width || 1;
                    p.strokeDashes = [];
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
 * Accept a single cluster: collect anchors, classify, place preview, delete sources.
 * Dedicated batch function — does NOT enter isolation mode or call sa_averageSelectedAnchors.
 * Returns "accepted|shape|confidence" or "error|message"
 */
function sa_acceptCluster(clusterIndex) {
    if (!_sa_clusters || clusterIndex < 0 || clusterIndex >= _sa_clusters.length) return "error|Invalid cluster";

    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    var cluster = _sa_clusters[clusterIndex];
    var names = cluster.path_names;

    // Collect all anchors from cluster paths
    var anchors = [];
    var sourcePaths = [];
    for (var ni = 0; ni < names.length; ni++) {
        for (var li = 0; li < doc.layers.length; li++) {
            try {
                var p = doc.layers[li].pathItems.getByName(names[ni]);
                for (var pp = 0; pp < p.pathPoints.length; pp++) {
                    anchors.push([p.pathPoints[pp].anchor[0], p.pathPoints[pp].anchor[1]]);
                }
                sourcePaths.push(p);
                break;
            } catch(e) {}
        }
    }

    if (anchors.length < 2) return "error|Need at least 2 anchors";

    // Sort, classify with surface hint, place preview — reusing shared library functions
    var sorted = sortByPCA(anchors);
    var classification = classifyShape(sorted);
    var surfaceHint = _sa_deriveSurfaceHint(classification.shape);
    if (surfaceHint) {
        classification = classifyShape(sorted, surfaceHint);
    }
    var previewPath = placePreview(classification.points, classification.closed, "Cleaned Forms", classification.handles || null);

    // Rename from __preview__ to a permanent name
    try {
        previewPath.name = "clustered_" + new Date().getTime() + "_" + clusterIndex;
    } catch(e) {}

    // Delete source paths
    for (var si = sourcePaths.length - 1; si >= 0; si--) {
        try { sourcePaths[si].remove(); } catch(e) {}
    }

    // Clean up origStrokes for deleted paths
    if (_sa_origStrokes) {
        for (var oi = _sa_origStrokes.length - 1; oi >= 0; oi--) {
            var found = false;
            for (var sp = 0; sp < sourcePaths.length; sp++) {
                if (_sa_origStrokes[oi].path === sourcePaths[sp]) { found = true; break; }
            }
            if (found) _sa_origStrokes.splice(oi, 1);
        }
    }

    // Splice this cluster from the ExtendScript-side array to stay in sync
    // with the JS-side clusterData.splice() that happens in the callback.
    _sa_clusters.splice(clusterIndex, 1);

    logInteraction("shapeaverager", "cluster_accept",
        {cluster_id: clusterIndex, identity_key: cluster.identity_key || "", member_count: names.length},
        null, null);

    app.redraw();
    return "accepted|" + classification.shape + "|" + classification.confidence;
}

/**
 * Accept ALL clusters: batch process each cluster in sequence.
 * Does NOT enter isolation mode — sa_acceptCluster handles placement directly.
 * Returns "accepted_all|count" or "error|message"
 */
function sa_acceptAllClusters() {
    if (!_sa_clusters) return "error|No clusters";

    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    var accepted = 0;
    // Process in reverse so indices don't shift as clusters are consumed
    for (var ci = _sa_clusters.length - 1; ci >= 0; ci--) {
        doc.selection = null;  // clear between iterations
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
    if (!_sa_clusters || clusterIndex < 0 || clusterIndex >= _sa_clusters.length) return "error|Invalid cluster";

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

/**
 * Approximate bezier arc length between two Illustrator PathPoints.
 * Uses the average of chord length and control polygon length,
 * which is more accurate than straight chord distance for curves.
 *
 * @param {PathPoint} pp1 - first path point
 * @param {PathPoint} pp2 - second path point
 * @returns {number} approximate arc length
 */
function _approxSegmentLength(pp1, pp2) {
    var p0 = pp1.anchor;
    var p1 = pp1.rightDirection;
    var p2 = pp2.leftDirection;
    var p3 = pp2.anchor;
    // Chord length
    var chord = dist2d(p0, p3);
    // Control polygon length
    var poly = dist2d(p0, p1) + dist2d(p1, p2) + dist2d(p2, p3);
    // Approximate arc length is average of chord and control polygon
    return (chord + poly) / 2;
}

/**
 * Select all small/noisy paths on visible, unlocked layers.
 *
 * Selects paths with fewer than maxPoints anchor points,
 * or (if maxArcLength > 0) total arc length shorter than the threshold.
 * Skips internal paths (__preview__, __bbox_*, __cluster_*).
 *
 * @param {number} maxPoints - max anchor count to qualify as "small" (default 3)
 * @param {number} maxArcLength - max arc length in points; 0 = skip length check
 * Returns the count of selected paths as a string, or "error|message"
 */
function sa_selectSmallPaths(maxPoints, maxArcLength) {
    var doc;
    try { doc = app.activeDocument; } catch(e) { return "error|No document"; }

    if (!maxPoints || maxPoints < 1) maxPoints = 3;
    if (!maxArcLength) maxArcLength = 0;

    // Deselect everything first
    doc.selection = null;

    var selected = 0;

    for (var li = 0; li < doc.layers.length; li++) {
        var lyr = doc.layers[li];
        // Skip hidden or locked layers
        if (!lyr.visible || lyr.locked) continue;

        for (var pi = 0; pi < lyr.pathItems.length; pi++) {
            var path = lyr.pathItems[pi];

            // Skip internal/preview paths
            var name = path.name || "";
            if (name === "__preview__" ||
                name.indexOf("__bbox_") === 0 ||
                name.indexOf("__cluster_") === 0) continue;

            // Skip hidden or locked paths
            if (path.hidden || path.locked) continue;

            var pointCount = path.pathPoints.length;
            var isSmall = false;

            // Check point count threshold
            if (pointCount < maxPoints) {
                isSmall = true;
            }

            // Check arc length threshold if specified
            // Uses bezier arc approximation: average of chord and control polygon lengths
            if (!isSmall && maxArcLength > 0 && pointCount >= 2) {
                var totalLength = 0;
                for (var pp = 1; pp < path.pathPoints.length; pp++) {
                    totalLength += _approxSegmentLength(path.pathPoints[pp - 1], path.pathPoints[pp]);
                }
                // Close the loop if path is closed
                if (path.closed && path.pathPoints.length > 2) {
                    totalLength += _approxSegmentLength(
                        path.pathPoints[path.pathPoints.length - 1],
                        path.pathPoints[0]
                    );
                }
                if (totalLength < maxArcLength) {
                    isSmall = true;
                }
            }

            if (isSmall) {
                path.selected = true;
                selected++;
            }
        }
    }

    app.redraw();
    return selected + "";
}

