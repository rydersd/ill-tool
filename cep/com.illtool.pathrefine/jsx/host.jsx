/**
 * Path Detach & Refine — ExtendScript host functions for Illustrator.
 *
 * Thin file that #includes shared libraries and adds panel-specific
 * workflow functions. All math runs locally in ExtendScript — no
 * WebSocket dependency.
 *
 * Called from the CEP panel via CSInterface.evalScript().
 */

// Include shared libraries
var _SHARED = "/Users/ryders/Developer/GitHub/ill_tool/cep/shared/";
$.evalFile(_SHARED + "json_es3.jsx");
$.evalFile(_SHARED + "logging.jsx");
$.evalFile(_SHARED + "math2d.jsx");
$.evalFile(_SHARED + "geometry.jsx");
$.evalFile(_SHARED + "shapes.jsx");
$.evalFile(_SHARED + "pathutils.jsx");
$.evalFile(_SHARED + "ui.jsx");

// Module-level cache (persists across evalScript calls)
var _detachedPaths = [];     // references to detached pathItems
var _originalAnchors = [];   // backup anchor data for reset
var _lodCache = null;        // precomputed LOD levels
var _originalPointCount = 0; // point count before simplification

/**
 * Get info about the current selection.
 * Returns pipe-delimited: "anchorCount|pathCount"
 */
function getSelectionInfo() {
    var counts = getSelectionCounts();
    return counts.anchorCount + "|" + counts.pathCount;
}

/**
 * Detach selected anchors and precompute LOD.
 *
 * 1. Read selected anchors with handles
 * 2. Find contiguous runs of selected points
 * 3. Create detached copies on "Refined Forms" layer
 * 4. Compute bounding box
 * 5. Precompute LOD levels for instant slider scrubbing
 *
 * Returns pipe-delimited: "detachedCount|totalPoints|done"
 * On error: "error|message"
 */
function detachAndPrecompute() {
    var doc;
    try {
        doc = app.activeDocument;
    } catch (e) {
        return "error|No active document";
    }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return "error|No selection";

    // Get or create the "Refined Forms" layer
    var lyr = ensureLayer("Refined Forms");

    // Clear any previous detached state
    _cleanDetachedPaths();

    _detachedPaths = [];
    _originalAnchors = [];
    var detachedCount = 0;
    var allAnchorsFlat = [];  // [x,y] pairs for LOD and bounding box

    for (var i = 0; i < sel.length; i++) {
        if (sel[i].typename !== "PathItem") continue;
        var path = sel[i];

        // Find contiguous runs of selected points
        var runs = [];
        var currentRun = null;

        for (var j = 0; j < path.pathPoints.length; j++) {
            var pp = path.pathPoints[j];
            if (pp.selected !== PathPointSelection.NOSELECTION) {
                if (!currentRun) currentRun = { points: [] };
                currentRun.points.push({
                    anchor: [pp.anchor[0], pp.anchor[1]],
                    left: [pp.leftDirection[0], pp.leftDirection[1]],
                    right: [pp.rightDirection[0], pp.rightDirection[1]],
                    type: pp.pointType
                });
                allAnchorsFlat.push([pp.anchor[0], pp.anchor[1]]);
            } else {
                if (currentRun) {
                    runs.push(currentRun);
                    currentRun = null;
                }
            }
        }
        if (currentRun) runs.push(currentRun);

        // Create detached paths from each run
        for (var r = 0; r < runs.length; r++) {
            var run = runs[r];
            if (run.points.length < 2) continue;

            // Save originals for reset
            var origCopy = [];
            for (var oc = 0; oc < run.points.length; oc++) {
                origCopy.push({
                    anchor: run.points[oc].anchor.slice(0),
                    left: run.points[oc].left.slice(0),
                    right: run.points[oc].right.slice(0)
                });
            }
            _originalAnchors.push(origCopy);

            var newPath = createPathWithHandles(lyr, run.points, {
                name: "__detached_" + detachedCount + "__",
                closed: false,
                stroked: true,
                strokeColor: [200, 100, 30],  // dark orange
                strokeWidth: 1.0,
                strokeDashes: [3, 3]
            });

            _detachedPaths.push(newPath);
            detachedCount++;
        }
    }

    if (detachedCount === 0) return "error|No contiguous runs with 2+ points";

    _originalPointCount = allAnchorsFlat.length;

    // Compute and draw bounding box
    if (allAnchorsFlat.length >= 2) {
        var rect = minAreaRect(allAnchorsFlat);
        drawBoundingBox(rect.center[0], rect.center[1], rect.width, rect.height, rect.angle, 5);
    }

    // Precompute LOD levels
    if (allAnchorsFlat.length >= 3) {
        var sorted = sortByPCA(allAnchorsFlat);
        _lodCache = precomputeLOD(sorted, 20);
    }

    logInteraction("pathrefine", "detach", null,
        {detachedCount: detachedCount, totalPoints: allAnchorsFlat.length}, null);

    app.redraw();
    return detachedCount + "|" + allAnchorsFlat.length + "|done";
}

/**
 * Apply a precomputed simplification level.
 * Slider value (0..100) maps to nearest cached level.
 *
 * Rebuilds detached paths with simplified point data.
 * Returns "pointCount" or "error|message"
 */
function applySimplifyLevel(level) {
    if (!_lodCache) return "error|No LOD cached";

    // Find the closest level at or below the requested value
    var best = _lodCache[0];
    for (var i = 0; i < _lodCache.length; i++) {
        if (_lodCache[i].value <= level) best = _lodCache[i];
    }

    // For simplification we rebuild detached paths with the simplified points.
    // Remove existing detached paths and create a single simplified one.
    _cleanDetachedPaths();

    if (best.points.length >= 2) {
        var lyr = ensureLayer("Refined Forms");
        var path = createPath(lyr, best.points, {
            name: "__detached_0__",
            closed: false,
            stroked: true,
            strokeColor: [200, 100, 30],
            strokeWidth: 1.0,
            strokeDashes: [3, 3],
            computeHandles: true,
            tension: 1 / 6
        });
        _detachedPaths = [path];
    }

    logInteraction("pathrefine", "simplify",
        {originalPoints: _originalPointCount},
        {simplifiedPoints: best.count, level: level}, null);

    app.redraw();
    return best.count + "";
}

/**
 * Apply: solidify detached paths, clear state.
 * Returns "applied|count"
 */
function doApply() {
    var count = 0;
    for (var i = 0; i < _detachedPaths.length; i++) {
        try {
            var item = _detachedPaths[i];
            // Make solid
            item.strokeDashes = [];
            var clr = new RGBColor();
            clr.red = 30;
            clr.green = 30;
            clr.blue = 30;
            item.strokeColor = clr;
            item.strokeWidth = 1.0;
            // Rename
            item.name = "refined_" + new Date().getTime() + "_" + count;
            count++;
        } catch (e) {
            // Path may have been removed
        }
    }

    logInteraction("pathrefine", "apply", null, {count: count}, null);

    removeBoundingBox();
    _detachedPaths = [];
    _originalAnchors = [];
    _lodCache = null;
    _originalPointCount = 0;

    app.redraw();
    return "applied|" + count;
}

/**
 * Reset: restore original point data on detached paths.
 * Returns "reset|pointCount"
 */
function doReset() {
    // Remove current detached paths and recreate from originals
    _cleanDetachedPaths();

    var lyr = ensureLayer("Refined Forms");
    _detachedPaths = [];
    var totalPoints = 0;

    for (var i = 0; i < _originalAnchors.length; i++) {
        var origPts = _originalAnchors[i];
        if (origPts.length < 2) continue;

        var newPath = createPathWithHandles(lyr, origPts, {
            name: "__detached_" + i + "__",
            closed: false,
            stroked: true,
            strokeColor: [200, 100, 30],
            strokeWidth: 1.0,
            strokeDashes: [3, 3]
        });

        _detachedPaths.push(newPath);
        totalPoints += origPts.length;
    }

    app.redraw();
    return "reset|" + totalPoints;
}

/**
 * Undo: remove all detached paths and bounding box, clear state.
 * Returns "undone"
 */
function doUndoDetach() {
    _cleanDetachedPaths();
    removeBoundingBox();
    _detachedPaths = [];
    _originalAnchors = [];
    _lodCache = null;
    _originalPointCount = 0;
    app.redraw();
    return "undone";
}

// ── Internal helpers ─────────────────────────────────────────────

/**
 * Remove all detached path items from the canvas.
 */
function _cleanDetachedPaths() {
    // Remove tracked paths
    for (var i = _detachedPaths.length - 1; i >= 0; i--) {
        try {
            _detachedPaths[i].remove();
        } catch (e) {}
    }
    _detachedPaths = [];

    // Also clean up any orphaned __detached_*__ paths on the layer
    try {
        var lyr = app.activeDocument.layers.getByName("Refined Forms");
        var toRemove = [];
        for (var j = 0; j < lyr.pathItems.length; j++) {
            var name = lyr.pathItems[j].name;
            if (name.indexOf("__detached_") === 0 && name.indexOf("__", 11) > 0) {
                toRemove.push(lyr.pathItems[j]);
            }
        }
        for (var k = toRemove.length - 1; k >= 0; k--) {
            toRemove[k].remove();
        }
    } catch (e) {}
}
