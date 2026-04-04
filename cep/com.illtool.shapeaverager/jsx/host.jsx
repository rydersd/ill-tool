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
var _bboxOriginalPoints = null;

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
    placePreview(classification.points, classification.closed, "Cleaned Forms", classification.handles || null);

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
    // Re-snapshot originals so bbox transform matches new point count
    storeBboxOriginals();

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
    // Re-snapshot originals so bbox transform matches new point count
    storeBboxOriginals();
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

    // Enter isolation mode on the confirmed path
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
    _bboxOriginalPoints = null;
    return "undone";
}

/**
 * Return bounding box data for the cached sorted points.
 * Returns pipe-delimited: "cx|cy|width|height|angle"
 * On error: "error|message"
 */
function getBboxData() {
    if (!_cachedSortedPoints) return "error|No data";
    var rect = minAreaRect(_cachedSortedPoints);
    return rect.center[0] + "|" + rect.center[1] + "|" + rect.width + "|" + rect.height + "|" + rect.angle;
}

/**
 * Store original point positions for the preview path.
 * Must be called once before any applyBboxTransform calls (at bbox drag start).
 * Returns "ok|pointCount" or "error|message"
 */
function storeBboxOriginals() {
    try {
        var lyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var preview = lyr.pathItems.getByName("__preview__");
        _bboxOriginalPoints = [];
        for (var i = 0; i < preview.pathPoints.length; i++) {
            var pp = preview.pathPoints[i];
            _bboxOriginalPoints.push({
                anchor: [pp.anchor[0], pp.anchor[1]],
                left: [pp.leftDirection[0], pp.leftDirection[1]],
                right: [pp.rightDirection[0], pp.rightDirection[1]]
            });
        }
        return "ok|" + _bboxOriginalPoints.length;
    } catch (e) {
        return "error|" + e.message;
    }
}

/**
 * Apply an affine transform matrix to the current preview path.
 * Transforms FROM stored originals to prevent cumulative drift during drag.
 * Matrix form: [a b tx; c d ty; 0 0 1]
 *
 * @param {number} a  - scale/rotate component
 * @param {number} b  - shear/rotate component
 * @param {number} c  - shear/rotate component
 * @param {number} d  - scale/rotate component
 * @param {number} tx - translation X
 * @param {number} ty - translation Y
 * @returns {string} "ok" or "error|message"
 */
function applyBboxTransform(a, b, c, d, tx, ty) {
    if (!_bboxOriginalPoints) return "error|No originals stored";
    try {
        var lyr = app.activeDocument.layers.getByName("Cleaned Forms");
        var preview = lyr.pathItems.getByName("__preview__");

        for (var i = 0; i < preview.pathPoints.length; i++) {
            var pp = preview.pathPoints[i];
            var orig = _bboxOriginalPoints[i];

            // Transform FROM originals, not from current position
            pp.anchor = [a * orig.anchor[0] + b * orig.anchor[1] + tx,
                         c * orig.anchor[0] + d * orig.anchor[1] + ty];
            pp.leftDirection = [a * orig.left[0] + b * orig.left[1] + tx,
                                c * orig.left[0] + d * orig.left[1] + ty];
            pp.rightDirection = [a * orig.right[0] + b * orig.right[1] + tx,
                                 c * orig.right[0] + d * orig.right[1] + ty];
        }

        app.redraw();
        return "ok";
    } catch (e) {
        return "error|" + e.message;
    }
}
