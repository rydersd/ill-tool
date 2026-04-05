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
var _sa_savedLayerOpacity = []; // saved layer opacities for isolation mode

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
                try {
                    if (_sa_hiddenSourcePaths[h].item === sel[s]) { alreadyTracked = true; break; }
                } catch (e) {
                    // Stale reference — remove it
                    _sa_hiddenSourcePaths.splice(h, 1);
                    h--;
                }
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

    // Isolate: dim all other layers so the working content stands out
    sa_dimOtherLayers();

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
    // Restore layer opacity from isolation mode
    sa_restoreLayerOpacity();
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
    // Restore layer opacity from isolation mode
    sa_restoreLayerOpacity();
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

// ── Shape Auto-Detection ────────────────────────────────────────

/**
 * Analyze the current selection and guess the shape type.
 * Returns: "line"|"arc"|"lshape"|"rectangle"|"scurve"|"ellipse"|"freeform"|"none"
 */
function sa_guessShapeType() {
    var doc;
    try { doc = app.activeDocument; } catch(e) { return "none"; }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return "none";

    // Collect selected anchors
    var anchors = [];
    for (var i = 0; i < sel.length; i++) {
        if (sel[i].typename === "PathItem") {
            for (var j = 0; j < sel[i].pathPoints.length; j++) {
                var pp = sel[i].pathPoints[j];
                if (pp.selected !== PathPointSelection.NOSELECTION) {
                    anchors.push([pp.anchor[0], pp.anchor[1]]);
                }
            }
        }
    }

    if (anchors.length < 2) return "freeform";

    // Check collinear (line)
    if (_sa_isCollinear(anchors, 2.0)) return "line";

    // Check arc (all points curve in one direction)
    if (anchors.length <= 4 && _sa_isArc(anchors, 3.0)) return "arc";

    // Check L-shape (sharp angle change)
    if (anchors.length >= 3 && _sa_hasSharpCorner(anchors, 30)) return "lshape";

    // Check S-curve (changes curvature direction)
    if (anchors.length >= 3 && _sa_isSCurve(anchors)) return "scurve";

    // Check rectangle (4 corners, roughly right angles)
    if (anchors.length === 4 && _sa_isRectangular(anchors, 20)) return "rectangle";

    // Check ellipse (roughly equidistant from center)
    if (anchors.length >= 4 && _sa_isElliptical(anchors, 0.3)) return "ellipse";

    return "freeform";
}

/**
 * Test if all points are collinear within tolerance.
 * Max perpendicular distance from first-to-last line < tolerance.
 */
function _sa_isCollinear(points, tolerance) {
    if (points.length <= 2) return true;
    var a = points[0];
    var b = points[points.length - 1];
    for (var i = 1; i < points.length - 1; i++) {
        if (pointToSegmentDist(points[i], a, b) > tolerance) return false;
    }
    return true;
}

/**
 * Test if points form an arc (all curve in one direction).
 * Uses cross product sign consistency of consecutive segments.
 */
function _sa_isArc(points, tolerance) {
    if (points.length < 3) return true;
    // Check that all intermediate points are on the same side of the chord
    var a = points[0];
    var b = points[points.length - 1];
    var chord = sub2d(b, a);
    var sign = 0;
    for (var i = 1; i < points.length - 1; i++) {
        var v = sub2d(points[i], a);
        var c = cross2d(chord, v);
        if (Math.abs(c) < 0.01) continue; // on the chord
        if (sign === 0) {
            sign = (c > 0) ? 1 : -1;
        } else if ((c > 0 ? 1 : -1) !== sign) {
            return false; // points on different sides
        }
    }
    // Also check max deviation isn't too small (otherwise it's a line)
    var maxDev = 0;
    for (var j = 1; j < points.length - 1; j++) {
        var d = pointToSegmentDist(points[j], a, b);
        if (d > maxDev) maxDev = d;
    }
    return maxDev > tolerance * 0.5;
}

/**
 * Test if any consecutive triple has an angle sharper than angleDeg.
 */
function _sa_hasSharpCorner(points, angleDeg) {
    for (var i = 1; i < points.length - 1; i++) {
        var v1 = sub2d(points[i - 1], points[i]);
        var v2 = sub2d(points[i + 1], points[i]);
        var ang = angle2d(v1, v2);
        if (ang < angleDeg) return true;
    }
    return false;
}

/**
 * Test if curvature changes sign (S-curve).
 * Uses cross product of consecutive edge vectors.
 */
function _sa_isSCurve(points) {
    if (points.length < 4) return false;
    var signs = [];
    for (var i = 0; i < points.length - 2; i++) {
        var v1 = sub2d(points[i + 1], points[i]);
        var v2 = sub2d(points[i + 2], points[i + 1]);
        var c = cross2d(v1, v2);
        if (Math.abs(c) > 0.01) {
            signs.push(c > 0 ? 1 : -1);
        }
    }
    // S-curve has at least one sign change
    for (var j = 1; j < signs.length; j++) {
        if (signs[j] !== signs[j - 1]) return true;
    }
    return false;
}

/**
 * Test if 4 points form a rectangle (approximately right angles).
 */
function _sa_isRectangular(points, angleTolerance) {
    if (points.length !== 4) return false;
    for (var i = 0; i < 4; i++) {
        var prev = points[(i + 3) % 4];
        var curr = points[i];
        var next = points[(i + 1) % 4];
        var v1 = sub2d(prev, curr);
        var v2 = sub2d(next, curr);
        var ang = angle2d(v1, v2);
        if (Math.abs(ang - 90) > angleTolerance) return false;
    }
    return true;
}

/**
 * Test if points are roughly equidistant from their centroid (ellipse).
 * tolerance is the max allowed coefficient of variation (std/mean).
 */
function _sa_isElliptical(points, tolerance) {
    var c = centroid2d(points);
    var distances = [];
    for (var i = 0; i < points.length; i++) {
        distances.push(dist2d(points[i], c));
    }
    var m = mean(distances);
    if (m < 1e-6) return false;
    var variance = 0;
    for (var j = 0; j < distances.length; j++) {
        var diff = distances[j] - m;
        variance += diff * diff;
    }
    variance /= distances.length;
    var cv = Math.sqrt(variance) / m;
    return cv < tolerance;
}

// ── Isolation mode ──────────────────────────────────────────────

/**
 * Dim all layers except "Cleaned Forms" to isolate the working content.
 * Saves current opacity values for restoration.
 */
function sa_dimOtherLayers() {
    _sa_savedLayerOpacity = [];
    try {
        var doc = app.activeDocument;
        for (var i = 0; i < doc.layers.length; i++) {
            var lyr = doc.layers[i];
            _sa_savedLayerOpacity.push({ index: i, opacity: lyr.opacity });
            if (lyr.name !== "Cleaned Forms") {
                lyr.opacity = 30;
            }
        }
    } catch (e) {}
}

/**
 * Restore all layer opacities saved by sa_dimOtherLayers().
 */
function sa_restoreLayerOpacity() {
    try {
        var doc = app.activeDocument;
        for (var i = 0; i < _sa_savedLayerOpacity.length; i++) {
            var saved = _sa_savedLayerOpacity[i];
            if (saved.index < doc.layers.length) {
                doc.layers[saved.index].opacity = saved.opacity;
            }
        }
    } catch (e) {}
    _sa_savedLayerOpacity = [];
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
            var path = lyr.pathItems[pi];
            if (!path.name || path.name === "") {
                path.name = "__cluster_" + lyr.name.replace(/[^a-zA-Z0-9]/g, "_") + "_" + pi + "__";
            } else if (nameCount[path.name]) {
                path.name = path.name + "_" + nameCount[path.name];
            }
            nameCount[path.name] = (nameCount[path.name] || 0) + 1;

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

    // Only save original strokes on the first call (not on re-color after accept/reject)
    var isFirstColor = (_sa_origStrokes.length === 0);

    // Dim other layers on first cluster coloring to isolate working content
    if (isFirstColor) {
        sa_dimOtherLayers();
    }

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

    // Sort, classify, place preview — reusing shared library functions
    var sorted = sortByPCA(anchors);
    var classification = classifyShape(sorted);
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

    // Restore layer opacity from isolation mode
    sa_restoreLayerOpacity();
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
    // Restore layer opacity from isolation mode
    sa_restoreLayerOpacity();
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

