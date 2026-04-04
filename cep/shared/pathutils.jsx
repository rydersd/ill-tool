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
