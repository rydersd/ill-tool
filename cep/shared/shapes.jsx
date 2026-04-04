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
 * @returns {Object} {shape: string, points: [[x,y],...], closed: boolean, confidence: number}
 */
function classifyShape(sortedPoints) {
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

    var ang1 = Math.atan2(p1[1] - circle.center[1], p1[0] - circle.center[0]);
    var ang3 = Math.atan2(p3[1] - circle.center[1], p3[0] - circle.center[0]);
    var angMid = Math.atan2(p2[1] - circle.center[1], p2[0] - circle.center[0]);
    var sweep = ang3 - ang1;
    while (sweep > Math.PI) sweep -= 2 * Math.PI;
    while (sweep < -Math.PI) sweep += 2 * Math.PI;

    var numPts = Math.max(n, 8);
    var arcPoints = [];
    for (var i = 0; i < numPts; i++) {
        var t = i / (numPts - 1);
        var a = ang1 + sweep * t;
        arcPoints.push([
            circle.center[0] + circle.radius * Math.cos(a),
            circle.center[1] + circle.radius * Math.sin(a)
        ]);
    }

    return { shape: "arc", points: arcPoints, closed: false, confidence: confidence };
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
    var simplified = douglasPeucker(pts, dist2d(pts[0], pts[pts.length - 1]) * 0.02);
    if (simplified.length < 3) simplified = pts.slice(0);
    return {
        shape: "scurve",
        points: simplified,
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

    var a = Math.sqrt(Math.max(0, ev1)) * 2;
    var b = Math.sqrt(Math.max(0, ev2)) * 2;

    var angle;
    if (Math.abs(cxy) > 1e-10) {
        angle = Math.atan2(ev1 - cxx, cxy);
    } else {
        angle = cxx >= cyy ? 0 : Math.PI / 2;
    }

    var numPts = Math.max(n, 16);
    var ellipsePoints = [];
    for (var j = 0; j < numPts; j++) {
        var t = (j / numPts) * 2 * Math.PI;
        var ex = a * Math.cos(t);
        var ey = b * Math.sin(t);
        var rx = ex * Math.cos(angle) - ey * Math.sin(angle) + c[0];
        var ry = ex * Math.sin(angle) + ey * Math.cos(angle) + c[1];
        ellipsePoints.push([rx, ry]);
    }

    return {
        shape: "ellipse",
        points: ellipsePoints,
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
