/**
 * ui.jsx — Preview, layer management, and visual helpers for ExtendScript (ES3).
 *
 * Requires: math2d.jsx, pathutils.jsx (must be #included first)
 *
 * Manages preview paths, bounding box guides, layer creation, and
 * confirmation/undo workflows.
 */

/**
 * Get or create a layer by name.
 *
 * @param {string} name - layer name
 * @returns {Layer}
 */
function ensureLayer(name) {
    var doc = app.activeDocument;
    var lyr;
    try {
        lyr = doc.layers.getByName(name);
    } catch (e) {
        lyr = doc.layers.add();
        lyr.name = name;
    }
    return lyr;
}

/**
 * Place a preview path on a named layer.
 * Removes any existing preview (named "__preview__") first.
 * Draws a dashed dark-orange stroke for visibility.
 *
 * If explicit handles are provided, uses createPathWithHandles() for
 * precise bezier control. Otherwise falls back to auto-computed
 * Catmull-Rom handles via createPath().
 *
 * @param {Array} points - array of [x, y]
 * @param {boolean} closed - whether to close the path
 * @param {string} layerName - target layer name
 * @param {Array} handles - optional array of {left:[x,y], right:[x,y]} parallel to points
 * @returns {PathItem} the created preview path
 */
function placePreview(points, closed, layerName, handles) {
    var lyr = ensureLayer(layerName);

    // Remove existing preview
    try {
        lyr.pathItems.getByName("__preview__").remove();
    } catch (e) {
        // No existing preview
    }

    var path;
    if (handles && handles.length === points.length) {
        // Use explicit handles from shape fitters
        var pointData = [];
        for (var i = 0; i < points.length; i++) {
            pointData.push({
                anchor: points[i],
                left: handles[i].left,
                right: handles[i].right
            });
        }
        path = createPathWithHandles(lyr, pointData, {
            name: "__preview__",
            closed: closed,
            stroked: true,
            strokeColor: [200, 100, 30],
            strokeWidth: 1.5,
            strokeDashes: [4, 4]
        });
    } else {
        // Original: auto-compute Catmull-Rom handles
        path = createPath(lyr, points, {
            name: "__preview__",
            closed: closed,
            stroked: true,
            strokeColor: [200, 100, 30],
            strokeWidth: 1.5,
            strokeDashes: [4, 4],
            computeHandles: true,
            tension: 1 / 6
        });
    }

    app.redraw();
    return path;
}

/**
 * Confirm a preview path: rename, solidify stroke, remove dashes.
 *
 * @param {string} layerName - layer containing the preview
 * @returns {string|null} the new path name, or null on failure
 */
function confirmPreview(layerName) {
    try {
        var lyr = app.activeDocument.layers.getByName(layerName);
        var preview = lyr.pathItems.getByName("__preview__");

        // Rename with timestamp
        var newName = "avg_" + new Date().getTime();
        preview.name = newName;

        // Solid dark stroke
        preview.strokeDashes = [];
        var clr = new RGBColor();
        clr.red = 30;
        clr.green = 30;
        clr.blue = 30;
        preview.strokeColor = clr;
        preview.opacity = 70;

        app.redraw();
        return newName;
    } catch (e) {
        return null;
    }
}

/**
 * Remove the preview path without confirming.
 *
 * @param {string} layerName - layer containing the preview
 */
function undoPreview(layerName) {
    try {
        app.activeDocument.layers.getByName(layerName)
            .pathItems.getByName("__preview__").remove();
        app.redraw();
    } catch (e) {
        // No preview to remove
    }
}

/**
 * Draw a rotated bounding box guide on a named layer.
 * Named "__bbox_guide__" so it can be replaced on subsequent calls.
 *
 * @param {number} cx - center X
 * @param {number} cy - center Y
 * @param {number} w - width (before padding)
 * @param {number} h - height (before padding)
 * @param {number} angle - rotation in degrees
 * @param {number} padding - extra padding around box
 * @returns {PathItem}
 */
function drawBoundingBox(cx, cy, w, h, angle, padding, layerName) {
    var lyr = ensureLayer(layerName || "Cleaned Forms");

    // Remove existing
    try {
        lyr.pathItems.getByName("__bbox_guide__").remove();
    } catch (e) {}

    var pw = w + padding * 2;
    var ph = h + padding * 2;
    var hw = pw / 2;
    var hh = ph / 2;
    var rad = angle * Math.PI / 180;
    var cosA = Math.cos(rad);
    var sinA = Math.sin(rad);

    var offsets = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
    var corners = [];
    for (var i = 0; i < 4; i++) {
        corners.push([
            cx + offsets[i][0] * cosA - offsets[i][1] * sinA,
            cy + offsets[i][0] * sinA + offsets[i][1] * cosA
        ]);
    }

    var bbox = lyr.pathItems.add();
    bbox.name = "__bbox_guide__";
    bbox.filled = false;
    bbox.stroked = true;

    var clr = new RGBColor();
    clr.red = 30;
    clr.green = 60;
    clr.blue = 180;
    bbox.strokeColor = clr;
    bbox.strokeWidth = 0.5;
    bbox.strokeDashes = [6, 3];
    bbox.closed = true;

    for (var j = 0; j < 4; j++) {
        var pp = bbox.pathPoints.add();
        pp.anchor = corners[j];
        pp.leftDirection = corners[j];
        pp.rightDirection = corners[j];
        pp.pointType = PointType.CORNER;
    }

    app.redraw();
    return bbox;
}

/**
 * Remove the bounding box guide.
 */
function removeBoundingBox(layerName) {
    try {
        var doc = app.activeDocument;
        // Check specified layer, or both possible layers as fallback
        var layerNames = layerName ? [layerName] : ["Cleaned Forms", "Refined Forms"];
        for (var i = 0; i < layerNames.length; i++) {
            try {
                var lyr = doc.layers.getByName(layerNames[i]);
                lyr.pathItems.getByName("__bbox_guide__").remove();
            } catch (e2) {}
        }
        app.redraw();
    } catch (e) {}
}
