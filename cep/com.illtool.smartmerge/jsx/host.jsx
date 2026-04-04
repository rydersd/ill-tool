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

// Module-level cache
var _cachedPaths = null;        // from getSelectedPaths()
var _cachedPairs = null;        // from findEndpointPairs()
var _cachedNormalScores = null;  // from sidecar
var _hasSidecar = false;
var _previewPaths = [];         // references to preview pathItems
var _lastTolerance = 5;         // tolerance from most recent scan

// JSON parsing now provided by json_es3.jsx (jsonParse function)

/**
 * Attempt to load the normal sidecar file for the current document.
 * Searches multiple possible locations to match the Python-side OUTPUT_DIR.
 *
 * Returns "found|pathCount" or "notfound"
 */
function loadSidecar() {
    _cachedNormalScores = null;
    _hasSidecar = false;

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

            _cachedNormalScores = {};
            for (var j = 0; j < data.paths.length; j++) {
                var p = data.paths[j];
                if (p.name) {
                    _cachedNormalScores[p.name] = p.dominant_surface || "";
                }
            }
            _hasSidecar = true;
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
function cleanupOrphans() {
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
function scanEndpoints(tolerance, useFormAware) {
    _cachedPaths = getSelectedPaths();
    if (_cachedPaths.length < 2) return "error|Need at least 2 open paths selected";

    _lastTolerance = tolerance;
    var normalScores = (useFormAware && _hasSidecar) ? _cachedNormalScores : null;
    _cachedPairs = findEndpointPairs(_cachedPaths, tolerance, normalScores);

    if (_cachedPairs.length === 0) {
        return "0|" + _cachedPaths.length + "|0|0";
    }

    // Count same-surface vs cross-surface pairs
    var sameSurface = 0;
    var crossSurface = 0;
    if (normalScores) {
        for (var i = 0; i < _cachedPairs.length; i++) {
            var pair = _cachedPairs[i];
            var typeA = normalScores[_cachedPaths[pair.idxA].name] || "";
            var typeB = normalScores[_cachedPaths[pair.idxB].name] || "";
            if (typeA !== "" && typeB !== "" && typeA === typeB) {
                sameSurface++;
            } else {
                crossSurface++;
            }
        }
    }

    logInteraction("smartmerge", "scan", null,
        {pairCount: _cachedPairs.length, pathCount: _cachedPaths.length},
        {tolerance: tolerance, formAware: useFormAware});

    return _cachedPairs.length + "|" + _cachedPaths.length + "|" + sameSurface + "|" + crossSurface;
}

/**
 * Draw preview lines between matched endpoint pairs.
 * Same-surface pairs in green, cross-surface in red-orange.
 *
 * Returns "ok|previewCount" or "error|message"
 */
function previewMerge() {
    if (!_cachedPairs || _cachedPairs.length === 0) return "error|No pairs to preview";

    // Clean any existing previews
    _cleanPreviews();

    var lyr = ensureLayer("Merge Preview");
    _previewPaths = [];

    for (var i = 0; i < _cachedPairs.length; i++) {
        var pair = _cachedPairs[i];
        var pathA = _cachedPaths[pair.idxA];
        var pathB = _cachedPaths[pair.idxB];

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
        if (_hasSidecar && _cachedNormalScores) {
            var tA = _cachedNormalScores[pathA.name] || "";
            var tB = _cachedNormalScores[pathB.name] || "";
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
        _previewPaths.push(preview);
    }

    app.redraw();
    return "ok|" + _previewPaths.length;
}

/**
 * Execute the merge operation.
 *
 * @param {boolean} chainMerge - if true, iterate merging until no more pairs
 * @param {boolean} preserveHandles - if true, keep original handles at junction
 * Returns "merged|count" or "error|message"
 */
function executeMerge(chainMerge, preserveHandles) {
    if (!_cachedPairs || _cachedPairs.length === 0) return "error|No pairs to merge";
    if (!_cachedPaths) return "error|No cached paths";

    _cleanPreviews();

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
    for (var ci = 0; ci < _cachedPaths.length; ci++) {
        if (ci < pathItems.length) {
            _cachedPaths[ci]._ref = pathItems[ci];
        }
    }

    while (iterations < maxIterations) {
        if (iterations > 0) {
            // Re-scan for new pairs among remaining paths
            _cachedPaths = [];
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
                    _cachedPaths.push({
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

            var normalScores = _hasSidecar ? _cachedNormalScores : null;
            _cachedPairs = findEndpointPairs(_cachedPaths, _lastTolerance, normalScores);
        }

        if (!_cachedPairs || _cachedPairs.length === 0) break;

        // Process each pair
        var indicesToRemove = [];
        var newItems = [];

        for (var p = 0; p < _cachedPairs.length; p++) {
            var pair = _cachedPairs[p];
            var merged = weldPoints(
                _cachedPaths[pair.idxA].points,
                _cachedPaths[pair.idxB].points,
                pair.endA,
                pair.endB,
                preserveHandles
            );

            // Get the layer from one of the source paths
            var srcItem = _cachedPaths[pair.idxA]._ref || pathItems[pair.idxA];
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
                var item = _cachedPaths[idx]._ref || pathItems[idx];
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

        totalMerged += _cachedPairs.length;
        iterations++;
    }

    logInteraction("smartmerge", "merge", null,
        {mergedCount: totalMerged, chainMerge: chainMerge, preserveHandles: preserveHandles},
        {hasSidecar: _hasSidecar});

    // Clear caches
    _cachedPaths = null;
    _cachedPairs = null;

    app.redraw();
    return "merged|" + totalMerged;
}

/**
 * Update the merge radius and re-scan.
 * Returns same format as scanEndpoints.
 */
function updateRadius(tolerance, useFormAware) {
    if (!_cachedPaths) return "error|Run scan first";
    _lastTolerance = tolerance;
    var normalScores = (useFormAware && _hasSidecar) ? _cachedNormalScores : null;
    _cachedPairs = findEndpointPairs(_cachedPaths, tolerance, normalScores);

    var sameSurface = 0;
    var crossSurface = 0;
    if (normalScores) {
        for (var i = 0; i < _cachedPairs.length; i++) {
            var pair = _cachedPairs[i];
            var tA = normalScores[_cachedPaths[pair.idxA].name] || "";
            var tB = normalScores[_cachedPaths[pair.idxB].name] || "";
            if (tA !== "" && tB !== "" && tA === tB) sameSurface++;
            else crossSurface++;
        }
    }

    return _cachedPairs.length + "|" + _cachedPaths.length + "|" + sameSurface + "|" + crossSurface;
}

/**
 * Remove preview lines and clear state.
 * Returns "undone"
 */
function doUndoMerge() {
    _cleanPreviews();
    // Keep _cachedPaths and _cachedPairs so user can re-preview or merge
    app.redraw();
    return "undone";
}

// ── Internal helpers ─────────────────────────────────────────────

function _cleanPreviews() {
    for (var i = _previewPaths.length - 1; i >= 0; i--) {
        try { _previewPaths[i].remove(); } catch (e) {}
    }
    _previewPaths = [];

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
