/**
 * Shape Cleanup — Panel logic
 *
 * Fully standalone: all math runs in ExtendScript via shared libraries.
 * No WebSocket dependency. Communicates with Illustrator via
 * CSInterface.evalScript() only.
 */

/* global CSInterface */

// ── State ──────────────────────────────────────────────────────────

var csInterface = new CSInterface();
var activeShape = null;          // currently highlighted shape type
var hasPreview = false;          // tracks whether a preview path exists

// ── Status Display ─────────────────────────────────────────────────

/**
 * Update the status indicator. States:
 *   "ready"      — idle, waiting for user action
 *   "processing" — running ExtendScript operation
 *   "preview"    — preview path is placed and active
 */
function updateStatus(state) {
    var dot = document.getElementById("statusDot");
    var label = document.getElementById("statusLabel");

    // Remove all state classes, apply new one
    dot.className = "status-dot " + state;
    label.className = "status-label " + state;

    var labels = {
        ready: "ready",
        processing: "processing...",
        preview: "preview active"
    };
    label.textContent = labels[state] || state;
}

// ── Shape Buttons ──────────────────────────────────────────────────

function initShapeButtons() {
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        // Disabled until a preview exists
        buttons[i].disabled = true;
        buttons[i].addEventListener("click", function () {
            var shapeType = this.getAttribute("data-shape");
            highlightShape(shapeType);
            reclassify(shapeType);
        });
    }
}

function highlightShape(shapeType) {
    activeShape = shapeType;
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        if (buttons[i].getAttribute("data-shape") === shapeType) {
            buttons[i].classList.add("active");
        } else {
            buttons[i].classList.remove("active");
        }
    }
}

function clearShapeHighlight() {
    activeShape = null;
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("active");
    }
}

// ── Slider Value Display ───────────────────────────────────────────

function initSliders() {
    var sliders = [
        { id: "tensionSlider", display: "tensionValue" }
    ];

    for (var s = 0; s < sliders.length; s++) {
        (function (cfg) {
            var slider = document.getElementById(cfg.id);
            var display = document.getElementById(cfg.display);
            slider.addEventListener("input", function () {
                display.textContent = this.value;
            });
        })(sliders[s]);
    }

    // Simplification slider — calls applyLODLevel in ExtendScript
    var simplifySlider = document.getElementById("simplifySlider");
    var simplifyDisplay = document.getElementById("simplifyValue");
    simplifySlider.addEventListener("input", function () {
        simplifyDisplay.textContent = this.value;
        onSimplifySlider();
    });

    // Tension slider — resmooth on change when preview is active
    var tensionSlider = document.getElementById("tensionSlider");
    tensionSlider.addEventListener("change", function () {
        if (hasPreview) {
            var tension = parseInt(this.value, 10) / 600;  // map 0-100 to 0-0.167
            csInterface.evalScript("resmooth(" + tension + ")", function () {});
        }
    });
}

// ── Core Actions ───────────────────────────────────────────────────

/**
 * Average the currently selected anchors.
 * All classification, sorting, LOD precomputation, and preview placement
 * happen in ExtendScript — no WebSocket needed.
 */
function averageSelection() {
    updateStatus("processing");

    csInterface.evalScript("averageSelectedAnchors()", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus("ready");
            var errMsg = result ? result.replace(/^error\|/, "") : "No selection";
            updateDetected(errMsg, null);
            bboxUI.hide();
            return;
        }

        var parts = result.split("|");
        // parts: [shape, confidence, inputCount, outputCount]
        updateDetected(parts[0], parseFloat(parts[1]));
        highlightShape(parts[0]);
        hasPreview = true;
        updateStatus("preview");

        document.getElementById("btnConfirm").disabled = false;
        // LOD is already precomputed in ExtendScript
        document.getElementById("simplifySlider").disabled = false;

        // Enable shape override buttons
        var shapeBtns = document.querySelectorAll(".shape-btn");
        for (var sb = 0; sb < shapeBtns.length; sb++) shapeBtns[sb].disabled = false;

        // Hide first-use guidance
        var help = document.getElementById("helpText");
        if (help) help.style.display = "none";

        // Fetch bbox data and show the interactive canvas
        bboxUI.fetch();
    });
}

/**
 * Force reclassify as a specific shape type.
 */
function reclassify(shapeType) {
    updateStatus("processing");

    csInterface.evalScript("reclassifyAs('" + shapeType + "')", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus(hasPreview ? "preview" : "ready");
            return;
        }

        var parts = result.split("|");
        updateDetected(parts[0], parseFloat(parts[1]));
        highlightShape(parts[0]);
        updateStatus("preview");
    });
}

/**
 * Slider handler: apply LOD level from precomputed cache in ExtendScript.
 * Instant — no network round-trip.
 */
function onSimplifySlider() {
    if (!hasPreview) return;
    var val = parseInt(document.getElementById("simplifySlider").value, 10);

    csInterface.evalScript("applyLODLevel(" + val + ")", function (result) {
        if (result && result.indexOf("error") !== 0) {
            document.getElementById("simplifiedCount").textContent = result;
        }
    });
}

/**
 * Update the classification readout display.
 */
function updateDetected(shapeName, confidence) {
    var el = document.getElementById("detected");
    if (confidence !== null && confidence !== undefined) {
        el.innerHTML =
            'Detected: <span class="shape-name">' + escapeHtml(shapeName) +
            '</span> <span class="confidence">(' + confidence.toFixed(2) + ')</span>';
    } else {
        el.textContent = shapeName;
    }
}

/**
 * Confirm the preview path — solidify, enter isolation mode, clear state.
 */
function confirmPreview() {
    csInterface.evalScript("doConfirm()", function (result) {
        if (result && result.indexOf("confirmed") === 0) {
            hasPreview = false;
            document.getElementById("btnConfirm").disabled = true;
            document.getElementById("simplifySlider").disabled = true;
            bboxUI.hide();

            // Disable shape override buttons
            var shapeBtns = document.querySelectorAll(".shape-btn");
            for (var sb = 0; sb < shapeBtns.length; sb++) shapeBtns[sb].disabled = true;

            // Show isolation mode hint and guidance
            updateDetected("In isolation mode \u2014 press Esc to exit", null);
            document.getElementById("isolationHint").style.display = "block";
            updateStatus("ready");
        }
    });
}

/**
 * Undo the preview path — remove and clear state.
 */
function undoPreview() {
    csInterface.evalScript("doUndoAverage()", function (result) {
        if (result === "undone") {
            hasPreview = false;
            document.getElementById("btnConfirm").disabled = true;
            document.getElementById("simplifySlider").disabled = true;
            clearShapeHighlight();
            updateDetected("No selection", null);
            bboxUI.hide();

            // Disable shape override buttons
            var shapeBtns = document.querySelectorAll(".shape-btn");
            for (var sb = 0; sb < shapeBtns.length; sb++) shapeBtns[sb].disabled = true;

            // Hide isolation hint if visible
            document.getElementById("isolationHint").style.display = "none";

            updateStatus("ready");
        }
    });
}

// ── Utilities ──────────────────────────────────────────────────────

function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ── Isolation Mode Exit ───────────────────────────────────────────

function exitIsolation() {
    csInterface.evalScript("app.executeMenuCommand('deselectall'); app.executeMenuCommand('exitisolation')", function() {
        document.getElementById("isolationHint").style.display = "none";
    });
}

// ── Bounding Box Interactive Canvas ────────────────────────────────

var bboxUI = (function () {
    // State
    var canvas = null;
    var ctx = null;
    var section = null;
    var rotInput = null;

    // Original bbox in AI coordinates
    var origCenter = [0, 0];
    var origW = 0;
    var origH = 0;
    var origAngle = 0;     // degrees

    // Current (modified) corners in AI coordinates — 4 corners + 4 midpoints = 8 control points
    var corners = [];      // 4 corners [x, y]
    var midpoints = [];    // 4 midpoints [x, y]
    var controlPts = [];   // 8 control points (corners first, then midpoints)

    // Viewport mapping
    var vpScale = 1;
    var vpOffX = 0;
    var vpOffY = 0;
    var canvasW = 250;
    var canvasH = 180;
    var padding = 20;

    // Drag state
    var dragging = false;
    var dragIdx = -1;
    var lastApplyTime = 0;
    var throttleMs = 150;

    // Snapshot of preview points before drag (for re-applying transform from scratch)
    var origCorners = [];

    function init() {
        canvas = document.getElementById("bboxCanvas");
        section = document.getElementById("bboxSection");
        rotInput = document.getElementById("rotationInput");
        if (!canvas || !section) return;

        ctx = canvas.getContext("2d");
        canvasW = canvas.width;
        canvasH = canvas.height;

        canvas.addEventListener("mousedown", onMouseDown);
        canvas.addEventListener("mousemove", onMouseMove);
        canvas.addEventListener("mouseup", onMouseUp);
        canvas.addEventListener("mouseleave", onMouseUp);

        if (rotInput) {
            rotInput.addEventListener("change", onRotationChange);
        }
    }

    // ── Coordinate mapping: AI ↔ canvas ──

    function computeViewport() {
        // Fit bbox into canvas with padding
        var diag = Math.sqrt(origW * origW + origH * origH);
        if (diag < 1) diag = 100;
        vpScale = (Math.min(canvasW, canvasH) - padding * 2) / diag;
        vpOffX = canvasW / 2;
        vpOffY = canvasH / 2;
    }

    function aiToCanvas(pt) {
        // AI coordinates relative to bbox center → canvas pixels
        // Note: AI Y-axis is inverted relative to canvas
        return [
            (pt[0] - origCenter[0]) * vpScale + vpOffX,
            -(pt[1] - origCenter[1]) * vpScale + vpOffY
        ];
    }

    function canvasToAI(cx, cy) {
        return [
            (cx - vpOffX) / vpScale + origCenter[0],
            -(cy - vpOffY) / vpScale + origCenter[1]
        ];
    }

    // ── Compute corners from center/size/angle ──

    function computeCorners() {
        var rad = origAngle * Math.PI / 180;
        var cosA = Math.cos(rad);
        var sinA = Math.sin(rad);
        var hw = origW / 2;
        var hh = origH / 2;
        var offsets = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];

        corners = [];
        for (var i = 0; i < 4; i++) {
            corners.push([
                origCenter[0] + offsets[i][0] * cosA - offsets[i][1] * sinA,
                origCenter[1] + offsets[i][0] * sinA + offsets[i][1] * cosA
            ]);
        }

        // Midpoints of each edge
        midpoints = [];
        for (var m = 0; m < 4; m++) {
            var next = (m + 1) % 4;
            midpoints.push([
                (corners[m][0] + corners[next][0]) / 2,
                (corners[m][1] + corners[next][1]) / 2
            ]);
        }

        // Combined control points: corners then midpoints
        controlPts = corners.concat(midpoints);
        origCorners = [];
        for (var j = 0; j < corners.length; j++) {
            origCorners.push(corners[j].slice(0));
        }
    }

    // ── Drawing ──

    function draw() {
        if (!ctx) return;
        ctx.clearRect(0, 0, canvasW, canvasH);

        // Draw bbox edges
        ctx.strokeStyle = "#3e7cbf";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        for (var i = 0; i < 4; i++) {
            var p = aiToCanvas(corners[i]);
            if (i === 0) ctx.moveTo(p[0], p[1]);
            else ctx.lineTo(p[0], p[1]);
        }
        ctx.closePath();
        ctx.stroke();

        // Draw crosshair at center
        var cc = aiToCanvas(origCenter);
        ctx.strokeStyle = "#666";
        ctx.lineWidth = 0.5;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.moveTo(cc[0] - 8, cc[1]);
        ctx.lineTo(cc[0] + 8, cc[1]);
        ctx.moveTo(cc[0], cc[1] - 8);
        ctx.lineTo(cc[0], cc[1] + 8);
        ctx.stroke();
        ctx.setLineDash([]);

        // Draw control points
        for (var j = 0; j < controlPts.length; j++) {
            var cp = aiToCanvas(controlPts[j]);
            var isCorner = j < 4;
            var size = isCorner ? 5 : 4;
            ctx.fillStyle = (j === dragIdx) ? "#ff9800" : (isCorner ? "#7cb8f0" : "#a0a0a0");
            ctx.fillRect(cp[0] - size / 2, cp[1] - size / 2, size, size);
            ctx.strokeStyle = "#222";
            ctx.lineWidth = 0.5;
            ctx.strokeRect(cp[0] - size / 2, cp[1] - size / 2, size, size);
        }
    }

    // ── Hit testing ──

    function hitTest(cx, cy) {
        var hitRadius = 8;
        for (var i = 0; i < controlPts.length; i++) {
            var cp = aiToCanvas(controlPts[i]);
            var dx = cx - cp[0];
            var dy = cy - cp[1];
            if (dx * dx + dy * dy < hitRadius * hitRadius) {
                return i;
            }
        }
        return -1;
    }

    // ── Mouse handlers ──

    function getCanvasPos(e) {
        var rect = canvas.getBoundingClientRect();
        return [e.clientX - rect.left, e.clientY - rect.top];
    }

    function onMouseDown(e) {
        var pos = getCanvasPos(e);
        dragIdx = hitTest(pos[0], pos[1]);
        if (dragIdx >= 0) {
            dragging = true;
            // Snapshot original corners for transform computation
            origCorners = [];
            for (var i = 0; i < corners.length; i++) {
                origCorners.push(corners[i].slice(0));
            }
        }
    }

    function onMouseMove(e) {
        var pos = getCanvasPos(e);

        if (!dragging || dragIdx < 0) {
            // Hover cursor
            var hit = hitTest(pos[0], pos[1]);
            canvas.style.cursor = hit >= 0 ? "grab" : "crosshair";
            return;
        }

        canvas.style.cursor = "grabbing";
        var aiPos = canvasToAI(pos[0], pos[1]);

        if (dragIdx < 4) {
            // Dragging a corner — move it, adjust adjacent corners for scale/skew
            corners[dragIdx] = aiPos;

            // Recompute opposite corner stays fixed, adjacent corners adjust
            // Simple: symmetric scale from center
            var oppIdx = (dragIdx + 2) % 4;
            var opp = corners[oppIdx];
            var newCenter = [(aiPos[0] + opp[0]) / 2, (aiPos[1] + opp[1]) / 2];

            // Recompute all 4 corners as a scaled/rotated rect
            var dx = aiPos[0] - opp[0];
            var dy = aiPos[1] - opp[1];
            var halfDiagX = dx / 2;
            var halfDiagY = dy / 2;

            // The other diagonal goes perpendicular
            // For corners: drag=0, opp=2 → adj are 1, 3
            var adj1 = (dragIdx + 1) % 4;
            var adj3 = (dragIdx + 3) % 4;

            // Compute from original aspect ratio
            var origDX = origCorners[dragIdx][0] - origCorners[oppIdx][0];
            var origDY = origCorners[dragIdx][1] - origCorners[oppIdx][1];
            var origDiag = Math.sqrt(origDX * origDX + origDY * origDY);

            if (origDiag > 1e-6) {
                var newDiag = Math.sqrt(dx * dx + dy * dy);
                var scale = newDiag / origDiag;

                // New angle from new diagonal
                var newAngle = Math.atan2(dy, dx);
                var origAngleRad = Math.atan2(origDY, origDX);
                var deltaAngle = newAngle - origAngleRad;

                // Recompute adj corners from origCorners rotated and scaled
                var cos = Math.cos(deltaAngle);
                var sin = Math.sin(deltaAngle);
                var oCenterX = (origCorners[dragIdx][0] + origCorners[oppIdx][0]) / 2;
                var oCenterY = (origCorners[dragIdx][1] + origCorners[oppIdx][1]) / 2;

                for (var ci = 0; ci < 4; ci++) {
                    if (ci === dragIdx) continue;
                    var relX = origCorners[ci][0] - oCenterX;
                    var relY = origCorners[ci][1] - oCenterY;
                    corners[ci] = [
                        newCenter[0] + (relX * cos - relY * sin) * scale,
                        newCenter[1] + (relX * sin + relY * cos) * scale
                    ];
                }
            }
        } else {
            // Dragging a midpoint — scale along one axis
            var edgeIdx = dragIdx - 4;
            var c1 = edgeIdx;
            var c2 = (edgeIdx + 1) % 4;

            // Move both corners along the perpendicular to the edge
            var edgeX = corners[c2][0] - corners[c1][0];
            var edgeY = corners[c2][1] - corners[c1][1];
            var edgeLen = Math.sqrt(edgeX * edgeX + edgeY * edgeY);
            if (edgeLen < 1e-6) return;

            // Perpendicular direction
            var perpX = -edgeY / edgeLen;
            var perpY = edgeX / edgeLen;

            // Project delta onto perpendicular
            var oldMid = midpoints[edgeIdx];
            var delta = (aiPos[0] - oldMid[0]) * perpX + (aiPos[1] - oldMid[1]) * perpY;

            corners[c1] = [corners[c1][0] + perpX * delta, corners[c1][1] + perpY * delta];
            corners[c2] = [corners[c2][0] + perpX * delta, corners[c2][1] + perpY * delta];
        }

        // Recompute midpoints
        midpoints = [];
        for (var m = 0; m < 4; m++) {
            var nxt = (m + 1) % 4;
            midpoints.push([
                (corners[m][0] + corners[nxt][0]) / 2,
                (corners[m][1] + corners[nxt][1]) / 2
            ]);
        }
        controlPts = corners.concat(midpoints);

        draw();

        // Throttled live transform
        var now = Date.now();
        if (now - lastApplyTime >= throttleMs) {
            lastApplyTime = now;
            applyTransformFromCorners();
        }
    }

    function onMouseUp(e) {
        if (dragging) {
            dragging = false;
            dragIdx = -1;
            // Final apply on mouse up
            applyTransformFromCorners();
            draw();
        }
    }

    // ── Transform computation ──

    function applyTransformFromCorners() {
        // Compute affine from original corners to current corners
        // Decompose as: translate to origin, scale_x, scale_y, rotate, translate to new center
        var oCx = 0, oCy = 0, nCx = 0, nCy = 0;
        for (var i = 0; i < 4; i++) {
            oCx += origCorners[i][0];
            oCy += origCorners[i][1];
            nCx += corners[i][0];
            nCy += corners[i][1];
        }
        oCx /= 4; oCy /= 4;
        nCx /= 4; nCy /= 4;

        // Compute scale and rotation using edge vectors
        // Original edge 0→1
        var oEdgeX = origCorners[1][0] - origCorners[0][0];
        var oEdgeY = origCorners[1][1] - origCorners[0][1];
        var oLen = Math.sqrt(oEdgeX * oEdgeX + oEdgeY * oEdgeY);
        var oAng = Math.atan2(oEdgeY, oEdgeX);

        // New edge 0→1
        var nEdgeX = corners[1][0] - corners[0][0];
        var nEdgeY = corners[1][1] - corners[0][1];
        var nLen = Math.sqrt(nEdgeX * nEdgeX + nEdgeY * nEdgeY);
        var nAng = Math.atan2(nEdgeY, nEdgeX);

        // Original edge 0→3 (perpendicular axis)
        var oPerX = origCorners[3][0] - origCorners[0][0];
        var oPerY = origCorners[3][1] - origCorners[0][1];
        var oPerLen = Math.sqrt(oPerX * oPerX + oPerY * oPerY);

        // New edge 0→3
        var nPerX = corners[3][0] - corners[0][0];
        var nPerY = corners[3][1] - corners[0][1];
        var nPerLen = Math.sqrt(nPerX * nPerX + nPerY * nPerY);

        var sx = (oLen > 1e-6) ? nLen / oLen : 1;
        var sy = (oPerLen > 1e-6) ? nPerLen / oPerLen : 1;
        var dAng = nAng - oAng;

        // Build affine matrix: translate(-oC) * rotate(dAng) * scale(sx, sy) * translate(nC)
        // In the original frame's local axes:
        var cosR = Math.cos(dAng);
        var sinR = Math.sin(dAng);

        // M = R * S (in original frame then translate)
        // But we need to do: p' = R * S * (p - oC) + nC
        // which is: p' = [a b; c d] * p + [tx; ty]
        // where [a b; c d] = R * diag(sx, sy) * R_orig^-1 ... complicated.
        //
        // Simpler: use the full 3-point affine from first 3 corners
        // p' = A * (p - origCorners[0]) + corners[0]
        // Using vectors: e0 = origCorners[1]-origCorners[0], e1 = origCorners[3]-origCorners[0]
        //                f0 = corners[1]-corners[0],         f1 = corners[3]-corners[0]
        // A = [f0 f1] * [e0 e1]^-1

        var e0x = origCorners[1][0] - origCorners[0][0];
        var e0y = origCorners[1][1] - origCorners[0][1];
        var e1x = origCorners[3][0] - origCorners[0][0];
        var e1y = origCorners[3][1] - origCorners[0][1];

        var f0x = corners[1][0] - corners[0][0];
        var f0y = corners[1][1] - corners[0][1];
        var f1x = corners[3][0] - corners[0][0];
        var f1y = corners[3][1] - corners[0][1];

        // [e0 e1]^-1
        var det = e0x * e1y - e0y * e1x;
        if (Math.abs(det) < 1e-10) return;

        var ie0x =  e1y / det;
        var ie0y = -e0y / det;
        var ie1x = -e1x / det;
        var ie1y =  e0x / det;

        // A = [f0 f1] * [e0 e1]^-1
        var a = f0x * ie0x + f1x * ie0y;
        var b = f0x * ie1x + f1x * ie1y;
        var c = f0y * ie0x + f1y * ie0y;
        var d = f0y * ie1x + f1y * ie1y;

        // Translation: corners[0] - A * origCorners[0]
        var tx = corners[0][0] - (a * origCorners[0][0] + b * origCorners[0][1]);
        var ty = corners[0][1] - (c * origCorners[0][0] + d * origCorners[0][1]);

        // Guard against degenerate transforms (NaN/Infinity from near-zero determinants)
        if (!isFinite(a) || !isFinite(b) || !isFinite(c) || !isFinite(d) || !isFinite(tx) || !isFinite(ty)) {
            return;
        }

        csInterface.evalScript(
            "applyBboxTransform(" + a + "," + b + "," + c + "," + d + "," + tx + "," + ty + ")",
            function () {}
        );
    }

    // ── Rotation input handler ──

    function onRotationChange() {
        if (!rotInput) return;
        var newAngle = parseFloat(rotInput.value) || 0;
        var deltaAngle = (newAngle - origAngle) * Math.PI / 180;

        // Rotate original corners around center
        var cos = Math.cos(deltaAngle);
        var sin = Math.sin(deltaAngle);

        for (var i = 0; i < origCorners.length; i++) {
            var rx = origCorners[i][0] - origCenter[0];
            var ry = origCorners[i][1] - origCenter[1];
            corners[i] = [
                origCenter[0] + rx * cos - ry * sin,
                origCenter[1] + rx * sin + ry * cos
            ];
        }

        // Recompute midpoints
        midpoints = [];
        for (var m = 0; m < 4; m++) {
            var nxt = (m + 1) % 4;
            midpoints.push([
                (corners[m][0] + corners[nxt][0]) / 2,
                (corners[m][1] + corners[nxt][1]) / 2
            ]);
        }
        controlPts = corners.concat(midpoints);

        draw();
        applyTransformFromCorners();
    }

    // ── Public API ──

    return {
        init: init,

        /**
         * Fetch bbox data from ExtendScript and show the canvas.
         */
        fetch: function () {
            csInterface.evalScript("getBboxData()", function (result) {
                if (!result || result.indexOf("error") === 0) return;

                var parts = result.split("|");
                origCenter = [parseFloat(parts[0]), parseFloat(parts[1])];
                origW = parseFloat(parts[2]);
                origH = parseFloat(parts[3]);
                origAngle = parseFloat(parts[4]);

                if (rotInput) rotInput.value = Math.round(origAngle);

                computeViewport();
                computeCorners();

                if (section) section.style.display = "";
                draw();

                // Store original point positions so applyBboxTransform
                // transforms FROM originals (prevents cumulative drift)
                csInterface.evalScript("storeBboxOriginals()", function () {});
            });
        },

        /**
         * Hide the canvas section and reset state.
         */
        hide: function () {
            if (section) section.style.display = "none";
            dragging = false;
            dragIdx = -1;
        }
    };
})();

// ── Keyboard Shortcuts ────────────────────────────────────────────

document.addEventListener("keydown", function(e) {
    // Don't trigger when typing in inputs
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "Enter") {
        if (hasPreview) confirmPreview();
        else averageSelection();
    } else if (e.key === "Escape") {
        if (document.getElementById("isolationHint").style.display !== "none") {
            exitIsolation();
        } else {
            undoPreview();
        }
    } else if (hasPreview && e.key >= "1" && e.key <= "7") {
        var shapes = ["line", "arc", "lshape", "rectangle", "scurve", "ellipse", "freeform"];
        var idx = parseInt(e.key) - 1;
        if (idx < shapes.length) {
            highlightShape(shapes[idx]);
            reclassify(shapes[idx]);
        }
    }
});

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initShapeButtons();
    initSliders();
    bboxUI.init();
    csInterface.evalScript("cleanupOrphans()", function() {});
    updateStatus("ready");
})();
