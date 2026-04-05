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
var operationInProgress = false; // guard against concurrent evalScript calls

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
 * Poll Illustrator selection to update the anchor/path count display
 * and show/hide group operation buttons based on context.
 * Runs on a 500ms interval so the panel shows live feedback.
 */
function pollSelection() {
    csInterface.evalScript("pr_getSelectionInfo()", function (result) {
        if (!result || result === "EvalScript Error" || result === "undefined") {
            document.getElementById("anchorCount").textContent = "0";
            document.getElementById("pathCount").textContent = "0";
            document.getElementById("inGroupLabel").style.display = "none";
            document.getElementById("groupOpsSection").style.display = "none";
            return;
        }

        // Parse pipe-delimited: "anchorCount|pathCount|inGroup"
        var parts = result.split("|");
        var anchorCount = parseInt(parts[0], 10) || 0;
        var pathCount = parseInt(parts[1], 10) || 0;
        var inGroup = (parts[2] === "1");

        document.getElementById("anchorCount").textContent = anchorCount;
        document.getElementById("pathCount").textContent = pathCount;

        // Show/hide group context indicator and operations
        document.getElementById("inGroupLabel").style.display = inGroup ? "inline" : "none";
        document.getElementById("groupOpsSection").style.display = inGroup ? "block" : "none";
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
    if (operationInProgress) return;
    operationInProgress = true;
    updateStatus("processing");

    var padding = 5;  // fixed padding (bounding box UI removed)
    var groupName = document.getElementById("groupName").value.replace(/'/g, "\\'").replace(/\\/g, "\\\\") || "";
    csInterface.evalScript("pr_detachAndPrecompute(" + padding + ", '" + groupName + "')", function (result) {
        operationInProgress = false;
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
        }
    });
}

/**
 * Apply: solidify detached paths (remove dashes, make solid stroke).
 */
function applyDetached() {
    if (operationInProgress) return;
    operationInProgress = true;
    updateStatus("processing");

    csInterface.evalScript("pr_doApply()", function (result) {
        operationInProgress = false;
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
    if (operationInProgress) return;
    operationInProgress = true;
    updateStatus("processing");

    csInterface.evalScript("pr_doUndoDetach()", function (result) {
        operationInProgress = false;
        if (result === "undone") {
            resetPanelState();
            updateStatus("ready");
        }
    });
}

// ── Group Operations ──────────────────────────────────────────────

/**
 * Detach selected items from their parent group, moving them to the layer.
 */
function detachFromGroup() {
    updateStatus("processing");
    csInterface.evalScript("pr_detachFromGroup()", function (result) {
        updateStatus("ready");
        if (result && result.indexOf("detached") === 0) {
            var parts = result.split("|");
            var count = parseInt(parts[1], 10) || 0;
            document.getElementById("anchorCount").textContent = count + " items detached";
        }
    });
}

/**
 * Split selected items into a new named group.
 */
function splitToNewGroup() {
    var groupName = document.getElementById("groupName").value.replace(/'/g, "\\'").replace(/\\/g, "\\\\") || "";
    updateStatus("processing");
    csInterface.evalScript("pr_splitToNewGroup('" + groupName + "')", function (result) {
        updateStatus("ready");
        if (result && result.indexOf("split") === 0) {
            var parts = result.split("|");
            var groupFinalName = parts[2] || "new group";
            document.getElementById("anchorCount").textContent = "Split to " + groupFinalName;
        } else if (result && result.indexOf("error") === 0) {
            document.getElementById("anchorCount").textContent = result.replace(/^error\|/, "");
        }
    });
}

// ── Isolation Mode Toggle ─────────────────────────────────────────

var _isolationActive = false;

/**
 * Toggle isolation mode on/off. Small button in the header.
 */
function toggleIsolation() {
    if (_isolationActive) {
        csInterface.evalScript("app.executeMenuCommand('deselectall'); app.executeMenuCommand('exitisolation')", function () {
            _isolationActive = false;
            document.getElementById("btnIsolation").style.borderColor = "#555";
        });
    } else {
        csInterface.evalScript("app.executeMenuCommand('isolate')", function () {
            _isolationActive = true;
            document.getElementById("btnIsolation").style.borderColor = "#7cb8f0";
        });
    }
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
        if (hasDetached) {
            undoDetach();
        } else if (_isolationActive) {
            toggleIsolation();
        }
    }
});

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initControls();
    csInterface.evalScript("pr_cleanupOrphans()", function() {});
    startSelectionPolling();
    updateStatus("ready");
})();
