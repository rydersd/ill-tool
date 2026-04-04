/**
 * pathutils.jsx — Illustrator path reading and manipulation for ExtendScript (ES3).
 *
 * Requires: math2d.jsx (must be #included first)
 *
 * Functions that touch the Illustrator DOM: reading selections, creating
 * paths, computing handles.
 */

/**
 * Read only the SELECTED anchor points from all selected PathItems.
 * Uses Direct Selection / Lasso tool selection state.
 *
 * @returns {Array} array of [x, y] for each selected anchor
 */
function getSelectedAnchors() {
    var doc;
    try {
        doc = app.activeDocument;
    } catch (e) {
        return [];
    }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return [];

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
    return anchors;
}

/**
 * Read selected anchors with full handle data.
 *
 * @returns {Array} array of {anchor:[x,y], left:[x,y], right:[x,y], type:PointType}
 */
function getSelectedAnchorsWithHandles() {
    var doc;
    try {
        doc = app.activeDocument;
    } catch (e) {
        return [];
    }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return [];

    var anchors = [];
    for (var i = 0; i < sel.length; i++) {
        if (sel[i].typename !== "PathItem") continue;
        for (var j = 0; j < sel[i].pathPoints.length; j++) {
            var pp = sel[i].pathPoints[j];
            if (pp.selected !== PathPointSelection.NOSELECTION) {
                anchors.push({
                    anchor: [pp.anchor[0], pp.anchor[1]],
                    left: [pp.leftDirection[0], pp.leftDirection[1]],
                    right: [pp.rightDirection[0], pp.rightDirection[1]],
                    type: pp.pointType
                });
            }
        }
    }
    return anchors;
}

/**
 * Count selected anchors and unique paths that have selections.
 *
 * @returns {Object} {anchorCount: N, pathCount: N}
 */
function getSelectionCounts() {
    var doc;
    try {
        doc = app.activeDocument;
    } catch (e) {
        return { anchorCount: 0, pathCount: 0 };
    }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return { anchorCount: 0, pathCount: 0 };

    var anchorCount = 0;
    var pathCount = 0;

    for (var i = 0; i < sel.length; i++) {
        if (sel[i].typename !== "PathItem") continue;
        var hasSelected = false;
        for (var j = 0; j < sel[i].pathPoints.length; j++) {
            if (sel[i].pathPoints[j].selected !== PathPointSelection.NOSELECTION) {
                anchorCount++;
                hasSelected = true;
            }
        }
        if (hasSelected) pathCount++;
    }

    return { anchorCount: anchorCount, pathCount: pathCount };
}

/**
 * Create a path on a specified layer with given points and options.
 *
 * @param {Layer} layer - target layer
 * @param {Array} points - array of [x, y]
 * @param {Object} options - {name, closed, filled, stroked, strokeColor:[r,g,b],
 *                            strokeWidth, strokeDashes, computeHandles, tension}
 * @returns {PathItem} the created path
 */
function createPath(layer, points, options) {
    if (!options) options = {};
    var path = layer.pathItems.add();

    path.name = options.name || "";
    path.filled = options.filled || false;
    path.stroked = (options.stroked !== undefined) ? options.stroked : true;
    path.closed = options.closed || false;

    if (options.strokeColor) {
        var clr = new RGBColor();
        clr.red = options.strokeColor[0];
        clr.green = options.strokeColor[1];
        clr.blue = options.strokeColor[2];
        path.strokeColor = clr;
    }
    if (options.strokeWidth !== undefined) path.strokeWidth = options.strokeWidth;
    if (options.strokeDashes) path.strokeDashes = options.strokeDashes;

    // Add points
    for (var i = 0; i < points.length; i++) {
        var pp = path.pathPoints.add();
        pp.anchor = [points[i][0], points[i][1]];
        // Default: retracted handles (corner points)
        pp.leftDirection = pp.anchor;
        pp.rightDirection = pp.anchor;
    }

    // Optionally compute smooth handles after all points are placed
    if (options.computeHandles) {
        computeSmoothHandles(path, options.tension || (1 / 6));
    }

    return path;
}

/**
 * Compute smooth cubic Bezier handles for all points on a path.
 * Uses Catmull-Rom-style tangent: handle = anchor +/- tangent * tension.
 *
 * @param {PathItem} path - the path to modify in place
 * @param {number} tension - handle length factor (default 1/6)
 */
function computeSmoothHandles(path, tension) {
    if (!tension) tension = 1 / 6;
    var n = path.pathPoints.length;
    if (n < 2) return;

    for (var i = 0; i < n; i++) {
        var pp = path.pathPoints[i];
        var ax = pp.anchor[0];
        var ay = pp.anchor[1];

        var prevIdx, nextIdx;
        if (path.closed) {
            prevIdx = (i - 1 + n) % n;
            nextIdx = (i + 1) % n;
        } else {
            prevIdx = Math.max(0, i - 1);
            nextIdx = Math.min(n - 1, i + 1);
        }

        var prev = path.pathPoints[prevIdx].anchor;
        var next = path.pathPoints[nextIdx].anchor;

        if (prevIdx === i && nextIdx === i) {
            // Single-point path
            pp.leftDirection = [ax, ay];
            pp.rightDirection = [ax, ay];
        } else if (!path.closed && (i === 0 || i === n - 1)) {
            // Endpoints on open paths: retracted handles
            pp.leftDirection = [ax, ay];
            pp.rightDirection = [ax, ay];
        } else {
            // Interior or closed-path point: smooth tangent
            var tx = (next[0] - prev[0]) * tension;
            var ty = (next[1] - prev[1]) * tension;
            pp.leftDirection = [ax - tx, ay - ty];
            pp.rightDirection = [ax + tx, ay + ty];
        }
    }
}

/**
 * Create a path from an array of {anchor, left, right} objects,
 * preserving explicit handle positions.
 *
 * @param {Layer} layer - target layer
 * @param {Array} pointData - array of {anchor:[x,y], left:[x,y], right:[x,y]}
 * @param {Object} options - same as createPath options (minus computeHandles)
 * @returns {PathItem}
 */
function createPathWithHandles(layer, pointData, options) {
    if (!options) options = {};
    var path = layer.pathItems.add();

    path.name = options.name || "";
    path.filled = options.filled || false;
    path.stroked = (options.stroked !== undefined) ? options.stroked : true;
    path.closed = options.closed || false;

    if (options.strokeColor) {
        var clr = new RGBColor();
        clr.red = options.strokeColor[0];
        clr.green = options.strokeColor[1];
        clr.blue = options.strokeColor[2];
        path.strokeColor = clr;
    }
    if (options.strokeWidth !== undefined) path.strokeWidth = options.strokeWidth;
    if (options.strokeDashes) path.strokeDashes = options.strokeDashes;

    for (var i = 0; i < pointData.length; i++) {
        var pd = pointData[i];
        var pp = path.pathPoints.add();
        pp.anchor = pd.anchor;
        pp.leftDirection = pd.left;
        pp.rightDirection = pd.right;
    }

    return path;
}

// ---------------------------------------------------------------------------
// Merge / Weld functions — used by Smart Merge CEP panel
// ---------------------------------------------------------------------------

/**
 * Read complete path data from all selected PathItems.
 * Unlike getSelectedAnchors(), this reads ALL points on each selected path,
 * not just selected anchor points.
 *
 * @returns {Array} [{name: string, closed: boolean, index: number,
 *                     points: [{anchor: [x,y], left: [x,y], right: [x,y]}...]}]
 */
function getSelectedPaths() {
    var doc;
    try { doc = app.activeDocument; } catch (e) { return []; }

    var sel = doc.selection;
    if (!sel || sel.length === 0) return [];

    var paths = [];
    for (var i = 0; i < sel.length; i++) {
        if (sel[i].typename !== "PathItem") continue;
        if (sel[i].closed) continue; // closed paths have no endpoints to merge

        var pi = sel[i];
        var pts = [];
        for (var j = 0; j < pi.pathPoints.length; j++) {
            var pp = pi.pathPoints[j];
            pts.push({
                anchor: [pp.anchor[0], pp.anchor[1]],
                left: [pp.leftDirection[0], pp.leftDirection[1]],
                right: [pp.rightDirection[0], pp.rightDirection[1]]
            });
        }

        paths.push({
            name: pi.name,
            closed: pi.closed,
            index: i,
            points: pts
        });
    }
    return paths;
}

/**
 * Find pairs of path endpoints within tolerance distance.
 * Optionally weights by normal/surface similarity scores.
 *
 * @param {Array} paths - from getSelectedPaths()
 * @param {number} tolerance - max distance between endpoints (points)
 * @param {Object} normalScores - optional {pathName: surfaceType} map for form-aware scoring.
 *                                 When present, same-surface pairs score higher.
 * @returns {Array} [{idxA, idxB, endA: "start"|"end", endB: "start"|"end", distance, score}]
 */
function findEndpointPairs(paths, tolerance, normalScores) {
    var pairs = [];
    var used = {};  // ES3: use object instead of Set

    for (var i = 0; i < paths.length; i++) {
        if (used[i]) continue;
        var ptsA = paths[i].points;
        if (!ptsA || ptsA.length === 0) continue;

        var aStart = ptsA[0].anchor;
        var aEnd = ptsA[ptsA.length - 1].anchor;

        var bestJ = -1;
        var bestScore = -1;
        var bestDist = Infinity;
        var bestEA = "";
        var bestEB = "";

        for (var j = i + 1; j < paths.length; j++) {
            if (used[j]) continue;
            var ptsB = paths[j].points;
            if (!ptsB || ptsB.length === 0) continue;

            var bStart = ptsB[0].anchor;
            var bEnd = ptsB[ptsB.length - 1].anchor;

            // Check all 4 endpoint combinations
            var candidates = [
                {d: dist2d(aEnd, bStart), ea: "end", eb: "start"},
                {d: dist2d(aEnd, bEnd), ea: "end", eb: "end"},
                {d: dist2d(aStart, bStart), ea: "start", eb: "start"},
                {d: dist2d(aStart, bEnd), ea: "start", eb: "end"}
            ];

            // Find closest endpoint pair within tolerance
            for (var c = 0; c < candidates.length; c++) {
                if (candidates[c].d <= tolerance) {
                    // Compute score: proximity + optional surface similarity
                    var proxScore = 1.0 - (candidates[c].d / tolerance);
                    var surfScore = 1.0;

                    if (normalScores) {
                        var typeA = normalScores[paths[i].name] || "";
                        var typeB = normalScores[paths[j].name] || "";
                        surfScore = (typeA !== "" && typeB !== "" && typeA === typeB) ? 1.0 : 0.3;
                    }

                    var totalScore = proxScore * surfScore;

                    if (totalScore > bestScore || (totalScore === bestScore && candidates[c].d < bestDist)) {
                        bestJ = j;
                        bestScore = totalScore;
                        bestDist = candidates[c].d;
                        bestEA = candidates[c].ea;
                        bestEB = candidates[c].eb;
                    }
                }
            }
        }

        if (bestJ >= 0) {
            pairs.push({
                idxA: i,
                idxB: bestJ,
                endA: bestEA,
                endB: bestEB,
                distance: bestDist,
                score: bestScore
            });
            used[i] = true;
            used[bestJ] = true;
        }
    }

    return pairs;
}

/**
 * Concatenate two point arrays at matching endpoints.
 * Averages the junction point (or preserves handles in GIR mode).
 *
 * @param {Array} ptsA - [{anchor, left, right}...]
 * @param {Array} ptsB - [{anchor, left, right}...]
 * @param {string} endpointA - "start" or "end"
 * @param {string} endpointB - "start" or "end"
 * @param {boolean} preserveHandles - if true, keep original handles at junction
 * @returns {Array} merged [{anchor, left, right}...]
 */
function weldPoints(ptsA, ptsB, endpointA, endpointB, preserveHandles) {
    // Orient both paths so junction is at the meeting point
    var a = ptsA.slice(0);
    var b = ptsB.slice(0);

    if (endpointA === "start") {
        a.reverse();
        // Reversing path direction swaps left/right handle semantics
        for (var ri = 0; ri < a.length; ri++) {
            var tmp = a[ri].left;
            a[ri].left = a[ri].right;
            a[ri].right = tmp;
        }
    }
    if (endpointB === "end") {
        b.reverse();
        for (var rj = 0; rj < b.length; rj++) {
            var tmp2 = b[rj].left;
            b[rj].left = b[rj].right;
            b[rj].right = tmp2;
        }
    }

    // Junction: last of a meets first of b
    var juncA = a[a.length - 1];
    var juncB = b[0];

    var merged;
    if (preserveHandles) {
        // GIR mode: keep A's anchor position, A's left handle, B's right handle
        merged = {
            anchor: [juncA.anchor[0], juncA.anchor[1]],
            left: [juncA.left[0], juncA.left[1]],
            right: [juncB.right[0], juncB.right[1]]
        };
    } else {
        // Average anchor position; preserve A's incoming handle and B's outgoing handle
        // for tangent continuity at the junction
        merged = {
            anchor: [
                (juncA.anchor[0] + juncB.anchor[0]) / 2,
                (juncA.anchor[1] + juncB.anchor[1]) / 2
            ],
            left: [juncA.left[0], juncA.left[1]],     // A's incoming
            right: [juncB.right[0], juncB.right[1]]    // B's outgoing
        };
    }

    // Build combined path: a[0..n-2] + merged_junction + b[1..end]
    var result = [];
    for (var i = 0; i < a.length - 1; i++) {
        result.push({
            anchor: a[i].anchor.slice(0),
            left: a[i].left.slice(0),
            right: a[i].right.slice(0)
        });
    }
    result.push(merged);
    for (var j = 1; j < b.length; j++) {
        result.push({
            anchor: b[j].anchor.slice(0),
            left: b[j].left.slice(0),
            right: b[j].right.slice(0)
        });
    }

    return result;
}
