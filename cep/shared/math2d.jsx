/**
 * math2d.jsx — 2D vector math primitives for ExtendScript (ES3).
 *
 * Pure math: no Illustrator DOM access. All functions operate on
 * [x, y] arrays and return new arrays (never mutate inputs).
 */

/**
 * Euclidean distance between two points.
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {number}
 */
function dist2d(a, b) {
    var dx = b[0] - a[0];
    var dy = b[1] - a[1];
    return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Squared distance (avoids sqrt for comparisons).
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {number}
 */
function dist2dSq(a, b) {
    var dx = b[0] - a[0];
    var dy = b[1] - a[1];
    return dx * dx + dy * dy;
}

/**
 * Dot product of two 2D vectors.
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {number}
 */
function dot2d(a, b) {
    return a[0] * b[0] + a[1] * b[1];
}

/**
 * 2D cross product (z-component of 3D cross).
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {number}
 */
function cross2d(a, b) {
    return a[0] * b[1] - a[1] * b[0];
}

/**
 * Vector subtraction: a - b.
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {Array} [x, y]
 */
function sub2d(a, b) {
    return [a[0] - b[0], a[1] - b[1]];
}

/**
 * Vector addition: a + b.
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {Array} [x, y]
 */
function add2d(a, b) {
    return [a[0] + b[0], a[1] + b[1]];
}

/**
 * Scalar multiply: v * s.
 * @param {Array} v - [x, y]
 * @param {number} s - scalar
 * @returns {Array} [x, y]
 */
function scale2d(v, s) {
    return [v[0] * s, v[1] * s];
}

/**
 * Vector length.
 * @param {Array} v - [x, y]
 * @returns {number}
 */
function len2d(v) {
    return Math.sqrt(v[0] * v[0] + v[1] * v[1]);
}

/**
 * Normalize to unit vector. Returns [0,0] for zero-length input.
 * @param {Array} v - [x, y]
 * @returns {Array} [x, y]
 */
function normalize2d(v) {
    var l = len2d(v);
    if (l < 1e-12) return [0, 0];
    return [v[0] / l, v[1] / l];
}

/**
 * Linear interpolation between two points.
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @param {number} t - interpolation factor (0..1)
 * @returns {Array} [x, y]
 */
function lerp2d(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/**
 * Perpendicular distance from point P to line segment AB.
 * @param {Array} p - [x, y]
 * @param {Array} a - [x, y] line start
 * @param {Array} b - [x, y] line end
 * @returns {number}
 */
function pointToSegmentDist(p, a, b) {
    var ab = sub2d(b, a);
    var ap = sub2d(p, a);
    var abLenSq = dot2d(ab, ab);
    if (abLenSq < 1e-12) return dist2d(p, a);

    var t = dot2d(ap, ab) / abLenSq;
    if (t < 0) t = 0;
    if (t > 1) t = 1;

    var proj = [a[0] + ab[0] * t, a[1] + ab[1] * t];
    return dist2d(p, proj);
}

/**
 * Centroid of a point array.
 * @param {Array} pts - array of [x, y]
 * @returns {Array} [x, y]
 */
function centroid2d(pts) {
    var sx = 0, sy = 0;
    for (var i = 0; i < pts.length; i++) {
        sx += pts[i][0];
        sy += pts[i][1];
    }
    return [sx / pts.length, sy / pts.length];
}

/**
 * Rotate a point around a center by angle (radians).
 * @param {Array} p - [x, y]
 * @param {Array} center - [x, y]
 * @param {number} angle - radians
 * @returns {Array} [x, y]
 */
function rotate2d(p, center, angle) {
    var dx = p[0] - center[0];
    var dy = p[1] - center[1];
    var cosA = Math.cos(angle);
    var sinA = Math.sin(angle);
    return [
        center[0] + dx * cosA - dy * sinA,
        center[1] + dx * sinA + dy * cosA
    ];
}

/**
 * Angle between two vectors in degrees (0..180).
 * Returns 0 for zero-length vectors.
 * @param {Array} a - [x, y]
 * @param {Array} b - [x, y]
 * @returns {number}
 */
function angle2d(a, b) {
    var la = len2d(a);
    var lb = len2d(b);
    if (la < 1e-10 || lb < 1e-10) return 0;
    var cosTheta = dot2d(a, b) / (la * lb);
    if (cosTheta > 1) cosTheta = 1;
    if (cosTheta < -1) cosTheta = -1;
    return Math.acos(cosTheta) * 180 / Math.PI;
}

/**
 * Perpendicular (normal) vector, rotated 90 degrees CCW.
 * @param {Array} v - [x, y]
 * @returns {Array} [-y, x]
 */
function perp2d(v) { return [-v[1], v[0]]; }


// ── Statistics ──────────────────────────────────────────────────────

/**
 * Median of a numeric array. Returns NaN for empty arrays.
 * @param {Array} arr - numeric array
 * @returns {number}
 */
function median(arr) {
    if (arr.length === 0) return NaN;
    var sorted = arr.slice(0);
    sorted.sort(function(a, b) { return a - b; });
    var mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) return (sorted[mid - 1] + sorted[mid]) / 2;
    return sorted[mid];
}

/**
 * Arithmetic mean of a numeric array. Returns NaN for empty arrays.
 * @param {Array} arr - numeric array
 * @returns {number}
 */
function mean(arr) {
    if (arr.length === 0) return NaN;
    var sum = 0;
    for (var i = 0; i < arr.length; i++) sum += arr[i];
    return sum / arr.length;
}


// ── Linear Regression ───────────────────────────────────────────────

/**
 * Linear least-squares fit: y = mx + b.
 * @param {Array} points - array of [x, y] pairs
 * @returns {Object} {slope, intercept, r_squared}
 */
function linearFit(points) {
    var n = points.length;
    if (n < 2) return { slope: 0, intercept: 0, r_squared: 0 };

    var sx = 0, sy = 0, sxy = 0, sx2 = 0, sy2 = 0;
    for (var i = 0; i < n; i++) {
        var x = points[i][0];
        var y = points[i][1];
        sx += x;
        sy += y;
        sxy += x * y;
        sx2 += x * x;
        sy2 += y * y;
    }

    var denom = n * sx2 - sx * sx;
    if (Math.abs(denom) < 1e-10) {
        return { slope: 0, intercept: sy / n, r_squared: 0 };
    }

    var m = (n * sxy - sx * sy) / denom;
    var b = (sy - m * sx) / n;

    var ss_tot = sy2 - (sy * sy) / n;
    var ss_res = 0;
    for (var j = 0; j < n; j++) {
        var pred = m * points[j][0] + b;
        var err = points[j][1] - pred;
        ss_res += err * err;
    }
    var r2 = (Math.abs(ss_tot) < 1e-10) ? 1.0 : 1.0 - ss_res / ss_tot;

    return { slope: m, intercept: b, r_squared: r2 };
}


// ── Quadratic Regression ────────────────────────────────────────────

/**
 * 3x3 determinant via Sarrus' rule.
 * @param {Array} m - [[a,b,c],[d,e,f],[g,h,i]]
 * @returns {number}
 */
function _det3(m) {
    return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
         - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
         + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
}

/**
 * Quadratic least-squares fit: y = ax^2 + bx + c.
 * Solved via normal equations and Cramer's rule (3x3).
 * @param {Array} points - array of [x, y] pairs
 * @returns {Object} {a, b, c, r_squared}
 */
function quadraticFit(points) {
    var n = points.length;
    if (n < 3) return { a: 0, b: 0, c: 0, r_squared: 0 };

    var s0 = n;
    var s1 = 0, s2 = 0, s3 = 0, s4 = 0;
    var sy = 0, sxy = 0, sx2y = 0, sy2 = 0;

    for (var i = 0; i < n; i++) {
        var x = points[i][0];
        var y = points[i][1];
        var x2 = x * x;
        var x3 = x2 * x;
        var x4 = x2 * x2;

        s1 += x;
        s2 += x2;
        s3 += x3;
        s4 += x4;
        sy += y;
        sxy += x * y;
        sx2y += x2 * y;
        sy2 += y * y;
    }

    var M = [[s4, s3, s2], [s3, s2, s1], [s2, s1, s0]];
    var D = _det3(M);

    if (Math.abs(D) < 1e-20) {
        var lin = linearFit(points);
        return { a: 0, b: lin.slope, c: lin.intercept, r_squared: lin.r_squared };
    }

    var Da = _det3([[sx2y, s3, s2], [sxy, s2, s1], [sy, s1, s0]]);
    var Db = _det3([[s4, sx2y, s2], [s3, sxy, s1], [s2, sy, s0]]);
    var Dc = _det3([[s4, s3, sx2y], [s3, s2, sxy], [s2, s1, sy]]);

    var a = Da / D;
    var b = Db / D;
    var c = Dc / D;

    var ss_tot = sy2 - (sy * sy) / n;
    var ss_res = 0;
    for (var j = 0; j < n; j++) {
        var xj = points[j][0];
        var pred = a * xj * xj + b * xj + c;
        var err = points[j][1] - pred;
        ss_res += err * err;
    }
    var r2 = (Math.abs(ss_tot) < 1e-10) ? 1.0 : 1.0 - ss_res / ss_tot;

    return { a: a, b: b, c: c, r_squared: r2 };
}
