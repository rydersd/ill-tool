/**
 * Smart Merge — ExtendScript host functions for Illustrator.
 *
 * Form-edge-aware path endpoint merging with optional normal map
 * sidecar intelligence. All math runs locally in ExtendScript — no
 * WebSocket dependency.
 *
 * Called from the CEP panel via CSInterface.evalScript().
 */

// Include shared libraries
// Derive shared library path from this script's location
var _SM_SHARED = (function() {
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
        var panelName = "com.illtool.smartmerge";
        var candidate = new Folder(cepBase + "/" + panelName);
        if (candidate.exists) {
            var resolved = candidate.fsName;
            var sharedDir2 = new Folder(new Folder(resolved).parent.fsName + "/shared");
            if (sharedDir2.exists) return sharedDir2.fsName + "/";
        }
    } catch (e2) {}
    return "";
})();
$.evalFile(_SM_SHARED + "json_es3.jsx");
$.evalFile(_SM_SHARED + "logging.jsx");
$.evalFile(_SM_SHARED + "math2d.jsx");
$.evalFile(_SM_SHARED + "geometry.jsx");
$.evalFile(_SM_SHARED + "shapes.jsx");
$.evalFile(_SM_SHARED + "pathutils.jsx");
$.evalFile(_SM_SHARED + "ui.jsx");

// Module-level cache
var _sm_cachedPaths = null;        // from getSelectedPaths()
var _sm_cachedPairs = null;        // from findEndpointPairs()
var _sm_cachedNormalScores = null;  // from sidecar
var _sm_hasSidecar = false;
var _sm_previewPaths = [];         // references to preview pathItems
var _sm_lastTolerance = 5;         // tolerance from most recent scan

// JSON parsing now provided by json_es3.jsx (jsonParse function)

/**
 * Attempt to load the normal sidecar file for the current document.
 * Searches multiple possible locations to match the Python-side OUTPUT_DIR.
 *
 * Returns "found|pathCount" or "notfound"
 */
function sm_loadSidecar() {
    _sm_cachedNormalScores = null;
    _sm_hasSidecar = false;

    var doc;
    try { doc = app.activeDocument; } catch (e) { return "notfound"; }

    var docName = doc.name.replace(/\.[^.]+$/, "").replace(/[\/\\:]/g, "_"); // strip extension, sanitize path chars

    // Search multiple possible sidecar locations
    // Python writes to /tmp/ai_form_edges_{os.getuid()}/ — numeric UID
    var candidates = [
        "/tmp/illtool_cache/" + docName + "_normals.json",
        "~/Library/Application Support/illtool/cache/" + docName + "_normals.json"
    ];

    // Enumerate /tmp/ai_form_edges_*/ directories (handles numeric UID mismatch)
    var tmpDir = new Folder("/tmp");
    if (tmpDir.exists) {
        var formEdgeDirs = tmpDir.getFiles("ai_form_edges_*");
        for (var di = 0; di < formEdgeDirs.length; di++) {
            if (formEdgeDirs[di] instanceof Folder) {
                // Try exact docName match first
                candidates.push(formEdgeDirs[di].fsName + "/" + docName + "_normals.json");
                // Then enumerate all sidecar files in this directory
                var sidecarFiles = formEdgeDirs[di].getFiles("*_normals.json");
                for (var fi = 0; fi < sidecarFiles.length; fi++) {
                    candidates.push(sidecarFiles[fi].fsName);
                }
            }
        }
    }

    for (var i = 0; i < candidates.length; i++) {
        var f = new File(candidates[i]);
        if (!f.exists) continue;

        try {
            f.open("r");
            var content = f.read();
            f.close();

            var data = jsonParse(content);
            if (!data || !data.paths) continue;

            _sm_cachedNormalScores = {};
            for (var j = 0; j < data.paths.length; j++) {
                var p = data.paths[j];
                if (p.name) {
                    _sm_cachedNormalScores[p.name] = p.dominant_surface || "";
                }
            }
            _sm_hasSidecar = true;
            return "found|" + data.paths.length;
        } catch (e) {
            continue;
        }
    }

    return "notfound";
}

/**
 * Clean up orphaned merge preview paths left from a previous session or crash.
 * Called on panel load. Returns the count of removed items as a string.
 */
function sm_cleanupOrphans() {
    try {
        var lyr = app.activeDocument.layers.getByName("Merge Preview");
        var toRemove = [];
        for (var i = 0; i < lyr.pathItems.length; i++) {
            var name = lyr.pathItems[i].name;
            if (name.indexOf("__merge_preview_") === 0) {
                toRemove.push(lyr.pathItems[i]);
            }
        }
        for (var j = toRemove.length - 1; j >= 0; j--) toRemove[j].remove();
        if (toRemove.length > 0) app.redraw();
        return toRemove.length + "";
    } catch (e) { return "0"; }
}

/**
 * Scan selected paths for endpoint merge candidates.
 *
 * Returns pipe-delimited: "pairCount|pathCount|sameSurface|crossSurface"
 * On error: "error|message"
 */
function sm_scanEndpoints(tolerance, useFormAware) {
    _sm_cachedPaths = getSelectedPaths();
    if (_sm_cachedPaths.length < 2) return "error|Need at least 2 open paths selected";

    _sm_lastTolerance = tolerance;
    var normalScores = (useFormAware && _sm_hasSidecar) ? _sm_cachedNormalScores : null;
    _sm_cachedPairs = findEndpointPairs(_sm_cachedPaths, tolerance, normalScores);

    if (_sm_cachedPairs.length === 0) {
        return "0|" + _sm_cachedPaths.length + "|0|0";
    }

    // Count same-surface vs cross-surface pairs
    var sameSurface = 0;
    var crossSurface = 0;
    if (normalScores) {
        for (var i = 0; i < _sm_cachedPairs.length; i++) {
            var pair = _sm_cachedPairs[i];
            var typeA = normalScores[_sm_cachedPaths[pair.idxA].name] || "";
            var typeB = normalScores[_sm_cachedPaths[pair.idxB].name] || "";
            if (typeA !== "" && typeB !== "" && typeA === typeB) {
                sameSurface++;
            } else {
                crossSurface++;
            }
        }
    }

    logInteraction("smartmerge", "scan", null,
        {pairCount: _sm_cachedPairs.length, pathCount: _sm_cachedPaths.length},
        {tolerance: tolerance, formAware: useFormAware});

    return _sm_cachedPairs.length + "|" + _sm_cachedPaths.length + "|" + sameSurface + "|" + crossSurface;
}

/**
 * Draw preview lines between matched endpoint pairs.
 * Same-surface pairs in green, cross-surface in red-orange.
 *
 * Returns "ok|previewCount" or "error|message"
 */
function sm_previewMerge() {
    if (!_sm_cachedPairs || _sm_cachedPairs.length === 0) return "error|No pairs to preview";

    // Clean any existing previews
    _sm_cleanPreviews();

    var lyr = ensureLayer("Merge Preview");
    _sm_previewPaths = [];

    for (var i = 0; i < _sm_cachedPairs.length; i++) {
        var pair = _sm_cachedPairs[i];
        var pathA = _sm_cachedPaths[pair.idxA];
        var pathB = _sm_cachedPaths[pair.idxB];

        // Get endpoints for the preview line
        var ptA = (pair.endA === "end")
            ? pathA.points[pathA.points.length - 1].anchor
            : pathA.points[0].anchor;
        var ptB = (pair.endB === "start")
            ? pathB.points[0].anchor
            : pathB.points[pathB.points.length - 1].anchor;

        // Determine color and dash pattern:
        //   same-surface: green, even dashes (visually uniform)
        //   cross-surface: dark orange, long-short dashes (visually distinct for colorblind users)
        var strokeColor;
        var strokeDashes;
        if (_sm_hasSidecar && _sm_cachedNormalScores) {
            var tA = _sm_cachedNormalScores[pathA.name] || "";
            var tB = _sm_cachedNormalScores[pathB.name] || "";
            if (tA !== "" && tB !== "" && tA === tB) {
                strokeColor = [60, 180, 60];    // green — same surface
                strokeDashes = [4, 4];          // even dashes
            } else {
                strokeColor = [200, 80, 30];    // dark orange — cross surface
                strokeDashes = [8, 3, 2, 3];    // long-short (visually distinct)
            }
        } else {
            strokeColor = [200, 100, 30]; // default dark orange
            strokeDashes = [4, 4];
        }

        var preview = createPath(lyr, [ptA, ptB], {
            name: "__merge_preview_" + i + "__",
            closed: false,
            stroked: true,
            strokeColor: strokeColor,
            strokeWidth: 1.5,
            strokeDashes: strokeDashes
        });
        _sm_previewPaths.push(preview);
    }

    app.redraw();
    return "ok|" + _sm_previewPaths.length;
}

/**
 * Execute the merge operation.
 *
 * @param {boolean} chainMerge - if true, iterate merging until no more pairs
 * @param {boolean} preserveHandles - if true, keep original handles at junction
 * Returns "merged|count" or "error|message"
 */
function sm_executeMerge(chainMerge, preserveHandles) {
    if (!_sm_cachedPairs || _sm_cachedPairs.length === 0) return "error|No pairs to merge";
    if (!_sm_cachedPaths) return "error|No cached paths";

    _sm_cleanPreviews();

    var doc;
    try { doc = app.activeDocument; } catch (e) { return "error|No document"; }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return "error|No selection";

    // Build map of selection index to pathItem reference
    var pathItems = [];
    for (var s = 0; s < sel.length; s++) {
        if (sel[s].typename === "PathItem" && !sel[s].closed) {
            pathItems.push(sel[s]);
        }
    }

    var totalMerged = 0;
    var iterations = 0;
    var maxIterations = chainMerge ? 10 : 1;

    // Attach _ref to cached paths on the first iteration so lookups
    // don't fall through to the positional pathItems fallback (which
    // could mis-index if the arrays ever diverge).
    for (var ci = 0; ci < _sm_cachedPaths.length; ci++) {
        if (ci < pathItems.length) {
            _sm_cachedPaths[ci]._ref = pathItems[ci];
        }
    }

    while (iterations < maxIterations) {
        if (iterations > 0) {
            // Re-scan for new pairs among remaining paths
            _sm_cachedPaths = [];
            for (var r = 0; r < pathItems.length; r++) {
                try {
                    var pi = pathItems[r];
                    var pts = [];
                    for (var j = 0; j < pi.pathPoints.length; j++) {
                        var pp = pi.pathPoints[j];
                        pts.push({
                            anchor: [pp.anchor[0], pp.anchor[1]],
                            left: [pp.leftDirection[0], pp.leftDirection[1]],
                            right: [pp.rightDirection[0], pp.rightDirection[1]]
                        });
                    }
                    _sm_cachedPaths.push({
                        name: pi.name,
                        closed: false,
                        index: r,
                        points: pts,
                        _ref: pi
                    });
                } catch (e) {
                    // pathItem may have been removed
                }
            }

            var normalScores = _sm_hasSidecar ? _sm_cachedNormalScores : null;
            _sm_cachedPairs = findEndpointPairs(_sm_cachedPaths, _sm_lastTolerance, normalScores);
        }

        if (!_sm_cachedPairs || _sm_cachedPairs.length === 0) break;

        // Process each pair
        var indicesToRemove = [];
        var newItems = [];

        for (var p = 0; p < _sm_cachedPairs.length; p++) {
            var pair = _sm_cachedPairs[p];
            var merged = weldPoints(
                _sm_cachedPaths[pair.idxA].points,
                _sm_cachedPaths[pair.idxB].points,
                pair.endA,
                pair.endB,
                preserveHandles
            );

            // Get the layer from one of the source paths
            var srcItem = _sm_cachedPaths[pair.idxA]._ref || pathItems[pair.idxA];
            var targetLayer;
            try {
                targetLayer = srcItem.layer;
            } catch (e) {
                targetLayer = ensureLayer("Merged Paths");
            }

            // Create the merged path
            var newPath = createPathWithHandles(targetLayer, merged, {
                name: "merged_" + new Date().getTime() + "_" + p,
                closed: false,
                stroked: true,
                strokeColor: [30, 30, 30],
                strokeWidth: 1.0
            });
            newItems.push(newPath);

            // Mark originals for removal
            indicesToRemove.push(pair.idxA);
            indicesToRemove.push(pair.idxB);
        }

        // Remove originals (reverse order to preserve indices)
        var sorted = indicesToRemove.slice(0).sort(function (a, b) { return b - a; });
        var removed = {};
        for (var d = 0; d < sorted.length; d++) {
            var idx = sorted[d];
            if (removed[idx]) continue;
            removed[idx] = true;
            try {
                var item = _sm_cachedPaths[idx]._ref || pathItems[idx];
                item.remove();
            } catch (e) {}
        }

        // Update pathItems list: remove consumed, add new
        var newPathItems = [];
        for (var k = 0; k < pathItems.length; k++) {
            if (!removed[k]) newPathItems.push(pathItems[k]);
        }
        for (var n = 0; n < newItems.length; n++) {
            newPathItems.push(newItems[n]);
        }
        pathItems = newPathItems;

        totalMerged += _sm_cachedPairs.length;
        iterations++;
    }

    logInteraction("smartmerge", "merge", null,
        {mergedCount: totalMerged, chainMerge: chainMerge, preserveHandles: preserveHandles},
        {hasSidecar: _sm_hasSidecar});

    // Clear caches
    _sm_cachedPaths = null;
    _sm_cachedPairs = null;

    app.redraw();
    return "merged|" + totalMerged;
}

/**
 * Update the merge radius and re-scan.
 * Returns same format as scanEndpoints.
 */
function sm_updateRadius(tolerance, useFormAware) {
    if (!_sm_cachedPaths) return "error|Run scan first";
    _sm_lastTolerance = tolerance;
    var normalScores = (useFormAware && _sm_hasSidecar) ? _sm_cachedNormalScores : null;
    _sm_cachedPairs = findEndpointPairs(_sm_cachedPaths, tolerance, normalScores);

    var sameSurface = 0;
    var crossSurface = 0;
    if (normalScores) {
        for (var i = 0; i < _sm_cachedPairs.length; i++) {
            var pair = _sm_cachedPairs[i];
            var tA = normalScores[_sm_cachedPaths[pair.idxA].name] || "";
            var tB = normalScores[_sm_cachedPaths[pair.idxB].name] || "";
            if (tA !== "" && tB !== "" && tA === tB) sameSurface++;
            else crossSurface++;
        }
    }

    return _sm_cachedPairs.length + "|" + _sm_cachedPaths.length + "|" + sameSurface + "|" + crossSurface;
}

/**
 * Remove preview lines and clear state.
 * Returns "undone"
 */
function sm_doUndoMerge() {
    _sm_cleanPreviews();
    // Keep _sm_cachedPaths and _sm_cachedPairs so user can re-preview or merge
    app.redraw();
    return "undone";
}

// ── Internal helpers ─────────────────────────────────────────────

function _sm_cleanPreviews() {
    for (var i = _sm_previewPaths.length - 1; i >= 0; i--) {
        try { _sm_previewPaths[i].remove(); } catch (e) {}
    }
    _sm_previewPaths = [];

    // Also clean orphaned preview paths
    try {
        var lyr = app.activeDocument.layers.getByName("Merge Preview");
        var toRemove = [];
        for (var j = 0; j < lyr.pathItems.length; j++) {
            if (lyr.pathItems[j].name.indexOf("__merge_preview_") === 0) {
                toRemove.push(lyr.pathItems[j]);
            }
        }
        for (var k = toRemove.length - 1; k >= 0; k--) {
            toRemove[k].remove();
        }
    } catch (e) {}
}
