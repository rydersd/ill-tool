/**
 * Path Detach & Refine — Panel logic
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
    csInterface.evalScript("getSelectionInfo()", function (result) {
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

    csInterface.evalScript("detachAndPrecompute()", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus("ready");
            console.warn("[PathRefine] detachAndPrecompute:", result);
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

    csInterface.evalScript("applySimplifyLevel(" + sliderVal + ")", function (result) {
        if (result && result.indexOf("error") !== 0) {
            document.getElementById("simplifiedCount").textContent = result;
        }
    });
}

/**
 * Apply: solidify detached paths (remove dashes, make solid stroke).
 */
function applyDetached() {
    updateStatus("processing");

    csInterface.evalScript("doApply()", function (result) {
        if (result && result.indexOf("applied") === 0) {
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

    csInterface.evalScript("doReset()", function (result) {
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

    csInterface.evalScript("doUndoDetach()", function (result) {
        if (result === "undone") {
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

    // Disable controls
    document.getElementById("simplifySlider").disabled = true;
    document.getElementById("btnApply").disabled = true;
    document.getElementById("btnReset").disabled = true;
    document.getElementById("btnUndo").disabled = true;

    // Reset displays
    document.getElementById("originalCount").textContent = "--";
    document.getElementById("simplifiedCount").textContent = "--";
    document.getElementById("simplifySlider").value = 0;
    document.getElementById("simplifyValue").textContent = "0";
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
                csInterface.evalScript("removeBoundingBox()", function () {});
            }
            // Note: bounding box is computed during detach; re-showing would
            // require re-running minAreaRect. For now, toggling off removes it.
        }
    });
}

// ── Utilities ──────────────────────────────────────────────────────

function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initControls();
    startSelectionPolling();
    updateStatus("ready");
})();
