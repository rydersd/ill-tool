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
var selectionPollId = null;      // timer for polling selection state
var lastSelectionState = "";     // last polled selection for change detection

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
            return;
        }

        var parts = result.split("|");
        // parts: [shape, confidence, inputCount, outputCount]
        updateDetected(parts[0], parseFloat(parts[1]));
        highlightShape(parts[0]);
        hasPreview = true;
        lastSelectionState = "";  // reset so polling can detect changes
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

// ── Selection Polling ──────────────────────────────────────────────

/**
 * Poll Illustrator selection to update the anchor/path count display.
 * When a preview is active and selection changes (user shift-deselects
 * points), re-run averaging on the current selection for live feedback.
 */
function pollSelection() {
    csInterface.evalScript("getSelectionInfo()", function (result) {
        if (!result || result === "EvalScript Error" || result === "undefined") {
            document.getElementById("selectionInfo").textContent = "No selection";
            return;
        }

        // Parse pipe-delimited: "anchorCount|pathCount"
        var parts = result.split("|");
        var anchorCount = parseInt(parts[0], 10) || 0;
        var pathCount = parseInt(parts[1], 10) || 0;

        if (anchorCount === 0) {
            document.getElementById("selectionInfo").textContent = "No selection";
        } else {
            document.getElementById("selectionInfo").textContent =
                anchorCount + " anchors on " + pathCount + " path" + (pathCount !== 1 ? "s" : "");
        }

        // Live re-average when preview is active and selection changes
        if (hasPreview && result !== lastSelectionState) {
            lastSelectionState = result;
            csInterface.evalScript("averageSelectedAnchors()", function (avgResult) {
                if (avgResult && avgResult.indexOf("error") !== 0) {
                    var avgParts = avgResult.split("|");
                    updateDetected(avgParts[0], parseFloat(avgParts[1]));
                    highlightShape(avgParts[0]);
                }
            });
        }
    });
}

function startSelectionPolling() {
    if (selectionPollId) return;
    selectionPollId = setInterval(pollSelection, 500);
}

function stopSelectionPolling() {
    if (selectionPollId) {
        clearInterval(selectionPollId);
        selectionPollId = null;
    }
}

// ── Panel Visibility Lifecycle ────────────────────────────────────

csInterface.addEventListener("com.adobe.csxs.events.WindowVisibilityChanged", function(event) {
    if (event.data === "true") {
        startSelectionPolling();
    } else {
        stopSelectionPolling();
    }
});

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

// ── Help Toggle ───────────────────────────────────────────────────

function toggleHelp() {
    var el = document.getElementById("helpText");
    el.style.display = el.style.display === "none" ? "block" : "none";
}

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initShapeButtons();
    initSliders();
    csInterface.evalScript("cleanupOrphans()", function() {});
    startSelectionPolling();
    // Run an immediate poll so selection shows right away
    pollSelection();
    updateStatus("ready");
})();
