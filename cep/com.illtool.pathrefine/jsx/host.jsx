/**
 * Grouping Tools — ExtendScript host functions for Illustrator.
 *
 * Thin file that #includes shared libraries and adds panel-specific
 * workflow functions. All math runs locally in ExtendScript — no
 * WebSocket dependency.
 *
 * Called from the CEP panel via CSInterface.evalScript().
 */

// Include shared libraries
// Derive shared library path from this script's location
var _PR_SHARED = (function() {
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
    try {
        var home = $.getenv("HOME") || "~";
        var cepBase = home + "/Library/Application Support/Adobe/CEP/extensions";
        var panelName = "com.illtool.pathrefine";
        var candidate = new Folder(cepBase + "/" + panelName);
        if (candidate.exists) {
            var resolved = candidate.resolve();
            if (resolved) {
                var sharedDir2 = new Folder(new Folder(resolved.fsName).parent.fsName + "/shared");
                if (sharedDir2.exists) return sharedDir2.fsName + "/";
            }
        }
    } catch (e2) {}
    return "";
})();
$.evalFile(_PR_SHARED + "json_es3.jsx");
$.evalFile(_PR_SHARED + "logging.jsx");
$.evalFile(_PR_SHARED + "math2d.jsx");
$.evalFile(_PR_SHARED + "geometry.jsx");
$.evalFile(_PR_SHARED + "shapes.jsx");
$.evalFile(_PR_SHARED + "pathutils.jsx");
$.evalFile(_PR_SHARED + "ui.jsx");

// Module-level cache (persists across evalScript calls)
var _pr_detachedPaths = [];     // references to detached pathItems
var _pr_originalAnchors = [];   // backup anchor data for reset
var _pr_lodCache = null;        // precomputed LOD levels
var _pr_originalPointCount = 0; // point count before simplification
var _pr_savedLayerOpacity = []; // saved layer opacities for isolation mode
var _pr_accentColor = [255, 136, 0]; // working path accent: orange default
var _pr_bboxData = null;        // cached bounding box parameters for overlay

/**
 * Clean up orphaned detached paths left from a previous session or crash.
 * Called on panel load. Returns the count of removed items as a string.
 */
function pr_cleanupOrphans() {
    try {
        var lyr = app.activeDocument.layers.getByName("Refined Forms");
        var toRemove = [];
        for (var i = 0; i < lyr.pathItems.length; i++) {
            var name = lyr.pathItems[i].name;
            if (name.indexOf("__detached_") === 0 && name.indexOf("__", 11) > 0) {
                toRemove.push(lyr.pathItems[i]);
            }
        }
        for (var j = toRemove.length - 1; j >= 0; j--) toRemove[j].remove();
        if (toRemove.length > 0) app.redraw();
        return toRemove.length + "";
    } catch (e) { return "0"; }
}

/**
 * Get info about the current selection.
 * Returns pipe-delimited: "anchorCount|pathCount"
 */
function pr_getSelectionInfo() {
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
var _pr_group = null;          // reference to the current detach group (working copy)
var _pr_originalGroup = null;  // hidden+locked backup of original art

function pr_detachAndPrecompute(padding, groupName) {
    if (padding === undefined || padding === null) padding = 5;
    if (groupName === undefined || groupName === null) groupName = "";
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
    _pr_cleanDetachedPaths();

    // ── Non-destructive: hide+lock originals, work on duplicates ──

    // 1. Group the original selected paths, hide and lock them
    _pr_originalGroup = lyr.groupItems.add();
    _pr_originalGroup.name = "__originals_backup__";

    // Collect selected PathItems and record per-point selection state
    // (must snapshot BEFORE duplicating, because duplicate + re-select loses point selection)
    var selPaths = [];
    var pointSelections = [];  // parallel array: per-path array of PathPointSelection values
    for (var si = 0; si < sel.length; si++) {
        if (sel[si].typename === "PathItem") {
            var path = sel[si];
            selPaths.push(path);
            var ptSel = [];
            for (var pi = 0; pi < path.pathPoints.length; pi++) {
                ptSel.push(path.pathPoints[pi].selected);
            }
            pointSelections.push(ptSel);
        }
    }

    // 2. Duplicate each selected path, move original into backup group
    var duplicates = [];
    for (var di = 0; di < selPaths.length; di++) {
        var dup = selPaths[di].duplicate();
        // Move original into backup group
        selPaths[di].move(_pr_originalGroup, ElementPlacement.PLACEATEND);
        duplicates.push(dup);
    }

    // 3. Hide and lock the backup group
    _pr_originalGroup.hidden = true;
    _pr_originalGroup.locked = true;

    // 4. Re-apply the original per-point selection to the duplicates
    doc.selection = null;
    for (var sd = 0; sd < duplicates.length; sd++) {
        duplicates[sd].selected = true;
        // Restore individual point selection from snapshot
        var savedSel = pointSelections[sd];
        if (savedSel) {
            for (var sp = 0; sp < duplicates[sd].pathPoints.length && sp < savedSel.length; sp++) {
                duplicates[sd].pathPoints[sp].selected = savedSel[sp];
            }
        }
    }

    // ── Now detach from the duplicates (originals are safe) ──

    // Create a top-level group for the detached result paths
    _pr_group = lyr.groupItems.add();
    _pr_group.name = groupName || ("detach_" + new Date().getTime());

    _pr_detachedPaths = [];
    _pr_originalAnchors = [];
    var detachedCount = 0;
    var allAnchorsFlat = [];

    for (var i = 0; i < duplicates.length; i++) {
        var path = duplicates[i];

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

        // Create detached paths from each run, inside the result group
        for (var r = 0; r < runs.length; r++) {
            var run = runs[r];
            if (run.points.length < 2) continue;

            var origCopy = [];
            for (var oc = 0; oc < run.points.length; oc++) {
                origCopy.push({
                    anchor: run.points[oc].anchor.slice(0),
                    left: run.points[oc].left.slice(0),
                    right: run.points[oc].right.slice(0)
                });
            }
            _pr_originalAnchors.push(origCopy);

            var newPath = createPathWithHandles(_pr_group, run.points, {
                name: "__detached_" + detachedCount + "__",
                closed: false,
                stroked: true,
                strokeColor: _pr_accentColor,
                strokeWidth: 1.0
            });

            _pr_detachedPaths.push(newPath);
            detachedCount++;
        }

        // Remove the duplicate (we've extracted what we need into the group)
        try { path.remove(); } catch(e) {}
    }

    if (detachedCount === 0) {
        // Nothing detached — restore originals
        try { _pr_group.remove(); } catch(e) {}
        _pr_group = null;
        _pr_restoreOriginals();
        return "error|No contiguous runs with 2+ points";
    }

    _pr_originalPointCount = allAnchorsFlat.length;

    // Compute and store bounding box data
    _pr_bboxData = null;
    if (allAnchorsFlat.length >= 2) {
        var rect = minAreaRect(allAnchorsFlat);
        _pr_bboxData = {
            center: [rect.center[0], rect.center[1]],
            width: rect.width,
            height: rect.height,
            angle: rect.angle,
            padding: padding
        };
        // Draw PathItem bbox as visual fallback (plugin overlay replaces this when connected)
        drawBoundingBox(rect.center[0], rect.center[1], rect.width, rect.height, rect.angle, padding, "Refined Forms");
    }

    // Precompute LOD levels
    if (allAnchorsFlat.length >= 3) {
        var sorted = sortByPCA(allAnchorsFlat);
        _pr_lodCache = precomputeLOD(sorted, 20);
    }

    // Isolate: dim all other layers so the working group stands out
    pr_dimOtherLayers();

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
function pr_applySimplifyLevel(level) {
    if (!_pr_lodCache) return "error|No LOD cached";

    // Find the closest level at or below the requested value
    var best = _pr_lodCache[0];
    for (var i = 0; i < _pr_lodCache.length; i++) {
        if (_pr_lodCache[i].value <= level) best = _pr_lodCache[i];
    }

    // For simplification we rebuild detached paths with the simplified points.
    // Remove existing detached paths and create a single simplified one.
    _pr_cleanDetachedPaths();

    if (best.points.length >= 2) {
        var target = _pr_group || ensureLayer("Refined Forms");
        var path = createPath(target, best.points, {
            name: "__detached_0__",
            closed: false,
            stroked: true,
            strokeColor: _pr_accentColor,
            strokeWidth: 1.0,
            computeHandles: true,
            tension: 1 / 6
        });
        _pr_detachedPaths = [path];
    }

    logInteraction("pathrefine", "simplify",
        {originalPoints: _pr_originalPointCount},
        {simplifiedPoints: best.count, level: level}, null);

    app.redraw();
    return best.count + "";
}

/**
 * Apply: solidify detached paths, clear state.
 * Returns "applied|count"
 */
function pr_doApply() {
    var count = 0;
    for (var i = 0; i < _pr_detachedPaths.length; i++) {
        try {
            var item = _pr_detachedPaths[i];
            // 80% black final stroke
            var clr = new RGBColor();
            clr.red = 51;
            clr.green = 51;
            clr.blue = 51;
            item.strokeColor = clr;
            item.strokeWidth = 1.0;
            // Rename
            item.name = "refined_" + new Date().getTime() + "_" + count;
            count++;
        } catch (e) {
            // Path may have been removed
        }
    }

    logInteraction("pathrefine", "apply", null, {count: count, group: _pr_group ? _pr_group.name : ""}, null);

    removeBoundingBox("Refined Forms");
    // Restore layer opacity from isolation mode
    pr_restoreLayerOpacity();
    // Keep the result group — it's now permanent with solid paths
    _pr_group = null;
    // Delete the hidden originals — user accepted the result
    if (_pr_originalGroup) {
        try {
            _pr_originalGroup.locked = false;
            _pr_originalGroup.remove();
        } catch(e) {}
        _pr_originalGroup = null;
    }
    _pr_detachedPaths = [];
    _pr_originalAnchors = [];
    _pr_lodCache = null;
    _pr_originalPointCount = 0;
    _pr_bboxData = null;

    app.redraw();
    return "applied|" + count;
}

/**
 * Reset: restore original point data on detached paths.
 * Returns "reset|pointCount"
 */
function pr_doReset() {
    // Remove current detached paths and recreate from originals
    _pr_cleanDetachedPaths();

    // Recreate inside the group (or layer if group was lost)
    var target = _pr_group || ensureLayer("Refined Forms");
    _pr_detachedPaths = [];
    var totalPoints = 0;

    for (var i = 0; i < _pr_originalAnchors.length; i++) {
        var origPts = _pr_originalAnchors[i];
        if (origPts.length < 2) continue;

        var newPath = createPathWithHandles(target, origPts, {
            name: "__detached_" + i + "__",
            closed: false,
            stroked: true,
            strokeColor: _pr_accentColor,
            strokeWidth: 1.0
        });

        _pr_detachedPaths.push(newPath);
        totalPoints += origPts.length;
    }

    app.redraw();
    return "reset|" + totalPoints;
}

/**
 * Undo: remove all detached paths and bounding box, clear state.
 * Returns "undone"
 */
function pr_doUndoDetach() {
    _pr_cleanDetachedPaths();
    // Remove the working group
    if (_pr_group) {
        try { _pr_group.remove(); } catch(e) {}
        _pr_group = null;
    }
    // Restore the hidden originals
    _pr_restoreOriginals();
    // Restore layer opacity from isolation mode
    pr_restoreLayerOpacity();
    removeBoundingBox("Refined Forms");
    _pr_detachedPaths = [];
    _pr_originalAnchors = [];
    _pr_lodCache = null;
    _pr_originalPointCount = 0;
    _pr_bboxData = null;
    app.redraw();
    return "undone";
}

/**
 * Restore hidden original art: unlock, unhide, ungroup back to layer.
 */
function _pr_restoreOriginals() {
    if (!_pr_originalGroup) return;
    try {
        _pr_originalGroup.locked = false;
        _pr_originalGroup.hidden = false;
        // Move paths out of backup group back to the layer
        var lyr = _pr_originalGroup.layer;
        while (_pr_originalGroup.pathItems.length > 0) {
            _pr_originalGroup.pathItems[0].move(lyr, ElementPlacement.PLACEATEND);
        }
        // Remove the now-empty backup group
        _pr_originalGroup.remove();
    } catch(e) {}
    _pr_originalGroup = null;
}

// ── Isolation mode ──────────────────────────────────────────────

/**
 * Dim all layers except "Refined Forms" to isolate the working group.
 * Saves current opacity values for restoration.
 */
function pr_dimOtherLayers() {
    _pr_savedLayerOpacity = [];
    try {
        var doc = app.activeDocument;
        for (var i = 0; i < doc.layers.length; i++) {
            var lyr = doc.layers[i];
            _pr_savedLayerOpacity.push({ index: i, opacity: lyr.opacity });
            if (lyr.name !== "Refined Forms") {
                lyr.opacity = 30;
            }
        }
    } catch (e) {}
}

/**
 * Restore all layer opacities saved by pr_dimOtherLayers().
 */
function pr_restoreLayerOpacity() {
    try {
        var doc = app.activeDocument;
        for (var i = 0; i < _pr_savedLayerOpacity.length; i++) {
            var saved = _pr_savedLayerOpacity[i];
            if (saved.index < doc.layers.length) {
                doc.layers[saved.index].opacity = saved.opacity;
            }
        }
    } catch (e) {}
    _pr_savedLayerOpacity = [];
}

/**
 * Set the accent color for working paths.
 * color: "orange" or "cyan"
 */
function pr_setAccentColor(color) {
    if (color === "cyan") {
        _pr_accentColor = [0, 200, 220];
    } else {
        _pr_accentColor = [255, 136, 0];
    }
    return "ok";
}

// ── Plugin Bridge Data ──────────────────────────────────────────

/**
 * Return JSON snapshot of current path state for C++ overlay rendering.
 * Contains original (ghost), simplified (current), and handle positions.
 */
function pr_getSimplifiedPathData() {
    var result = {original: [], simplified: [], handles: []};

    // Read original from backup anchors
    for (var i = 0; i < _pr_originalAnchors.length; i++) {
        var orig = _pr_originalAnchors[i];
        for (var j = 0; j < orig.length; j++) {
            result.original.push({
                anchor: orig[j].anchor,
                left: orig[j].left,
                right: orig[j].right
            });
        }
    }

    // Read simplified from current detached paths
    for (var k = 0; k < _pr_detachedPaths.length; k++) {
        var path = _pr_detachedPaths[k];
        try {
            for (var m = 0; m < path.pathPoints.length; m++) {
                var pp = path.pathPoints[m];
                var pt = {
                    anchor: [pp.anchor[0], pp.anchor[1]],
                    left: [pp.leftDirection[0], pp.leftDirection[1]],
                    right: [pp.rightDirection[0], pp.rightDirection[1]]
                };
                result.simplified.push(pt);
                result.handles.push({id: "handle_" + k + "_" + m, anchor: pt.anchor});
            }
        } catch (e) {
            // Path may have been removed
        }
    }

    return jsonStringify(result);
}

/**
 * Return cached bounding box parameters as JSON for overlay rendering.
 * Returns: {center: [cx, cy], width, height, angle, padding}
 * Called by the panel JS after detach to build overlay commands.
 */
function pr_getBoundingBoxData() {
    if (!_pr_bboxData) return "undefined";
    return jsonStringify(_pr_bboxData);
}

/**
 * Move a specific path point by handle ID (called from overlay drag).
 * handleId format: "handle_<pathIndex>_<pointIndex>"
 * Returns "ok" or "error|message"
 */
function pr_moveHandlePoint(handleId, newX, newY) {
    try {
        var parts = handleId.split("_");
        var pathIdx = parseInt(parts[1], 10);
        var ptIdx = parseInt(parts[2], 10);

        if (pathIdx < 0 || pathIdx >= _pr_detachedPaths.length) return "error|Invalid path index";
        var path = _pr_detachedPaths[pathIdx];
        if (ptIdx < 0 || ptIdx >= path.pathPoints.length) return "error|Invalid point index";

        var pp = path.pathPoints[ptIdx];
        var dx = newX - pp.anchor[0];
        var dy = newY - pp.anchor[1];

        // Move anchor and handles together (maintain handle shape)
        pp.anchor = [newX, newY];
        pp.leftDirection = [pp.leftDirection[0] + dx, pp.leftDirection[1] + dy];
        pp.rightDirection = [pp.rightDirection[0] + dx, pp.rightDirection[1] + dy];

        app.redraw();
        return "ok";
    } catch (e) {
        return "error|" + e.message;
    }
}

// ── Internal helpers ─────────────────────────────────────────────

/**
 * Remove all detached path items from the canvas.
 */
function _pr_cleanDetachedPaths() {
    // Remove tracked paths
    for (var i = _pr_detachedPaths.length - 1; i >= 0; i--) {
        try {
            _pr_detachedPaths[i].remove();
        } catch (e) {}
    }
    _pr_detachedPaths = [];

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
