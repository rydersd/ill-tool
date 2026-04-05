/**
 * Grouping Tools — Panel logic
 *
 * Fully standalone: all math runs in ExtendScript via shared libraries.
 * No WebSocket dependency. Communicates with Illustrator via
 * CSInterface.evalScript() only.
 */

/* global CSInterface */

// ── State ──────────────────────────────────────────────────────────

var csInterface = new CSInterface();
var hasDetached = false;         // tracks whether detached paths exist
var originalPointCount = 0;      // point count before simplification
var selectionPollTimer = null;   // timer for polling selection state
var accentColor = localStorage.getItem("pr_accentColor") || "orange";
var bboxData = null;             // cached bounding box parameters from detach
var bboxCorners = null;          // current corner positions for overlay drag

// ── C++ Plugin Bridge ─────────────────────────────────────────────
var PLUGIN_URL = "http://localhost:8787";
var pluginConnected = false;
var eventSource = null;

/**
 * Check if the C++ plugin is running. If yes, activate annotator and
 * start the SSE event listener. If not, log and continue — overlays
 * disabled, panel works normally.
 */
function connectPluginBridge() {
    fetch(PLUGIN_URL + "/status")
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            if (data && data.status === "ok") {
                pluginConnected = true;
                console.log("[IllTool] Plugin bridge connected at " + PLUGIN_URL);
                // Activate the annotator so overlay drawing is enabled
                fetch(PLUGIN_URL + "/annotator/activate", { method: "POST" })
                    .catch(function() {});
                startEventListener();
                updateBridgeIndicator(true);
            }
        })
        .catch(function() {
            pluginConnected = false;
            console.log("[IllTool] Plugin bridge not available — overlays disabled");
            updateBridgeIndicator(false);
        });
}

/**
 * POST draw commands to /draw. Fire and forget.
 */
function sendDrawCommands(commands) {
    if (!pluginConnected || !commands || commands.length === 0) return;
    fetch(PLUGIN_URL + "/draw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ commands: commands })
    }).catch(function(err) {
        console.log("[IllTool] Draw command failed: " + err.message);
    });
}

/**
 * POST to /clear to remove all overlays.
 */
function clearOverlays() {
    if (!pluginConnected) return;
    fetch(PLUGIN_URL + "/clear", { method: "POST" })
        .catch(function() {});
}

/**
 * Create EventSource to /events for mouse events from the plugin.
 * Listens for mousedown, mousedrag, mouseup for handle dragging.
 */
function startEventListener() {
    if (eventSource) return;
    try {
        eventSource = new EventSource(PLUGIN_URL + "/events");
        eventSource.addEventListener("mousedrag", function(e) {
            try {
                var data = JSON.parse(e.data);
                handleOverlayDrag(data);
            } catch (err) {}
        });
        eventSource.addEventListener("mouseup", function(e) {
            // Drag complete — rebuild overlay with final positions
            if (pluginConnected && hasDetached) {
                sendSimplifyOverlay();
            }
        });
        eventSource.onerror = function() {
            // SSE connection lost — clean up and retry after delay
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            setTimeout(function() {
                if (pluginConnected) startEventListener();
            }, 3000);
        };
    } catch (err) {
        console.log("[IllTool] EventSource not available: " + err.message);
    }
}

/**
 * Build draw command array from path data for the C++ annotator.
 *
 * Draws:
 * - Ghost bezier of original path (gray, dashed, 40% opacity)
 * - Solid bezier of simplified path (accent color)
 * - Filled circle handles at each control point (draggable)
 * - Text label showing point count
 */
function buildSimplifyOverlayCommands(pathData, color) {
    var commands = [];
    var accentRGB = (color === "cyan") ? [0, 200, 220] : [255, 136, 0];

    // Ghost original path — gray dashed bezier
    if (pathData.original.length >= 2) {
        var origSegments = [];
        for (var i = 0; i < pathData.original.length - 1; i++) {
            var a = pathData.original[i];
            var b = pathData.original[i + 1];
            origSegments.push({
                p0: a.anchor, cp1: a.right, cp2: b.left, p3: b.anchor
            });
        }
        commands.push({
            type: "bezier",
            segments: origSegments,
            color: [128, 128, 128],
            strokeWidth: 0.5,
            opacity: 0.4,
            dash: [3, 3]
        });
    }

    // Simplified path — solid bezier in accent color
    if (pathData.simplified.length >= 2) {
        var simpSegments = [];
        for (var j = 0; j < pathData.simplified.length - 1; j++) {
            var sa = pathData.simplified[j];
            var sb = pathData.simplified[j + 1];
            simpSegments.push({
                p0: sa.anchor, cp1: sa.right, cp2: sb.left, p3: sb.anchor
            });
        }
        commands.push({
            type: "bezier",
            segments: simpSegments,
            color: accentRGB,
            strokeWidth: 1.5,
            opacity: 1.0
        });
    }

    // Handle circles at each simplified control point
    for (var h = 0; h < pathData.handles.length; h++) {
        var handle = pathData.handles[h];
        commands.push({
            type: "circle",
            center: handle.anchor,
            radius: 4,
            fillColor: accentRGB,
            strokeColor: [255, 255, 255],
            strokeWidth: 0.5,
            draggable: true,
            hitRadius: 8,
            id: handle.id
        });
    }

    // Point count label — positioned above the center of simplified path
    if (pathData.simplified.length > 0) {
        var cx = 0, cy = 0;
        for (var p = 0; p < pathData.simplified.length; p++) {
            cx += pathData.simplified[p].anchor[0];
            cy += pathData.simplified[p].anchor[1];
        }
        cx /= pathData.simplified.length;
        cy /= pathData.simplified.length;
        commands.push({
            type: "text",
            position: [cx, cy + 12],  // offset above (Illustrator Y goes up)
            text: pathData.simplified.length + " pts",
            color: accentRGB,
            fontSize: 10
        });
    }

    return commands;
}

/**
 * Build draw command array for bounding box overlay with draggable corner handles.
 *
 * @param {Object} bbox - {center: [cx,cy], width, height, angle, padding}
 * @param {string} color - "orange" or "cyan"
 * @returns {Array} draw commands for the C++ annotator
 */
function buildBoundingBoxOverlayCommands(bbox, color) {
    var commands = [];
    var accentRGB = (color === "cyan") ? [0, 200, 220] : [255, 136, 0];

    var pw = bbox.width + bbox.padding * 2;
    var ph = bbox.height + bbox.padding * 2;
    var hw = pw / 2;
    var hh = ph / 2;
    var rad = bbox.angle * Math.PI / 180;
    var cosA = Math.cos(rad);
    var sinA = Math.sin(rad);
    var cx = bbox.center[0];
    var cy = bbox.center[1];

    var offsets = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
    var corners = [];
    for (var i = 0; i < 4; i++) {
        corners.push([
            cx + offsets[i][0] * cosA - offsets[i][1] * sinA,
            cy + offsets[i][0] * sinA + offsets[i][1] * cosA
        ]);
    }

    // Cache corners for drag handling
    bboxCorners = corners;

    // 4 line segments forming the rotated rectangle outline
    for (var s = 0; s < 4; s++) {
        var next = (s + 1) % 4;
        commands.push({
            type: "line",
            p0: corners[s],
            p1: corners[next],
            color: accentRGB,
            strokeWidth: 1,
            opacity: 0.6
        });
    }

    // 4 filled circle handles at corners — draggable
    for (var h = 0; h < 4; h++) {
        commands.push({
            type: "circle",
            center: corners[h],
            radius: 5,
            fillColor: accentRGB,
            strokeColor: [255, 255, 255],
            strokeWidth: 0.75,
            draggable: true,
            hitRadius: 10,
            id: "bbox_corner_" + h
        });
    }

    // Center crosshair (small +)
    var crossSize = 4;
    commands.push({
        type: "line",
        p0: [cx - crossSize, cy],
        p1: [cx + crossSize, cy],
        color: accentRGB,
        strokeWidth: 0.5,
        opacity: 0.5
    });
    commands.push({
        type: "line",
        p0: [cx, cy - crossSize],
        p1: [cx, cy + crossSize],
        color: accentRGB,
        strokeWidth: 0.5,
        opacity: 0.5
    });

    return commands;
}

/**
 * Handle bbox corner drag: recompute box from moved corner, rebuild overlay.
 *
 * When one corner moves, we recompute the bounding box by finding the new
 * center and dimensions from all 4 corners (3 fixed + 1 dragged).
 */
function handleBboxCornerDrag(cornerIndex, newPos) {
    if (!bboxCorners || !bboxData) return;

    // Update the dragged corner
    bboxCorners[cornerIndex] = newPos;

    // Recompute center from all 4 corners
    var cx = 0, cy = 0;
    for (var i = 0; i < 4; i++) {
        cx += bboxCorners[i][0];
        cy += bboxCorners[i][1];
    }
    cx /= 4;
    cy /= 4;

    // Recompute width/height from corner distances
    var dx01 = bboxCorners[1][0] - bboxCorners[0][0];
    var dy01 = bboxCorners[1][1] - bboxCorners[0][1];
    var dx03 = bboxCorners[3][0] - bboxCorners[0][0];
    var dy03 = bboxCorners[3][1] - bboxCorners[0][1];
    var newWidth = Math.sqrt(dx01 * dx01 + dy01 * dy01);
    var newHeight = Math.sqrt(dx03 * dx03 + dy03 * dy03);
    var newAngle = Math.atan2(dy01, dx01) * 180 / Math.PI;

    // Update cached bbox data (without padding — subtract it back)
    bboxData.center = [cx, cy];
    bboxData.width = newWidth - bboxData.padding * 2;
    bboxData.height = newHeight - bboxData.padding * 2;
    bboxData.angle = newAngle;

    // Rebuild full overlay (simplify paths + bbox)
    sendSimplifyOverlay();
}

/**
 * Handle drag events from the C++ plugin overlay.
 * Moves the corresponding path point in the document and refreshes overlay.
 */
function handleOverlayDrag(data) {
    if (!data || !data.id || !data.position) return;
    var handleId = data.id;
    var newX = data.position[0];
    var newY = data.position[1];

    // Check if this is a bbox corner drag
    if (handleId.indexOf("bbox_corner_") === 0) {
        var cornerIdx = parseInt(handleId.replace("bbox_corner_", ""), 10);
        handleBboxCornerDrag(cornerIdx, [newX, newY]);
        return;
    }

    // Move the point in ExtendScript
    csInterface.evalScript(
        "pr_moveHandlePoint('" + handleId + "', " + newX + ", " + newY + ")",
        function(result) {
            if (result === "ok") {
                // Rebuild overlay with updated positions
                sendSimplifyOverlay();
            }
        }
    );
}

/**
 * Fetch current path data from ExtendScript and send overlay commands.
 * Also sends bounding box overlay if bbox data is cached and plugin is connected.
 */
function sendSimplifyOverlay() {
    if (!pluginConnected) return;
    csInterface.evalScript("pr_getSimplifiedPathData()", function(pathJson) {
        if (pathJson && pathJson !== "EvalScript Error" && pathJson !== "undefined") {
            try {
                var pathData = JSON.parse(pathJson);
                var commands = buildSimplifyOverlayCommands(pathData, accentColor);

                // Append bounding box overlay commands if bbox data is available
                if (bboxData && document.getElementById("showBBox").checked) {
                    var bboxCommands = buildBoundingBoxOverlayCommands(bboxData, accentColor);
                    commands = commands.concat(bboxCommands);
                }

                sendDrawCommands(commands);
            } catch (e) {}
        }
    });
}

/**
 * Update the bridge connection indicator in the header.
 */
function updateBridgeIndicator(connected) {
    var el = document.getElementById("bridgeStatus");
    if (el) {
        el.style.color = connected ? "#4caf50" : "#666";
        el.title = connected ? "Plugin bridge connected" : "Plugin bridge offline";
    }
}

/**
 * Ask Claude for simplification advice via the plugin's /llm/query endpoint.
 */
function askClaude() {
    if (!pluginConnected) return;
    var btn = document.getElementById("btnAskClaude");
    var responseDiv = document.getElementById("claudeResponse");
    var textDiv = document.getElementById("claudeText");

    btn.disabled = true;
    btn.textContent = "Thinking...";
    responseDiv.style.display = "block";
    textDiv.textContent = "Waiting for response...";

    // Build context from current state
    var context = {
        originalPoints: originalPointCount,
        simplifiedPoints: document.getElementById("simplifiedCount").textContent,
        sliderLevel: document.getElementById("simplifySlider").value,
        accentColor: accentColor
    };

    var systemPrompt = "You are an expert illustration path simplification advisor. " +
        "The user is working in Adobe Illustrator, simplifying bezier paths for " +
        "clean vector illustration. Give concise, actionable advice about point " +
        "reduction, curve quality, and when to use manual vs automated simplification.";

    var userPrompt = "I have a path with " + context.originalPoints + " original points, " +
        "currently simplified to " + context.simplifiedPoints + " points " +
        "(slider at " + context.sliderLevel + "/100). " +
        "What simplification level would you recommend, and should I adjust any handles manually?";

    fetch(PLUGIN_URL + "/llm/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            system: systemPrompt,
            prompt: userPrompt,
            max_tokens: 256
        })
    })
    .then(function(resp) { return resp.json(); })
    .then(function(data) {
        if (data && data.response) {
            textDiv.textContent = data.response;
        } else if (data && data.error) {
            textDiv.textContent = "Error: " + data.error;
        } else {
            textDiv.textContent = "No response received.";
        }
        btn.textContent = "Ask Claude";
        btn.disabled = !hasDetached;
    })
    .catch(function(err) {
        textDiv.textContent = "Request failed: " + err.message;
        btn.textContent = "Ask Claude";
        btn.disabled = !hasDetached;
    });
}

// ── Status Display ─────────────────────────────────────────────────

/**
 * Update the status indicator. States:
 *   "ready"      — idle, waiting for user action
 *   "processing" — running ExtendScript operation
 *   "preview"    — detached paths are placed and active
 */
function updateStatus(state) {
    var dot = document.getElementById("statusDot");
    var label = document.getElementById("statusLabel");

    dot.className = "status-dot " + state;
    label.className = "status-label " + state;

    var labels = {
        ready: "ready",
        processing: "processing...",
        preview: "preview active"
    };
    label.textContent = labels[state] || state;
}

// ── Selection Polling ──────────────────────────────────────────────

/**
 * Poll Illustrator selection to update the anchor/path count display.
 * Runs on a 500ms interval so the panel shows live feedback.
 */
function pollSelection() {
    csInterface.evalScript("pr_getSelectionInfo()", function (result) {
        if (!result || result === "EvalScript Error" || result === "undefined") {
            document.getElementById("anchorCount").textContent = "0";
            document.getElementById("pathCount").textContent = "0";
            return;
        }

        // Parse pipe-delimited: "anchorCount|pathCount"
        var parts = result.split("|");
        var anchorCount = parseInt(parts[0], 10) || 0;
        var pathCount = parseInt(parts[1], 10) || 0;

        document.getElementById("anchorCount").textContent = anchorCount;
        document.getElementById("pathCount").textContent = pathCount;
    });
}

function startSelectionPolling() {
    if (selectionPollTimer) return;
    selectionPollTimer = setInterval(pollSelection, 500);
}

function stopSelectionPolling() {
    if (selectionPollTimer) {
        clearInterval(selectionPollTimer);
        selectionPollTimer = null;
    }
}

// ── Core Actions ───────────────────────────────────────────────────

/**
 * Detach selected anchors from their parent paths into new paths
 * on the "Refined Forms" layer. All simplification is precomputed
 * in ExtendScript for instant slider scrubbing.
 */
function detachSelection() {
    updateStatus("processing");

    var padding = parseInt(document.getElementById("paddingSlider").value, 10) || 5;
    var groupName = document.getElementById("groupName").value.replace(/'/g, "\\'").replace(/\\/g, "\\\\") || "";
    csInterface.evalScript("pr_detachAndPrecompute(" + padding + ", '" + groupName + "')", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus("ready");
            var errMsg = result ? result.replace(/^error\|/, "") : "No selection";
            document.getElementById("anchorCount").textContent = errMsg;
            return;
        }

        var parts = result.split("|");
        var detachedCount = parseInt(parts[0], 10) || 0;
        var totalPoints = parseInt(parts[1], 10) || 0;

        if (detachedCount > 0) {
            hasDetached = true;
            originalPointCount = totalPoints;

            // Update point count display
            document.getElementById("originalCount").textContent = originalPointCount;
            document.getElementById("simplifiedCount").textContent = originalPointCount;

            // Enable controls
            document.getElementById("simplifySlider").disabled = false;
            document.getElementById("btnApply").disabled = false;
            document.getElementById("btnReset").disabled = false;
            document.getElementById("btnUndo").disabled = false;
            document.getElementById("btnAskClaude").disabled = false;

            // Fetch bounding box data for overlay rendering
            csInterface.evalScript("pr_getBoundingBoxData()", function(bboxJson) {
                if (bboxJson && bboxJson !== "EvalScript Error" && bboxJson !== "undefined") {
                    try {
                        bboxData = JSON.parse(bboxJson);
                    } catch (e) {
                        bboxData = null;
                    }
                }
                // Send initial overlay to C++ plugin (includes bbox if available)
                sendSimplifyOverlay();
            });

            updateStatus("preview");
        } else {
            updateStatus("ready");
        }
    });
}

/**
 * Simplification slider handler.
 * Calls applySimplifyLevel in ExtendScript — instant from precomputed LOD.
 */
function requestSimplify() {
    if (!hasDetached) return;

    var sliderVal = parseInt(document.getElementById("simplifySlider").value, 10);

    csInterface.evalScript("pr_applySimplifyLevel(" + sliderVal + ")", function (result) {
        if (result && result.indexOf("error") !== 0) {
            document.getElementById("simplifiedCount").textContent = result;
            // Refresh overlay with new simplified path
            sendSimplifyOverlay();
        }
    });
}

/**
 * Apply: solidify detached paths with 80% black stroke, restore layer opacity.
 */
function applyDetached() {
    updateStatus("processing");

    csInterface.evalScript("pr_doApply()", function (result) {
        if (result && result.indexOf("applied") === 0) {
            clearOverlays();
            resetPanelState();
            updateStatus("ready");
        }
    });
}

/**
 * Reset: revert simplified paths to their original point data.
 */
function resetDetached() {
    if (!hasDetached) return;
    updateStatus("processing");

    csInterface.evalScript("pr_doReset()", function (result) {
        if (result && result.indexOf("reset") === 0) {
            var parts = result.split("|");
            var pointCount = parseInt(parts[1], 10) || originalPointCount;

            // Reset slider and display
            document.getElementById("simplifySlider").value = 0;
            document.getElementById("simplifyValue").textContent = "0";
            document.getElementById("simplifiedCount").textContent = pointCount;

            updateStatus("preview");
        }
    });
}

/**
 * Undo: remove all detached paths and bounding box guide.
 */
function undoDetach() {
    updateStatus("processing");

    csInterface.evalScript("pr_doUndoDetach()", function (result) {
        if (result === "undone") {
            clearOverlays();
            resetPanelState();
            updateStatus("ready");
        }
    });
}

// ── Panel State Management ────────────────────────────────────────

/**
 * Reset all panel controls to their default state.
 */
function resetPanelState() {
    hasDetached = false;
    originalPointCount = 0;
    bboxData = null;
    bboxCorners = null;

    // Disable controls
    document.getElementById("simplifySlider").disabled = true;
    document.getElementById("btnApply").disabled = true;
    document.getElementById("btnReset").disabled = true;
    document.getElementById("btnUndo").disabled = true;
    document.getElementById("btnAskClaude").disabled = true;

    // Reset displays
    document.getElementById("originalCount").textContent = "--";
    document.getElementById("simplifiedCount").textContent = "--";
    document.getElementById("simplifySlider").value = 0;
    document.getElementById("simplifyValue").textContent = "0";

    // Hide Claude response
    var claudeResp = document.getElementById("claudeResponse");
    if (claudeResp) claudeResp.style.display = "none";
}

// ── Slider & Checkbox Handlers ────────────────────────────────────

function initControls() {
    // Simplification slider — live preview on input
    var simplifySlider = document.getElementById("simplifySlider");
    var simplifyDisplay = document.getElementById("simplifyValue");
    simplifySlider.addEventListener("input", function () {
        simplifyDisplay.textContent = this.value;
        requestSimplify();
    });

    // Padding slider
    var paddingSlider = document.getElementById("paddingSlider");
    var paddingDisplay = document.getElementById("paddingValue");
    paddingSlider.addEventListener("input", function () {
        paddingDisplay.textContent = this.value + "pt";
    });

    // Show bounding box checkbox
    document.getElementById("showBBox").addEventListener("change", function () {
        if (hasDetached) {
            if (!this.checked) {
                // Remove PathItem bbox if plugin not connected
                if (!pluginConnected) {
                    csInterface.evalScript("removeBoundingBox()", function () {});
                }
                // Rebuild overlay without bbox
                sendSimplifyOverlay();
            } else {
                // Re-show: rebuild overlay with bbox
                sendSimplifyOverlay();
            }
        }
    });

}

// ── Accent Color ──────────────────────────────────────────────

/**
 * Toggle accent color between orange and cyan.
 * Persists to localStorage and syncs to ExtendScript.
 */
function toggleAccentColor() {
    accentColor = (accentColor === "orange") ? "cyan" : "orange";
    localStorage.setItem("pr_accentColor", accentColor);
    var btn = document.getElementById("btnAccentToggle");
    btn.textContent = accentColor;
    btn.style.color = (accentColor === "cyan") ? "#00c8dc" : "#ff8800";
    csInterface.evalScript("pr_setAccentColor('" + accentColor + "')", function() {});
}

function syncAccentColor() {
    var btn = document.getElementById("btnAccentToggle");
    btn.textContent = accentColor;
    btn.style.color = (accentColor === "cyan") ? "#00c8dc" : "#ff8800";
    csInterface.evalScript("pr_setAccentColor('" + accentColor + "')", function() {});
}

// ── Utilities ──────────────────────────────────────────────────────

function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ── Panel Visibility Lifecycle ─────────────────────────────────────

csInterface.addEventListener("com.adobe.csxs.events.WindowVisibilityChanged", function(event) {
    if (event.data === "true") {
        startSelectionPolling();
    } else {
        stopSelectionPolling();
    }
});

// ── Keyboard Shortcuts ────────────────────────────────────────────

document.addEventListener("keydown", function(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "Enter" && !document.getElementById("btnApply").disabled) {
        applyDetached();
    } else if (e.key === "Escape") {
        undoDetach();
    }
});

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initControls();
    syncAccentColor();
    csInterface.evalScript("pr_cleanupOrphans()", function() {});
    startSelectionPolling();
    connectPluginBridge();
    updateStatus("ready");
})();
