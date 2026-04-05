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
var _pr_gapPaths = [];          // unselected-segment paths (removed on undo/apply)
var _pr_originalAnchors = [];   // backup anchor data for reset
var _pr_lodCache = null;        // precomputed LOD levels
var _pr_originalPointCount = 0; // point count before simplification

/**
 * Clean up orphaned detached paths left from a previous session or crash.
 * Called on panel load. Returns the count of removed items as a string.
 */
function pr_cleanupOrphans() {
    try {
        var doc = app.activeDocument;
        var toRemove = [];

        // Clean orphaned __detached_*__ on Refined Forms layer
        try {
            var lyr = doc.layers.getByName("Refined Forms");
            for (var i = 0; i < lyr.pathItems.length; i++) {
                var name = lyr.pathItems[i].name;
                if (name.indexOf("__detached_") === 0 && name.indexOf("__", 11) > 0) {
                    toRemove.push(lyr.pathItems[i]);
                }
            }
        } catch (e) {}

        // Clean orphaned __gap_*__ on any layer
        for (var li = 0; li < doc.layers.length; li++) {
            var layer = doc.layers[li];
            for (var gi = 0; gi < layer.pathItems.length; gi++) {
                var gname = layer.pathItems[gi].name;
                if (gname.indexOf("__gap_") === 0 && gname.lastIndexOf("__") > 5) {
                    toRemove.push(layer.pathItems[gi]);
                }
            }
        }

        for (var j = toRemove.length - 1; j >= 0; j--) toRemove[j].remove();
        if (toRemove.length > 0) app.redraw();
        return toRemove.length + "";
    } catch (e) { return "0"; }
}

/**
 * Get info about the current selection.
 * Returns pipe-delimited: "anchorCount|pathCount|inGroup"
 */
function pr_getSelectionInfo() {
    var counts = getSelectionCounts();
    var inGroup = false;
    try {
        var sel = app.activeDocument.selection;
        if (sel && sel.length > 0 && sel[0].parent && sel[0].parent.typename === "GroupItem") {
            inGroup = true;
        }
    } catch(e) {}
    return counts.anchorCount + "|" + counts.pathCount + "|" + (inGroup ? "1" : "0");
}

/**
 * Copy selected anchors to a new group on "Refined Forms" layer.
 * Non-destructive: originals stay on their layer, untouched.
 *
 * 1. Duplicate selected paths to read selection state
 * 2. Find contiguous runs of selected points
 * 3. Remove duplicates (they were only for reading selection)
 * 4. Create new paths from selected runs in a group on Refined Forms
 * 5. Precompute LOD levels for instant slider scrubbing
 *
 * Returns pipe-delimited: "detachedCount|totalPoints|done"
 * On error: "error|message"
 */
var _pr_group = null;          // reference to the current working group

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

    // Collect selected PathItems (snapshot)
    var selPaths = [];
    for (var si = 0; si < sel.length; si++) {
        if (sel[si].typename === "PathItem") selPaths.push(sel[si]);
    }

    // ── Duplicate to read selection state, then discard duplicates ──

    var duplicates = [];
    for (var di = 0; di < selPaths.length; di++) {
        duplicates.push(selPaths[di].duplicate());
    }

    // Create a top-level group for the new paths
    _pr_group = lyr.groupItems.add();
    _pr_group.name = groupName || ("detach_" + new Date().getTime());

    _pr_detachedPaths = [];
    _pr_gapPaths = [];
    _pr_originalAnchors = [];
    var detachedCount = 0;
    var allAnchorsFlat = [];

    for (var i = 0; i < duplicates.length; i++) {
        var path = duplicates[i];

        // Read ALL points with their selection state from the duplicate
        var allPts = [];
        var selectedCount = 0;
        for (var j = 0; j < path.pathPoints.length; j++) {
            var pp = path.pathPoints[j];
            var isSel = (pp.selected !== PathPointSelection.NOSELECTION);
            if (isSel) selectedCount++;
            allPts.push({
                anchor: [pp.anchor[0], pp.anchor[1]],
                left: [pp.leftDirection[0], pp.leftDirection[1]],
                right: [pp.rightDirection[0], pp.rightDirection[1]],
                type: pp.pointType,
                selected: isSel
            });
        }

        // Remove the duplicate — we only needed it for selection state
        try { path.remove(); } catch(e) {}

        // Find contiguous runs of selected points
        var runs = [];
        var currentRun = null;

        for (var j2 = 0; j2 < allPts.length; j2++) {
            var pt = allPts[j2];
            if (pt.selected) {
                if (!currentRun) currentRun = { points: [] };
                currentRun.points.push(pt);
                allAnchorsFlat.push(pt.anchor.slice(0));
            } else {
                if (currentRun) {
                    runs.push(currentRun);
                    currentRun = null;
                }
            }
        }
        if (currentRun) runs.push(currentRun);

        // Create new paths from each selected run, inside the result group
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
                strokeColor: [200, 100, 30],
                strokeWidth: 1.0,
                strokeDashes: []
            });

            _pr_detachedPaths.push(newPath);
            detachedCount++;
        }
    }

    if (detachedCount === 0) {
        // Nothing created — clean up
        try { _pr_group.remove(); } catch(e) {}
        _pr_group = null;
        return "error|No contiguous runs with 2+ points";
    }

    _pr_originalPointCount = allAnchorsFlat.length;

    // Precompute LOD levels
    if (allAnchorsFlat.length >= 3) {
        var sorted = sortByPCA(allAnchorsFlat);
        _pr_lodCache = precomputeLOD(sorted, 20);
    }

    // Go into isolation mode — no bounding box, use native handles
    try {
        doc.selection = null;
        if (_pr_detachedPaths.length > 0) {
            _pr_detachedPaths[0].selected = true;
        }
        app.executeMenuCommand("isolate");
        app.executeMenuCommand("direct");
    } catch (e) {}

    logInteraction("pathrefine", "copy-to-group", null,
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
            strokeColor: [200, 100, 30],
            strokeWidth: 1.0,
            strokeDashes: [],
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
 * Apply: finalize group paths (originals untouched), clear state.
 * Returns "applied|count"
 */
function pr_doApply() {
    var count = 0;
    for (var i = 0; i < _pr_detachedPaths.length; i++) {
        try {
            var item = _pr_detachedPaths[i];
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

    logInteraction("pathrefine", "apply", null, {count: count, group: _pr_group ? _pr_group.name : ""}, null);

    // Keep the result group — it's now permanent with solid paths
    _pr_group = null;
    // No originals to restore — they were never moved
    _pr_detachedPaths = [];
    _pr_gapPaths = [];
    _pr_originalAnchors = [];
    _pr_lodCache = null;
    _pr_originalPointCount = 0;

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
            strokeColor: [200, 100, 30],
            strokeWidth: 1.0,
            strokeDashes: []
        });

        _pr_detachedPaths.push(newPath);
        totalPoints += origPts.length;
    }

    app.redraw();
    return "reset|" + totalPoints;
}

/**
 * Undo: remove all created group paths, clear state.
 * Originals are untouched since copy-to-group is non-destructive.
 * Returns "undone"
 */
function pr_doUndoDetach() {
    _pr_cleanDetachedPaths();
    // Remove the working group
    if (_pr_group) {
        try { _pr_group.remove(); } catch(e) {}
        _pr_group = null;
    }
    _pr_detachedPaths = [];
    _pr_gapPaths = [];
    _pr_originalAnchors = [];
    _pr_lodCache = null;
    _pr_originalPointCount = 0;
    app.redraw();
    return "undone";
}

// ── Group Operations ─────────────────────────────────────────────

/**
 * Detach selected items from their parent group to the layer.
 * Returns "detached|count"
 */
function pr_detachFromGroup() {
    var doc = app.activeDocument;
    var sel = doc.selection;
    var count = 0;
    for (var i = sel.length - 1; i >= 0; i--) {
        try {
            if (sel[i].parent && sel[i].parent.typename === "GroupItem") {
                var parentLayer = sel[i].parent.layer;
                sel[i].move(parentLayer, ElementPlacement.PLACEATEND);
                count++;
            }
        } catch(e) {}
    }
    app.redraw();
    return "detached|" + count;
}

/**
 * Split selected items into a new named group on the same layer.
 * Returns "split|count|groupName" or "error|message"
 */
function pr_splitToNewGroup(newGroupName) {
    var doc = app.activeDocument;
    var sel = doc.selection;
    if (!sel || sel.length === 0) return "error|No selection";
    var lyr = sel[0].layer;
    var newGroup = lyr.groupItems.add();
    newGroup.name = newGroupName || ("split_" + new Date().getTime());
    var count = 0;
    for (var i = sel.length - 1; i >= 0; i--) {
        try {
            sel[i].move(newGroup, ElementPlacement.PLACEATEND);
            count++;
        } catch(e) {}
    }
    app.redraw();
    return "split|" + count + "|" + newGroup.name;
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

/**
 * Remove all gap (unselected remainder) path items from the canvas.
 */
function _pr_cleanGapPaths() {
    // Remove tracked gap paths
    for (var i = _pr_gapPaths.length - 1; i >= 0; i--) {
        try {
            _pr_gapPaths[i].remove();
        } catch (e) {}
    }
    _pr_gapPaths = [];

    // Also clean up any orphaned __gap_*__ paths across all layers
    try {
        var doc = app.activeDocument;
        for (var li = 0; li < doc.layers.length; li++) {
            var layer = doc.layers[li];
            var toRemove = [];
            for (var j = 0; j < layer.pathItems.length; j++) {
                var name = layer.pathItems[j].name;
                if (name.indexOf("__gap_") === 0 && name.lastIndexOf("__") > 5) {
                    toRemove.push(layer.pathItems[j]);
                }
            }
            for (var k = toRemove.length - 1; k >= 0; k--) {
                toRemove[k].remove();
            }
        }
    } catch (e) {}
}
