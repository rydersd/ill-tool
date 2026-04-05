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
            strokeDashes: []
        });
    } else {
        // Original: auto-compute Catmull-Rom handles
        path = createPath(lyr, points, {
            name: "__preview__",
            closed: closed,
            stroked: true,
            strokeColor: [200, 100, 30],
            strokeWidth: 1.5,
            strokeDashes: [],
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
        preview.opacity = 100;

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

    var bboxClr = new RGBColor();
    bboxClr.red = 30;
    bboxClr.green = 100;
    bboxClr.blue = 220;

    // Draw bbox outline
    var bbox = lyr.pathItems.add();
    bbox.name = "__bbox_guide__";
    bbox.filled = false;
    bbox.stroked = true;
    bbox.strokeColor = bboxClr;
    bbox.strokeWidth = 1.0;
    bbox.strokeDashes = [];
    bbox.closed = true;

    for (var j = 0; j < 4; j++) {
        var pp = bbox.pathPoints.add();
        pp.anchor = corners[j];
        pp.leftDirection = corners[j];
        pp.rightDirection = corners[j];
        pp.pointType = PointType.CORNER;
    }

    // Draw visible corner handles (filled blue circles, 2x normal anchor size)
    // These are separate paths so they're visually distinct from shape anchors
    var handleSize = 4; // radius in points (normal anchor is ~2pt)
    for (var k = 0; k < 4; k++) {
        var handle = lyr.pathItems.ellipse(
            corners[k][1] + handleSize,  // top (AI Y = up)
            corners[k][0] - handleSize,  // left
            handleSize * 2,               // width
            handleSize * 2,               // height
            false, true                   // not reversed, inscribed
        );
        handle.name = "__bbox_handle_" + k + "__";
        handle.filled = true;
        handle.fillColor = bboxClr;
        handle.stroked = true;
        var handleStroke = new RGBColor();
        handleStroke.red = 255;
        handleStroke.green = 255;
        handleStroke.blue = 255;
        handle.strokeColor = handleStroke;
        handle.strokeWidth = 0.5;
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
        var layerNames = layerName ? [layerName] : ["Cleaned Forms", "Refined Forms"];
        for (var i = 0; i < layerNames.length; i++) {
            try {
                var lyr = doc.layers.getByName(layerNames[i]);
                // Remove bbox outline
                try { lyr.pathItems.getByName("__bbox_guide__").remove(); } catch (e3) {}
                // Remove corner handle circles
                for (var h = 0; h < 4; h++) {
                    try { lyr.pathItems.getByName("__bbox_handle_" + h + "__").remove(); } catch (e4) {}
                }
            } catch (e2) {}
        }
        app.redraw();
    } catch (e) {}
}

/**
 * Polygon lasso selection — select all path points inside a polygon.
 *
 * Click points to define polygon edges, double-click to close.
 * Selects anchor points of all pathItems on visible, unlocked layers
 * that fall inside the polygon.
 *
 * @param {string} polygonJson - JSON array of [x, y] polygon vertices (AI coordinates)
 * @param {boolean} [addToSelection] - if true, adds to existing selection; if false, replaces
 * @returns {string} pipe-delimited: "selected|anchorCount|pathCount" or "error|message"
 */
function polygonLassoSelect(polygonJson, addToSelection) {
    try {
        var polygon = jsonParse(polygonJson);
        if (!polygon || polygon.length < 3) return "error|Need at least 3 points";

        var doc = app.activeDocument;

        // Clear selection unless adding
        if (!addToSelection) {
            doc.selection = null;
        }

        var selectedAnchors = 0;
        var selectedPaths = 0;

        // Iterate all visible, unlocked layers
        for (var li = 0; li < doc.layers.length; li++) {
            var lyr = doc.layers[li];
            if (!lyr.visible || lyr.locked) continue;

            // Check all pathItems on this layer
            for (var pi = 0; pi < lyr.pathItems.length; pi++) {
                var path = lyr.pathItems[pi];
                if (path.hidden || path.locked) continue;
                // Skip guide/bbox items
                var pname = path.name;
                if (pname.indexOf("__") === 0) continue;

                var pathHit = false;
                for (var ai = 0; ai < path.pathPoints.length; ai++) {
                    var anchor = path.pathPoints[ai].anchor;
                    if (pointInPolygon(anchor, polygon)) {
                        path.pathPoints[ai].selected = PathPointSelection.ANCHORPOINT;
                        selectedAnchors++;
                        pathHit = true;
                    }
                }
                if (pathHit) selectedPaths++;
            }

            // Also check grouped items (one level deep)
            for (var gi = 0; gi < lyr.groupItems.length; gi++) {
                var grp = lyr.groupItems[gi];
                if (grp.hidden || grp.locked) continue;

                for (var gpi = 0; gpi < grp.pathItems.length; gpi++) {
                    var gpath = grp.pathItems[gpi];
                    if (gpath.hidden || gpath.locked) continue;
                    var gpname = gpath.name;
                    if (gpname.indexOf("__") === 0) continue;

                    var gpathHit = false;
                    for (var gai = 0; gai < gpath.pathPoints.length; gai++) {
                        var ganchor = gpath.pathPoints[gai].anchor;
                        if (pointInPolygon(ganchor, polygon)) {
                            gpath.pathPoints[gai].selected = PathPointSelection.ANCHORPOINT;
                            selectedAnchors++;
                            gpathHit = true;
                        }
                    }
                    if (gpathHit) selectedPaths++;
                }
            }
        }

        app.redraw();
        return "selected|" + selectedAnchors + "|" + selectedPaths;
    } catch (e) {
        return "error|" + e.message;
    }
}

/**
 * Initialize working state for a layer of extracted paths.
 *
 * 1. Groups all items on the source layer into a named group
 * 2. Duplicates the group
 * 3. Tags the original with "(og)", locks it, hides it
 * 4. The duplicate becomes the active working copy
 *
 * @param {string} layerName - layer containing the extracted paths
 * @param {string} [groupName] - optional name for the group (defaults to layerName)
 * @returns {string} pipe-delimited: "ok|itemCount|groupName" or "error|message"
 */
function initializeWorkingState(layerName, groupName) {
    try {
        var doc = app.activeDocument;
        var lyr = doc.layers.getByName(layerName);

        if (lyr.pageItems.length === 0) return "error|Layer is empty";

        if (!groupName) groupName = layerName;

        // 1. Group all items on the layer
        var workGroup = lyr.groupItems.add();
        workGroup.name = groupName;

        // Move all items into the group (iterate backwards)
        var itemCount = 0;
        while (lyr.pageItems.length > 1) { // >1 because the group itself is a pageItem
            var item = null;
            // Find first item that isn't our group
            for (var i = 0; i < lyr.pageItems.length; i++) {
                if (lyr.pageItems[i] !== workGroup) {
                    item = lyr.pageItems[i];
                    break;
                }
            }
            if (!item) break;
            item.move(workGroup, ElementPlacement.PLACEATEND);
            itemCount++;
        }

        // 2. Duplicate the group (stays on same layer)
        var ogGroup = workGroup.duplicate();

        // 3. Tag original as (og), lock, hide
        ogGroup.name = groupName + " (og)";
        ogGroup.locked = true;
        ogGroup.hidden = true;

        // 4. Working copy stays visible and active
        // Select the working group
        doc.selection = null;
        workGroup.selected = true;

        app.redraw();
        return "ok|" + itemCount + "|" + groupName;
    } catch (e) {
        return "error|" + e.message;
    }
}
