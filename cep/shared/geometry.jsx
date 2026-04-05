/**
 * geometry.jsx — Geometric analysis for ExtendScript (ES3).
 *
 * Requires: math2d.jsx (must be #included first)
 *
 * PCA sorting, minimum-area bounding rectangles, Douglas-Peucker
 * simplification, and LOD precomputation.
 */

/**
 * Sort points by their projection onto the first principal component.
 * This orders scattered anchors along their dominant direction.
 *
 * @param {Array} pts - array of [x, y]
 * @returns {Array} sorted copy of pts
 */
function sortByPCA(pts) {
    if (pts.length < 2) return pts.slice(0);

    // Compute centroid
    var cx = 0, cy = 0;
    for (var i = 0; i < pts.length; i++) {
        cx += pts[i][0];
        cy += pts[i][1];
    }
    cx /= pts.length;
    cy /= pts.length;

    // Covariance matrix [cxx, cxy; cxy, cyy]
    var cxx = 0, cxy = 0, cyy = 0;
    for (var j = 0; j < pts.length; j++) {
        var dx = pts[j][0] - cx;
        var dy = pts[j][1] - cy;
        cxx += dx * dx;
        cxy += dx * dy;
        cyy += dy * dy;
    }

    // First eigenvector via analytic 2x2 solution
    var trace = cxx + cyy;
    var det = cxx * cyy - cxy * cxy;
    var eigenvalue = trace / 2 + Math.sqrt(Math.max(0, trace * trace / 4 - det));

    var vx, vy;
    if (Math.abs(cxy) > 1e-10) {
        vx = eigenvalue - cyy;
        vy = cxy;
    } else if (cxx >= cyy) {
        vx = 1;
        vy = 0;
    } else {
        vx = 0;
        vy = 1;
    }

    // Normalize
    var vlen = Math.sqrt(vx * vx + vy * vy);
    if (vlen > 1e-12) {
        vx /= vlen;
        vy /= vlen;
    }

    // Project each point and sort by projection value
    var indexed = [];
    for (var k = 0; k < pts.length; k++) {
        var proj = (pts[k][0] - cx) * vx + (pts[k][1] - cy) * vy;
        indexed.push({ idx: k, proj: proj });
    }
    indexed.sort(function (a, b) { return a.proj - b.proj; });

    var sorted = [];
    for (var m = 0; m < indexed.length; m++) {
        sorted.push(pts[indexed[m].idx].slice(0));
    }
    return sorted;
}

/**
 * Douglas-Peucker polyline simplification.
 *
 * @param {Array} pts - array of [x, y]
 * @param {number} epsilon - max perpendicular distance tolerance
 * @returns {Array} simplified array of [x, y]
 */
function douglasPeucker(pts, epsilon) {
    if (pts.length < 3) return pts.slice(0);

    // Find the point with the max distance from the line start-end
    var maxDist = 0;
    var maxIdx = 0;
    var first = pts[0];
    var last = pts[pts.length - 1];

    for (var i = 1; i < pts.length - 1; i++) {
        var d = pointToSegmentDist(pts[i], first, last);
        if (d > maxDist) {
            maxDist = d;
            maxIdx = i;
        }
    }

    if (maxDist > epsilon) {
        // Recurse on both halves
        var left = [];
        for (var a = 0; a <= maxIdx; a++) left.push(pts[a]);
        var right = [];
        for (var b = maxIdx; b < pts.length; b++) right.push(pts[b]);

        var recLeft = douglasPeucker(left, epsilon);
        var recRight = douglasPeucker(right, epsilon);

        // Combine (remove duplicate at junction)
        var result = [];
        for (var c = 0; c < recLeft.length - 1; c++) result.push(recLeft[c]);
        for (var d2 = 0; d2 < recRight.length; d2++) result.push(recRight[d2]);
        return result;
    } else {
        return [first.slice(0), last.slice(0)];
    }
}

/**
 * Find inflection points where curvature sign changes.
 * Returns an array of indices into pts where cross-product sign flips.
 *
 * @param {Array} pts - array of [x, y]
 * @returns {Array} indices of inflection points (always includes first and last)
 */
function _findInflectionIndices(pts) {
    var result = [0]; // always keep first point
    if (pts.length < 3) {
        if (pts.length > 1) result.push(pts.length - 1);
        return result;
    }

    var prevSign = 0;
    for (var i = 1; i < pts.length - 1; i++) {
        var v1x = pts[i][0] - pts[i - 1][0];
        var v1y = pts[i][1] - pts[i - 1][1];
        var v2x = pts[i + 1][0] - pts[i][0];
        var v2y = pts[i + 1][1] - pts[i][1];
        var cp = v1x * v2y - v1y * v2x;
        var sign = cp > 0 ? 1 : (cp < 0 ? -1 : 0);
        if (sign !== 0 && prevSign !== 0 && sign !== prevSign) {
            result.push(i);
        }
        if (sign !== 0) prevSign = sign;
    }

    result.push(pts.length - 1); // always keep last point
    return result;
}

/**
 * Merge inflection points into a simplified point set.
 * Any inflection point not already present in simplified is inserted
 * at the correct position based on its index in the original array.
 *
 * @param {Array} simplified - array of [x, y] from Douglas-Peucker
 * @param {Array} allPts - original full point array
 * @param {Array} inflectionIndices - indices into allPts of inflection points
 * @returns {Array} merged point array with inflection points preserved
 */
function _mergeInflectionPoints(simplified, allPts, inflectionIndices) {
    if (!inflectionIndices || inflectionIndices.length === 0) return simplified;

    // Build a set of points already in simplified (by coordinate match)
    var EPSILON = 1e-6;
    var merged = simplified.slice(0);

    for (var ii = 0; ii < inflectionIndices.length; ii++) {
        var idx = inflectionIndices[ii];
        var ip = allPts[idx];

        // Check if this inflection point is already in merged
        var found = false;
        for (var m = 0; m < merged.length; m++) {
            var dx = merged[m][0] - ip[0];
            var dy = merged[m][1] - ip[1];
            if (dx * dx + dy * dy < EPSILON) {
                found = true;
                break;
            }
        }

        if (!found) {
            // Insert at correct position: find where it belongs by closest neighbor
            var bestInsert = merged.length; // default: append
            var bestDist = Infinity;
            for (var s = 0; s < merged.length - 1; s++) {
                // Check if ip falls between merged[s] and merged[s+1]
                var d = pointToSegmentDist(ip, merged[s], merged[s + 1]);
                if (d < bestDist) {
                    bestDist = d;
                    bestInsert = s + 1;
                }
            }
            merged.splice(bestInsert, 0, ip.slice(0));
        }
    }

    return merged;
}

/**
 * Precompute LOD levels for a point array.
 * Runs Douglas-Peucker at exponentially spaced epsilon values.
 *
 * When surfaceHint is provided, the simplification becomes surface-aware:
 * - Low levels (0-30%): Douglas-Peucker as before
 * - Medium levels (30-70%): Douglas-Peucker with mandatory inflection point preservation
 * - High levels (70-100%): Blend toward the mathematically ideal primitive fit
 * At level 100% with a surface hint, you always get the minimal geometric primitive.
 *
 * @param {Array} pts - array of [x, y]
 * @param {number} numLevels - number of LOD levels to compute
 * @param {string} surfaceHint - optional: "flat", "cylindrical", "convex", "concave", "saddle", "angular"
 * @returns {Array} [{value: 0..100, points: [...], count: N}, ...]
 */
function precomputeLOD(pts, numLevels, surfaceHint) {
    if (!numLevels) numLevels = 20;
    var levels = [];

    // Compute bounding diagonal for epsilon scaling
    var minX = pts[0][0], maxX = pts[0][0];
    var minY = pts[0][1], maxY = pts[0][1];
    for (var i = 1; i < pts.length; i++) {
        if (pts[i][0] < minX) minX = pts[i][0];
        if (pts[i][0] > maxX) maxX = pts[i][0];
        if (pts[i][1] < minY) minY = pts[i][1];
        if (pts[i][1] > maxY) maxY = pts[i][1];
    }
    var diag = Math.sqrt((maxX - minX) * (maxX - minX) + (maxY - minY) * (maxY - minY));
    if (diag < 1) diag = 1;

    // Level 0 = no simplification
    levels.push({ value: 0, points: pts.slice(0), count: pts.length });

    // Precompute the primitive fit for this surface type (only if hint provided)
    var primitiveFit = null;
    if (surfaceHint) {
        if (surfaceHint === "flat") {
            primitiveFit = fitToShape(pts, "line");
        } else if (surfaceHint === "cylindrical" || surfaceHint === "convex" || surfaceHint === "concave") {
            // Try both arc and ellipse, pick best confidence
            var arcFit = fitToShape(pts, "arc");
            var ellFit = fitToShape(pts, "ellipse");
            primitiveFit = arcFit.confidence > ellFit.confidence ? arcFit : ellFit;
        } else if (surfaceHint === "saddle") {
            primitiveFit = fitToShape(pts, "scurve");
        } else if (surfaceHint === "angular") {
            primitiveFit = fitToShape(pts, "lshape");
        } else if (surfaceHint === "rectangular") {
            primitiveFit = fitToShape(pts, "rectangle");
        }
    }

    // Precompute inflection indices for medium-level preservation
    var inflectionIndices = _findInflectionIndices(pts);

    for (var lv = 1; lv <= numLevels; lv++) {
        var t = lv / numLevels; // 0..1
        var sliderValue = Math.round(t * 100);

        if (t < 0.3 || !primitiveFit) {
            // Low simplification (or no surface hint): pure Douglas-Peucker
            var epsilon = diag * 0.001 * Math.pow(100, t);
            var simplified = douglasPeucker(pts, epsilon);
            levels.push({ value: sliderValue, points: simplified, count: simplified.length });

        } else if (t < 0.7) {
            // Medium simplification: Douglas-Peucker with mandatory inflection points
            var epsilon2 = diag * 0.001 * Math.pow(100, t);
            var dpResult = douglasPeucker(pts, epsilon2);
            var withInflections = _mergeInflectionPoints(dpResult, pts, inflectionIndices);
            levels.push({ value: sliderValue, points: withInflections, count: withInflections.length });

        } else {
            // High simplification: blend toward primitive fit
            // blendT goes from 0.0 at 70% to 1.0 at 100%
            var blendT = (t - 0.7) / 0.3;

            if (blendT >= 0.95) {
                // Pure primitive — the mathematically ideal shape
                levels.push({
                    value: sliderValue,
                    points: primitiveFit.points,
                    count: primitiveFit.points.length,
                    shape: primitiveFit.shape,
                    handles: primitiveFit.handles || null,
                    closed: primitiveFit.closed || false
                });
            } else {
                // Transitional: increasingly aggressive DP, still preserving endpoints
                var epsilon3 = diag * 0.001 * Math.pow(100, t);
                var dpHigh = douglasPeucker(pts, epsilon3);
                levels.push({ value: sliderValue, points: dpHigh, count: dpHigh.length });
            }
        }
    }

    return levels;
}

/**
 * Minimum-area bounding rectangle using rotating calipers on convex hull.
 *
 * @param {Array} pts - array of [x, y]
 * @returns {Object} {center: [x,y], width: N, height: N, angle: degrees}
 */
function minAreaRect(pts) {
    if (pts.length < 2) {
        return { center: pts[0] || [0, 0], width: 0, height: 0, angle: 0 };
    }
    if (pts.length === 2) {
        var mx = (pts[0][0] + pts[1][0]) / 2;
        var my = (pts[0][1] + pts[1][1]) / 2;
        var d = dist2d(pts[0], pts[1]);
        var ang = Math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]) * 180 / Math.PI;
        return { center: [mx, my], width: d, height: 0, angle: ang };
    }

    // Convex hull (Graham scan)
    var hull = convexHull2d(pts);

    // Rotating calipers to find minimum-area bounding rectangle
    var bestArea = Infinity;
    var bestRect = null;

    for (var i = 0; i < hull.length; i++) {
        var i2 = (i + 1) % hull.length;
        // Edge direction
        var edgeDir = normalize2d(sub2d(hull[i2], hull[i]));
        var edgePerp = [-edgeDir[1], edgeDir[0]];

        // Project all hull points onto edge direction and perpendicular
        var minProj = Infinity, maxProj = -Infinity;
        var minPerp = Infinity, maxPerp = -Infinity;

        for (var j = 0; j < hull.length; j++) {
            var v = sub2d(hull[j], hull[i]);
            var proj = dot2d(v, edgeDir);
            var perp = dot2d(v, edgePerp);
            if (proj < minProj) minProj = proj;
            if (proj > maxProj) maxProj = proj;
            if (perp < minPerp) minPerp = perp;
            if (perp > maxPerp) maxPerp = perp;
        }

        var w = maxProj - minProj;
        var h = maxPerp - minPerp;
        var area = w * h;

        if (area < bestArea) {
            bestArea = area;
            var midProj = (minProj + maxProj) / 2;
            var midPerp = (minPerp + maxPerp) / 2;
            var rcx = hull[i][0] + edgeDir[0] * midProj + edgePerp[0] * midPerp;
            var rcy = hull[i][1] + edgeDir[1] * midProj + edgePerp[1] * midPerp;
            var angle = Math.atan2(edgeDir[1], edgeDir[0]) * 180 / Math.PI;
            bestRect = { center: [rcx, rcy], width: w, height: h, angle: angle };
        }
    }

    return bestRect || { center: centroid2d(pts), width: 0, height: 0, angle: 0 };
}

/**
 * Convex hull via Graham scan. Returns hull points in CCW order.
 * @param {Array} pts - array of [x, y]
 * @returns {Array} hull points
 */
function convexHull2d(pts) {
    if (pts.length < 3) return pts.slice(0);

    // Find lowest-leftmost point
    var pivot = 0;
    for (var i = 1; i < pts.length; i++) {
        if (pts[i][1] < pts[pivot][1] ||
            (pts[i][1] === pts[pivot][1] && pts[i][0] < pts[pivot][0])) {
            pivot = i;
        }
    }

    // Sort by polar angle from pivot
    var p0 = pts[pivot];
    var indices = [];
    for (var j = 0; j < pts.length; j++) {
        if (j !== pivot) indices.push(j);
    }
    indices.sort(function (a, b) {
        var angA = Math.atan2(pts[a][1] - p0[1], pts[a][0] - p0[0]);
        var angB = Math.atan2(pts[b][1] - p0[1], pts[b][0] - p0[0]);
        if (angA !== angB) return angA - angB;
        return dist2d(p0, pts[a]) - dist2d(p0, pts[b]);
    });

    var stack = [p0];
    for (var k = 0; k < indices.length; k++) {
        var pt = pts[indices[k]];
        while (stack.length > 1) {
            var top = stack[stack.length - 1];
            var below = stack[stack.length - 2];
            var crossVal = cross2d(sub2d(top, below), sub2d(pt, below));
            if (crossVal <= 0) {
                stack.pop();
            } else {
                break;
            }
        }
        stack.push(pt);
    }

    return stack;
}
