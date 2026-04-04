/**
 * Shape Averager — ExtendScript host functions for Illustrator.
 *
 * Thin file that #includes shared libraries and adds panel-specific
 * workflow functions. All math runs locally in ExtendScript — no
 * WebSocket dependency.
 *
 * Called from the CEP panel via CSInterface.evalScript().
 */

// Include shared libraries
// The panel is symlinked from the repo — use the known repo path directly.
// This is reliable across CEP panel loading, evalScript, and symlink resolution.
var _SHARED = "/Users/ryders/Developer/GitHub/ill_tool/cep/shared/";
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

    // Place preview path on "Cleaned Forms" layer
    placePreview(classification.points, classification.closed, "Cleaned Forms");

    // Compute and draw bounding box
    var rect = minAreaRect(anchors);
    drawBoundingBox(rect.center[0], rect.center[1], rect.width, rect.height, rect.angle, 5);

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

    placePreview(result.points, result.closed, "Cleaned Forms");

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
 * Confirm the preview: solidify stroke, clear caches.
 * Returns "confirmed"
 */
function doConfirm() {
    confirmPreview("Cleaned Forms");
    removeBoundingBox();
    _cachedSortedPoints = null;
    _cachedClassification = null;
    _cachedLOD = null;
    return "confirmed";
}

/**
 * Undo the preview: remove preview path, clear caches.
 * Returns "undone"
 */
function doUndo() {
    undoPreview("Cleaned Forms");
    removeBoundingBox();
    _cachedSortedPoints = null;
    _cachedClassification = null;
    _cachedLOD = null;
    return "undone";
}
