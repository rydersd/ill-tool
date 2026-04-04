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
var _SHARED = (function() {
    try {
        var thisFile = new File($.fileName);
        var jsxDir = thisFile.parent;
        var panelDir = jsxDir.parent;
        var cepDir = panelDir.parent;
        var sharedDir = new Folder(cepDir.fsName + "/shared");
        if (sharedDir.exists) return sharedDir.fsName + "/";
    } catch (e) { /* $.fileName empty or parent traversal failed */ }
    return "/Users/ryders/Developer/GitHub/ill_tool/cep/shared/";
})();
$.evalFile(_SHARED + "json_es3.jsx");
$.evalFile(_SHARED + "logging.jsx");
$.evalFile(_SHARED + "math2d.jsx");
$.evalFile(_SHARED + "geometry.jsx");
$.evalFile(_SHARED + "shapes.jsx");
$.evalFile(_SHARED + "pathutils.jsx");
$.evalFile(_SHARED + "ui.jsx");

// Module-level cache (persists across evalScript calls)
var _cachedSortedPoints = null;
var _cachedClassification = null;
var _cachedLOD = null;

/**
 * Get info about the current selection.
 * Returns pipe-delimited: "anchorCount|pathCount"
 */
function getSelectionInfo() {
    var counts = getSelectionCounts();
    return counts.anchorCount + "|" + counts.pathCount;
}

/**
 * Main entry point: read selected anchors, classify shape, place preview.
 *
 * Returns pipe-delimited: "shape|confidence|inputCount|outputCount"
 * On error: "error|message"
 */
function averageSelectedAnchors() {
    var anchors = getSelectedAnchors();
    if (anchors.length < 2) return "error|Need at least 2 selected anchors";

    var sorted = sortByPCA(anchors);
    _cachedSortedPoints = sorted;

    var classification = classifyShape(sorted);
    _cachedClassification = classification;

    // Precompute LOD levels for instant slider scrubbing
    _cachedLOD = precomputeLOD(sorted, 20);

    // Place preview path on "Cleaned Forms" layer (pass handles if available)
    var previewPath = placePreview(classification.points, classification.closed, "Cleaned Forms", classification.handles || null);

    // Select the preview so user can see anchor handles
    try {
        app.activeDocument.selection = null;
        previewPath.selected = true;
    } catch (e) {}

    // Compute and draw bounding box
    var rect = minAreaRect(anchors);
    drawBoundingBox(rect.center[0], rect.center[1], rect.width, rect.height, rect.angle, 5, "Cleaned Forms");

    // Return result as pipe-delimited string
    return classification.shape + "|" + classification.confidence + "|" + sorted.length + "|" + classification.points.length;
}

/**
 * Force reclassify cached points as a specific shape type.
 *
 * Returns pipe-delimited: "shape|confidence|outputCount"
 * On error: "error|message"
 */
function reclassifyAs(shapeType) {
    if (!_cachedSortedPoints) return "error|No cached data";

    var result = fitToShape(_cachedSortedPoints, shapeType);
    _cachedClassification = result;

    placePreview(result.points, result.closed, "Cleaned Forms", result.handles || null);

    logInteraction("shapeaverager", "reclassify",
        {shape: _cachedClassification ? _cachedClassification.shape : "unknown"},
        {shape: result.shape, confidence: result.confidence, pointCount: result.points.length},
        {inputAnchors: _cachedSortedPoints ? _cachedSortedPoints.length : 0});

    return result.shape + "|" + result.confidence + "|" + result.points.length;
}

/**
 * Apply a precomputed LOD level from the cache.
 * The slider value (0..100) maps to the nearest cached level.
 *
 * Returns the point count at that level as a string.
 * On error: "error|message"
 */
function applyLODLevel(level) {
    if (!_cachedLOD) return "error|No LOD cached";

    // Find the closest cached level at or below the requested value
    var best = _cachedLOD[0];
    for (var i = 0; i < _cachedLOD.length; i++) {
        if (_cachedLOD[i].value <= level) best = _cachedLOD[i];
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
function resmooth(tension) {
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
function doConfirm() {
    logInteraction("shapeaverager", "confirm",
        {shape: _cachedClassification ? _cachedClassification.shape : "unknown",
         confidence: _cachedClassification ? _cachedClassification.confidence : 0},
        null, null);
    var pathName = confirmPreview("Cleaned Forms");
    removeBoundingBox("Cleaned Forms");
    _cachedSortedPoints = null;
    _cachedClassification = null;
    _cachedLOD = null;

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
function doUndoAverage() {
    logInteraction("shapeaverager", "undo", null, null, null);
    undoPreview("Cleaned Forms");
    removeBoundingBox("Cleaned Forms");
    _cachedSortedPoints = null;
    _cachedClassification = null;
    _cachedLOD = null;
    return "undone";
}

/**
 * Clean up orphaned preview paths left from a previous session or crash.
 * Called on panel load. Returns the count of removed items as a string.
 */
function cleanupOrphans() {
    try {
        var lyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var toRemove = [];
        for (var i = 0; i < lyr.pathItems.length; i++) {
            var name = lyr.pathItems[i].name;
            if (name === "__preview__" || name === "__bbox_guide__") {
                toRemove.push(lyr.pathItems[i]);
            }
        }
        for (var j = toRemove.length - 1; j >= 0; j--) toRemove[j].remove();
        if (toRemove.length > 0) app.redraw();
        return toRemove.length + "";
    } catch (e) { return "0"; }
}

