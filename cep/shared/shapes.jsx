/**
 * shapes.jsx — Shape classification and fitting for ExtendScript (ES3).
 *
 * Requires: math2d.jsx, geometry.jsx (must be #included first)
 *
 * Classifies sorted point arrays into geometric primitives (line, arc,
 * L-shape, rectangle, S-curve, ellipse, freeform) and can re-fit points
 * to a specified shape type.
 */

/**
 * Classify a sorted point array into a shape type.
 *
 * @param {Array} sortedPoints - PCA-sorted array of [x, y]
 * @param {string} surfaceHint - optional surface type: "flat", "cylindrical", "convex", "concave", "saddle"
 * @returns {Object} {shape: string, points: [[x,y],...], closed: boolean, confidence: number, handles: Array|undefined}
 */
function classifyShape(sortedPoints, surfaceHint) {
    if (!sortedPoints || sortedPoints.length < 2) {
        return { shape: "freeform", points: sortedPoints || [], closed: false, confidence: 0 };
    }

    var pts = sortedPoints;

    // Test each shape type, pick highest confidence
    var candidates = [
        _testLine(pts),
        _testArc(pts),
        _testLShape(pts),
        _testRectangle(pts),
        _testSCurve(pts),
        _testEllipse(pts)
    ];

    var best = { shape: "freeform", points: pts.slice(0), closed: false, confidence: 0.1 };
    for (var i = 0; i < candidates.length; i++) {
        if (candidates[i].confidence > best.confidence) {
            best = candidates[i];
        }
    }

    // Apply surface hint bonus if provided
    if (surfaceHint && best.shape !== "freeform") {
        var hintMapping = {
            "flat": "line",
            "cylindrical": "arc",
            "convex": "arc",
            "concave": "arc",
            "saddle": "scurve"
        };
        var suggestedShape = hintMapping[surfaceHint];
        if (suggestedShape && best.shape === suggestedShape) {
            best.confidence = Math.min(1.0, best.confidence + 0.15);
        }
        // Also boost the suggested shape in the candidate list if it scores higher
        for (var h = 0; h < candidates.length; h++) {
            if (candidates[h].shape === suggestedShape && candidates[h].confidence > best.confidence) {
                best = candidates[h];
                best.confidence = Math.min(1.0, best.confidence + 0.15);
                break;
            }
        }
    }

    return best;
}

/**
 * Force-fit points to a specified shape type.
 *
 * @param {Array} pts - sorted array of [x, y]
 * @param {string} shapeType - one of: line, arc, lshape, rectangle, scurve, ellipse, freeform
 * @returns {Object} {shape: string, points: [[x,y],...], closed: boolean, confidence: number}
 */
function fitToShape(pts, shapeType) {
    if (!pts || pts.length < 2) {
        return { shape: shapeType, points: pts || [], closed: false, confidence: 0 };
    }

    switch (shapeType) {
        case "line":      return _fitLine(pts);
        case "arc":       return _fitArc(pts);
        case "lshape":    return _fitLShape(pts);
        case "rectangle": return _fitRectangle(pts);
        case "scurve":    return _fitSCurve(pts);
        case "ellipse":   return _fitEllipse(pts);
        default:          return { shape: "freeform", points: pts.slice(0), closed: false, confidence: 0.5 };
    }
}

// ── Shape Tests (classify) ───────────────────────────────────────

function _testLine(pts) {
    var first = pts[0];
    var last = pts[pts.length - 1];
    var totalDev = 0;

    for (var i = 1; i < pts.length - 1; i++) {
        totalDev += pointToSegmentDist(pts[i], first, last);
    }

    var span = dist2d(first, last);
    if (span < 1e-6) return { shape: "line", points: [first, last], closed: false, confidence: 0 };

    var avgDev = pts.length > 2 ? totalDev / (pts.length - 2) : 0;
    var relDev = avgDev / span;
    var confidence = Math.max(0, 1 - relDev * 20);
    return _fitLine(pts, confidence);
}

function _testArc(pts) {
    var n = pts.length;
    if (n < 3) return { shape: "arc", points: pts.slice(0), closed: false, confidence: 0 };

    var p1 = pts[0];
    var p2 = pts[Math.floor(n / 2)];
    var p3 = pts[n - 1];
    var circle = _circumcircle(p1, p2, p3);

    if (!circle) return { shape: "arc", points: pts.slice(0), closed: false, confidence: 0 };

    var totalDev = 0;
    for (var i = 0; i < n; i++) {
        var r = dist2d(pts[i], circle.center);
        totalDev += Math.abs(r - circle.radius);
    }
    var avgDev = totalDev / n;
    var relDev = avgDev / circle.radius;

    var ang1 = Math.atan2(p1[1] - circle.center[1], p1[0] - circle.center[0]);
    var ang3 = Math.atan2(p3[1] - circle.center[1], p3[0] - circle.center[0]);
    var sweep = Math.abs(ang3 - ang1);
    if (sweep > Math.PI) sweep = 2 * Math.PI - sweep;

    var confidence = Math.max(0, (1 - relDev * 10) * (sweep < 5.5 ? 1 : 0.3));
    return _fitArc(pts, confidence);
}

function _testLShape(pts) {
    var n = pts.length;
    if (n < 3) return { shape: "lshape", points: pts.slice(0), closed: false, confidence: 0 };

    var first = pts[0];
    var last = pts[n - 1];
    var maxDist = 0;
    var cornerIdx = 0;

    for (var i = 1; i < n - 1; i++) {
        var d = pointToSegmentDist(pts[i], first, last);
        if (d > maxDist) {
            maxDist = d;
            cornerIdx = i;
        }
    }

    var span = dist2d(first, last);
    if (span < 1e-6) return { shape: "lshape", points: pts.slice(0), closed: false, confidence: 0 };

    var dev1 = 0, dev2 = 0;
    var corner = pts[cornerIdx];
    for (var a = 1; a < cornerIdx; a++) {
        dev1 += pointToSegmentDist(pts[a], first, corner);
    }
    for (var b = cornerIdx + 1; b < n - 1; b++) {
        dev2 += pointToSegmentDist(pts[b], corner, last);
    }

    var totalDev = (dev1 + dev2) / Math.max(1, n - 3);
    var relDev = totalDev / span;

    var v1 = normalize2d(sub2d(first, corner));
    var v2 = normalize2d(sub2d(last, corner));
    var dotVal = dot2d(v1, v2);
    var angleFactor = Math.max(0, 1 - Math.abs(dotVal));

    var confidence = Math.max(0, (1 - relDev * 15) * angleFactor);
    return _fitLShape(pts, confidence);
}

function _testRectangle(pts) {
    var n = pts.length;
    if (n < 4) return { shape: "rectangle", points: [], closed: true, confidence: 0 };

    var rect = minAreaRect(pts);
    var hw = rect.width / 2;
    var hh = rect.height / 2;
    var rad = rect.angle * Math.PI / 180;
    var corners = _rectCorners(rect.center[0], rect.center[1], hw, hh, rad);

    var totalDist = 0;
    for (var i = 0; i < n; i++) {
        var minDist = Infinity;
        for (var e = 0; e < 4; e++) {
            var e2 = (e + 1) % 4;
            var d = pointToSegmentDist(pts[i], corners[e], corners[e2]);
            if (d < minDist) minDist = d;
        }
        totalDist += minDist;
    }
    var avgDist = totalDist / n;
    var diagLen = Math.sqrt(rect.width * rect.width + rect.height * rect.height);
    if (diagLen < 1) diagLen = 1;
    var relDist = avgDist / diagLen;

    var aspectPenalty = 1;
    if (rect.width > 0 && rect.height > 0) {
        var aspect = Math.min(rect.width, rect.height) / Math.max(rect.width, rect.height);
        if (aspect < 0.05) aspectPenalty = 0.2;
    }

    var closureDist = dist2d(pts[0], pts[n - 1]);
    var closureFactor = closureDist < diagLen * 0.3 ? 1 : 0.3;

    var confidence = Math.max(0, (1 - relDist * 10) * aspectPenalty * closureFactor);
    return _fitRectangle(pts, confidence);
}

function _testSCurve(pts) {
    var n = pts.length;
    if (n < 4) return { shape: "scurve", points: pts.slice(0), closed: false, confidence: 0 };

    var signChanges = 0;
    var prevSign = 0;
    for (var i = 1; i < n - 1; i++) {
        var v1 = sub2d(pts[i], pts[i - 1]);
        var v2 = sub2d(pts[i + 1], pts[i]);
        var cp = cross2d(v1, v2);
        var sign = cp > 0 ? 1 : (cp < 0 ? -1 : 0);
        if (sign !== 0 && prevSign !== 0 && sign !== prevSign) {
            signChanges++;
        }
        if (sign !== 0) prevSign = sign;
    }

    var inflectionScore = signChanges >= 1 && signChanges <= 3 ? 1 : 0.3;
    var lineTest = _testLine(pts);
    var notLinePenalty = lineTest.confidence < 0.7 ? 1 : 0.3;

    var confidence = 0.6 * inflectionScore * notLinePenalty;
    return _fitSCurve(pts, confidence);
}

function _testEllipse(pts) {
    var n = pts.length;
    if (n < 5) return { shape: "ellipse", points: [], closed: true, confidence: 0 };

    var closureDist = dist2d(pts[0], pts[n - 1]);
    var c = centroid2d(pts);
    var avgRadius = 0;
    for (var i = 0; i < n; i++) {
        avgRadius += dist2d(pts[i], c);
    }
    avgRadius /= n;
    if (avgRadius < 1) avgRadius = 1;

    var closureFactor = closureDist < avgRadius * 0.5 ? 1 : 0.3;

    var totalDev = 0;
    for (var j = 0; j < n; j++) {
        totalDev += Math.abs(dist2d(pts[j], c) - avgRadius);
    }
    var relDev = (totalDev / n) / avgRadius;

    var confidence = Math.max(0, (1 - relDev * 5) * closureFactor);
    return _fitEllipse(pts, confidence);
}

// ── Shape Fitters ────────────────────────────────────────────────

function _fitLine(pts, confidence) {
    if (confidence === undefined) confidence = 0.5;
    return {
        shape: "line",
        points: [pts[0].slice(0), pts[pts.length - 1].slice(0)],
        closed: false,
        confidence: confidence
    };
}

function _fitArc(pts, confidence) {
    if (confidence === undefined) confidence = 0.5;
    var n = pts.length;
    var p1 = pts[0];
    var p2 = pts[Math.floor(n / 2)];
    var p3 = pts[n - 1];
    var circle = _circumcircle(p1, p2, p3);

    if (!circle) {
        return { shape: "arc", points: pts.slice(0), closed: false, confidence: confidence };
    }

    var cx = circle.center[0], cy = circle.center[1], r = circle.radius;

    // Compute angles for start, mid, end on the circle
    var ang1 = Math.atan2(p1[1] - cy, p1[0] - cx);
    var ang3 = Math.atan2(p3[1] - cy, p3[0] - cx);
    var sweep = ang3 - ang1;
    while (sweep > Math.PI) sweep -= 2 * Math.PI;
    while (sweep < -Math.PI) sweep += 2 * Math.PI;

    var angMid = ang1 + sweep * 0.5;

    // 3 output points: start, midpoint (apex), end — on the arc
    var arcPoints = [
        [cx + r * Math.cos(ang1), cy + r * Math.sin(ang1)],
        [cx + r * Math.cos(angMid), cy + r * Math.sin(angMid)],
        [cx + r * Math.cos(ang1 + sweep), cy + r * Math.sin(ang1 + sweep)]
    ];

    // Cubic bezier arc: 3 points = 2 segments, each spanning sweep/2.
    // Handle length per segment of angle theta: (4/3) * tan(theta/4) * radius
    var segAngle = Math.abs(sweep / 2);
    var hLen = (4.0 / 3.0) * Math.tan(segAngle / 4.0) * r;
    var sweepSign = (sweep >= 0) ? 1 : -1;

    // Tangent at angle theta perpendicular to radius
    var handles = [];
    var angles = [ang1, angMid, ang1 + sweep];
    for (var i = 0; i < 3; i++) {
        var theta = angles[i];
        var tx = -Math.sin(theta) * sweepSign;
        var ty = Math.cos(theta) * sweepSign;

        var pt = arcPoints[i];
        if (i === 0) {
            // First point: retract left (incoming) handle, extend right (outgoing)
            handles.push({
                left:  [pt[0], pt[1]],
                right: [pt[0] + tx * hLen, pt[1] + ty * hLen]
            });
        } else if (i === 2) {
            // Last point: extend left (incoming) handle, retract right (outgoing)
            handles.push({
                left:  [pt[0] - tx * hLen, pt[1] - ty * hLen],
                right: [pt[0], pt[1]]
            });
        } else {
            // Middle point: both handles
            handles.push({
                left:  [pt[0] - tx * hLen, pt[1] - ty * hLen],
                right: [pt[0] + tx * hLen, pt[1] + ty * hLen]
            });
        }
    }

    return {
        shape: "arc",
        points: arcPoints,
        handles: handles,
        closed: false,
        confidence: confidence
    };
}

function _fitLShape(pts, confidence) {
    if (confidence === undefined) confidence = 0.5;
    var n = pts.length;
    var first = pts[0];
    var last = pts[n - 1];
    var maxDist = 0;
    var cornerIdx = 0;
    for (var i = 1; i < n - 1; i++) {
        var d = pointToSegmentDist(pts[i], first, last);
        if (d > maxDist) {
            maxDist = d;
            cornerIdx = i;
        }
    }
    return {
        shape: "lshape",
        points: [first.slice(0), pts[cornerIdx].slice(0), last.slice(0)],
        closed: false,
        confidence: confidence
    };
}

function _fitRectangle(pts, confidence) {
    if (confidence === undefined) confidence = 0.5;
    var rect = minAreaRect(pts);
    var hw = rect.width / 2;
    var hh = rect.height / 2;
    var rad = rect.angle * Math.PI / 180;
    var corners = _rectCorners(rect.center[0], rect.center[1], hw, hh, rad);
    return {
        shape: "rectangle",
        points: corners,
        closed: true,
        confidence: confidence
    };
}

function _fitSCurve(pts, confidence) {
    if (confidence === undefined) confidence = 0.5;
    var n = pts.length;

    // Find the inflection point: where cross-product sign changes
    var inflIdx = Math.floor(n / 2); // fallback to midpoint
    var prevSign = 0;
    for (var i = 1; i < n - 1; i++) {
        var v1 = sub2d(pts[i], pts[i - 1]);
        var v2 = sub2d(pts[i + 1], pts[i]);
        var cp = cross2d(v1, v2);
        var sign = cp > 0 ? 1 : (cp < 0 ? -1 : 0);
        if (sign !== 0 && prevSign !== 0 && sign !== prevSign) {
            inflIdx = i;
            break;
        }
        if (sign !== 0) prevSign = sign;
    }

    // 3 output points: first, inflection, last
    var first = pts[0];
    var inflPt = pts[inflIdx];
    var last = pts[n - 1];
    var scurvePoints = [first.slice(0), inflPt.slice(0), last.slice(0)];

    // Catmull-Rom tangent handles at each point: handle = (next - prev) * tension
    var tension = 1.0 / 6.0;
    var handles = [];

    // Start point: tangent from first toward inflection
    var t0x = (inflPt[0] - first[0]) * tension;
    var t0y = (inflPt[1] - first[1]) * tension;
    handles.push({
        left:  [first[0] - t0x, first[1] - t0y],
        right: [first[0] + t0x, first[1] + t0y]
    });

    // Inflection point: tangent from first toward last
    var t1x = (last[0] - first[0]) * tension;
    var t1y = (last[1] - first[1]) * tension;
    handles.push({
        left:  [inflPt[0] - t1x, inflPt[1] - t1y],
        right: [inflPt[0] + t1x, inflPt[1] + t1y]
    });

    // End point: tangent from inflection toward last
    var t2x = (last[0] - inflPt[0]) * tension;
    var t2y = (last[1] - inflPt[1]) * tension;
    handles.push({
        left:  [last[0] - t2x, last[1] - t2y],
        right: [last[0] + t2x, last[1] + t2y]
    });

    return {
        shape: "scurve",
        points: scurvePoints,
        handles: handles,
        closed: false,
        confidence: confidence
    };
}

function _fitEllipse(pts, confidence) {
    if (confidence === undefined) confidence = 0.5;
    var c = centroid2d(pts);
    var n = pts.length;

    var cxx = 0, cxy = 0, cyy = 0;
    for (var i = 0; i < n; i++) {
        var dx = pts[i][0] - c[0];
        var dy = pts[i][1] - c[1];
        cxx += dx * dx;
        cxy += dx * dy;
        cyy += dy * dy;
    }
    cxx /= n; cxy /= n; cyy /= n;

    var trace = cxx + cyy;
    var det = cxx * cyy - cxy * cxy;
    var discrim = Math.max(0, trace * trace / 4 - det);
    var ev1 = trace / 2 + Math.sqrt(discrim);
    var ev2 = trace / 2 - Math.sqrt(discrim);

    // For points on ellipse perimeter: variance = semi_axis^2 / 2
    // So semi_axis = sqrt(2 * eigenvalue)
    var a = Math.sqrt(Math.max(0, 2 * ev1));  // semi-major axis
    var b = Math.sqrt(Math.max(0, 2 * ev2));  // semi-minor axis

    var angle;
    if (Math.abs(cxy) > 1e-10) {
        angle = Math.atan2(ev1 - cxx, cxy);
    } else {
        angle = cxx >= cyy ? 0 : Math.PI / 2;
    }

    var cosA = Math.cos(angle);
    var sinA = Math.sin(angle);

    // Kappa constant for bezier circle approximation
    var k = (4.0 / 3.0) * (Math.sqrt(2) - 1);  // ~0.5523

    // 4 cardinal points at 0, 90, 180, 270 degrees in the ellipse's rotated frame
    var cardinalAngles = [0, Math.PI / 2, Math.PI, 3 * Math.PI / 2];
    var ellipsePoints = [];
    var handles = [];

    for (var j = 0; j < 4; j++) {
        var t = cardinalAngles[j];
        // Point on ellipse in local frame
        var ex = a * Math.cos(t);
        var ey = b * Math.sin(t);
        // Rotate to world frame
        var px = ex * cosA - ey * sinA + c[0];
        var py = ex * sinA + ey * cosA + c[1];
        ellipsePoints.push([px, py]);

        // Handle direction is perpendicular to the radius in the ellipse's frame
        // At cardinal angle t, the tangent direction in local frame is [-a*sin(t), b*cos(t)]
        var ltx = -a * Math.sin(t);
        var lty = b * Math.cos(t);
        // Rotate tangent to world frame
        var wtx = ltx * cosA - lty * sinA;
        var wty = ltx * sinA + lty * cosA;
        // Normalize tangent and scale by kappa * appropriate semi-axis
        var tLen = Math.sqrt(wtx * wtx + wty * wty);
        if (tLen > 1e-10) {
            wtx /= tLen;
            wty /= tLen;
        }

        // Handle length: kappa * the semi-axis perpendicular to the cardinal direction
        // At 0/180 deg: perpendicular axis is b; at 90/270 deg: perpendicular axis is a
        var hLen = (j % 2 === 0) ? k * b : k * a;

        handles.push({
            left:  [px - wtx * hLen, py - wty * hLen],
            right: [px + wtx * hLen, py + wty * hLen]
        });
    }

    return {
        shape: "ellipse",
        points: ellipsePoints,
        handles: handles,
        closed: true,
        confidence: confidence
    };
}

// ── Helpers ──────────────────────────────────────────────────────

function _circumcircle(p1, p2, p3) {
    var ax = p1[0], ay = p1[1];
    var bx = p2[0], by = p2[1];
    var cx = p3[0], cy = p3[1];

    var D = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
    if (Math.abs(D) < 1e-10) return null;

    var ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / D;
    var uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / D;
    var r = dist2d([ux, uy], p1);

    return { center: [ux, uy], radius: r };
}

function _rectCorners(cx, cy, hw, hh, rad) {
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
    return corners;
}
